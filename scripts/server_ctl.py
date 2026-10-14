#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quant_review 本地服务管理脚本 (Windows)
解决三件事:
  1. uvicorn --reload 启动的是 "reloader 父进程 + worker 子进程" 两棵树,
     只杀监听端口的 worker 杀不干净, 必须按进程树一起杀。
  2. 不用再手动 netstat 查 PID。
  3. 防止多个 uvicorn 同时监听 8000: uvicorn 默认 SO_REUSEADDR, Windows 允许两个进程
     同时 listen 同一端口, 但请求会被内核随机分流 -> 部分接口的访问日志打在另一个
     实例上 (表现就是"有些接口的日志没了")。start/run 启动前会拦截端口被外来进程占用,
     stop 会按进程树清掉端口上所有监听者。

用法 (在 D:\\quant_review 下执行):
  python server_ctl.py start     以 uvicorn --reload 后台启动 (DETACHED, 日志 server.log; 控制器退出后服务仍运行)
  python server_ctl.py run       前台阻塞运行 (Ctrl+C 退出; 适合用 run_in_background 常驻, 日志直接输出)
  python server_ctl.py stop      停止 (按进程树杀掉端口上所有监听进程, 含外来实例)
  python server_ctl.py restart    stop + start
  python server_ctl.py status     查看运行状态 (标出本脚本管理 / 外来进程)
"""
import subprocess
import sys
import os
import time

PY   = r"D:\sortware\python_3_10\python.exe"   # 装了 fastapi/uvicorn/openai/pymysql 的解释器
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根（随脚本位置自适应）
HOST = "127.0.0.1"
PORT = 8000
LOGF = os.path.join(ROOT, "server.log")
PIDF = os.path.join(ROOT, ".server.pid")
DETACHED = 0x00000008  # subprocess.DETACHED_PROCESS (Windows)


def _listener_pids():
    """返回所有 LISTENING 在 PORT 上的进程 PID 列表 (SO_REUSEADDR 下可能不止一个)。

    注意: 中文 Windows 下 netstat 输出是 GBK, 必须用 bytes + decode("gbk") 解码,
    不能用 text=True(utf-8), 否则抛 UnicodeDecodeError。
    """
    pids = []
    try:
        out = subprocess.run(["netstat", "-ano"],
                             capture_output=True, timeout=10).stdout
    except Exception:
        return pids
    if not out:
        return pids
    text = out.decode("gbk", errors="ignore")
    for line in text.splitlines():
        if (":%d " % PORT) in line and "LISTENING" in line:
            try:
                pids.append(int(line.split()[-1]))
            except ValueError:
                pass
    # 去重保序
    seen, uniq = set(), []
    for p in pids:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _listener_pid():
    """兼容旧调用: 返回第一个监听 PID, 没有则返回 None。"""
    pids = _listener_pids()
    return pids[0] if pids else None


def is_up():
    return bool(_listener_pids())


def _our_pid():
    """读取 pidfile 中本脚本管理的 reloader PID (可能已死)。"""
    if os.path.exists(PIDF):
        try:
            return int(open(PIDF).read().strip())
        except Exception:
            pass
    return None


def _guard_port():
    """启动前检查端口占用。

    返回 True  = 可以安全启动
    返回 False = 已被占用, 已打印提示, 调用方应直接 return 不启动
    """
    pids = _listener_pids()
    if not pids:
        return True
    our = _our_pid()
    foreign = [p for p in pids if p != our]
    # 仅本脚本管理的实例在跑 -> 提示无需重复启动
    if not foreign and our is not None:
        print("[*] 本脚本管理的实例已在运行 (PID %d): http://%s:%d"
              % (our, HOST, PORT))
        print("    无需重复启动; 如需重启请用: python server_ctl.py restart")
        return False
    # 有外来进程占用端口 -> 拒绝重复启动, 给出可执行的处理命令
    print("[!] 端口 %d 已被其他进程占用 (可能是另一个 uvicorn), 不能重复启动:"
          % PORT)
    for p in foreign:
        print("      - 外来监听进程 PID %d" % p)
    if our is not None:
        print("      - 本脚本实例 PID %d" % our)
    print("    原因: uvicorn 默认 SO_REUSEADDR, 两个实例可同时监听同端口, 但请求会被")
    print("          内核随机分流, 导致部分接口的访问日志打在另一个实例上 (就是你之前")
    print("          遇到的'日志丢失'现象)。")
    print("    处理 (二选一):")
    for p in foreign:
        print("      a) 结束外来进程:  taskkill /PID %d /T /F" % p)
    print("      b) 统一用本脚本管理: python server_ctl.py stop  (按进程树杀掉端口上所有监听者)")
    return False


def _kill(pid, tree=False):
    cmd = ["taskkill", "/PID", str(pid), "/F"]
    if tree:
        cmd.append("/T")
    # taskkill 中文输出是 GBK, 用 bytes 避免 utf-8 解码异常
    subprocess.run(cmd, capture_output=True)


def start():
    if not _guard_port():
        return
    print("[*] 启动 uvicorn --reload @ %s:%d ..." % (HOST, PORT))
    try:
        with open(LOGF, "a", encoding="utf-8", buffering=1) as lf:
            proc = subprocess.Popen(
                [PY, "-m", "uvicorn", "main:app", "--reload",
                 "--host", HOST, "--port", str(PORT)],
                cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT,
                creationflags=DETACHED, close_fds=True,
            )
    except Exception as e:
        print("[!] 启动失败:", e)
        return
    # proc.pid 是 reloader 父进程 PID, 杀它 (/T) 会连带杀掉 worker
    with open(PIDF, "w") as f:
        f.write(str(proc.pid))
    for _ in range(30):
        time.sleep(1)
        if is_up():
            print("[+] 已启动 (reloader PID %d, 日志 %s)"
                  % (proc.pid, LOGF))
            return
    print("[!] 启动超时, 查看日志: %s" % LOGF)


def stop():
    up_before = bool(_listener_pids())
    # 1) pidfile 记录的 reloader: 杀整棵树
    our = _our_pid()
    if our is not None:
        _kill(our, tree=True)
        try:
            os.remove(PIDF)
        except OSError:
            pass
    # 2) 兜底: 杀掉端口上所有监听进程 (整棵树), 含外来实例
    for p in _listener_pids():
        _kill(p, tree=True)
    # 3) 轮询直到端口释放
    for _ in range(20):
        if not _listener_pids():
            break
        time.sleep(0.5)
    if _listener_pids():
        pids = _listener_pids()
        print("[!] 端口 %d 仍被占用 (PID %s)。这些进程可能不是本脚本启动的, "
              "请在任务管理器结束 uvicorn 后重试。" % (PORT, pids))
    else:
        print("[+] 已停止" if up_before else "[*] 本就未运行")


def restart():
    stop()
    time.sleep(1)
    start()


def run_foreground():
    """前台阻塞运行 (适合 run_in_background 常驻; Ctrl+C 退出, 进程受 pidfile 管理)。"""
    if not _guard_port():
        return
    print("[*] 前台运行 uvicorn --reload (Ctrl+C 退出) ...")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "main:app", "--reload",
         "--host", HOST, "--port", str(PORT)],
        cwd=ROOT,
    )
    with open(PIDF, "w") as f:
        f.write(str(proc.pid))
    try:
        proc.wait()
    except KeyboardInterrupt:
        _kill(proc.pid, tree=True)
    finally:
        if os.path.exists(PIDF):
            try:
                os.remove(PIDF)
            except OSError:
                pass


def status():
    pids = _listener_pids()
    our = _our_pid()
    if not pids:
        print("[*] 未运行")
        return
    print("[*] 端口 %d 监听中, 共 %d 个进程:" % (PORT, len(pids)))
    for p in pids:
        tag = " (本脚本管理)" if p == our else " (外来 / 手动启动)"
        print("      - PID %d%s" % (p, tag))
    print("    访问: http://%s:%d" % (HOST, PORT))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"start": start, "stop": stop, "restart": restart,
     "status": status, "run": run_foreground}.get(
        cmd,
        lambda: print("用法: python server_ctl.py [start|stop|restart|status|run]"),
    )()
