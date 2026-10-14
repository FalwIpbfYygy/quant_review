# -*- coding: utf-8 -*-
"""
每月脉冲：月初自动跑一次 → 生成「当月前瞻整月日历」文档落 outputs/，并推飞书
（附「上月关键已公布读数回顾」小节，取自金十当前周已公布行，如实标注来源）。

用法（每月 1 日 08:30 由自动化触发）：
    python monthly_pulse.py [--dry]     # --dry 不推飞书，仅生成本地文档并打印推送预览

数据口径与 gen_month_doc 一致：金十实时=当前自然周(含 actual)，排期推算=官方排期锚点。
无未来信息、无虚构；金十 MCP 只能给当前自然周，故“上月复盘”仅能取到与当前周重叠的已公布行，
其余如实说明。
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, json, argparse, urllib.request
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, "outputs")

# ── 飞书机器人 webhook（来自 config，环境变量注入，不再硬编码）────────
from config import FEISHU_MC_WEBHOOK as FEISHU_WEBHOOK

import gen_month_doc as GMD
from core import month_cal
from data import jin10


def _next_ym():
    d = date.today()
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return y, m


def _feishu(text):
    payload = {"msg_type": "text", "content": {"text": text}}
    req = urllib.request.Request(
        FEISHU_WEBHOOK, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read().decode("utf-8")


def _pull_current_week_done():
    """取金十当前自然周里『已公布且美国/黄金主线』的行，用于上月回顾（如实）。"""
    try:
        rows = jin10.get_calendar_week()
    except Exception:
        return []
    out = []
    core = ["非农", "失业率", "平均时薪", "CPI", "PPI", "PCE", "初请", "ADP", "零售销售",
            "GDP", "JOLT", "职位空缺", "利率决议", "美联储", "核心"]
    for r in rows or []:
        act = r.get("actual")
        if act in (None, ""):
            continue
        t = r.get("title", "")
        if len(t) < 4 or any(n in t for n in month_cal._J10_NOISE):
            continue
        if not any(k in t for k in ["美国", "美联储", "非农", "失业", "CPI", "PPI", "PCE",
                                    "初请", "零售", "GDP", "ISM", "JOLT", "ADP"]):
            continue
        # 去次级噪声：非核心关键词、且低于 3★ 的细分指数（如 ISM 分项）不收录，避免刷屏
        if (r.get("star") or 0) < 3 and not any(k in t for k in core):
            continue
        out.append(r)
    # 按时间倒序，取最近 ~12 条
    out.sort(key=lambda r: str(r.get("pub_time", "")), reverse=True)
    return out[:12]


def build_pulse(dry=False):
    today = date.today()
    ny, nm = _next_ym()

    # 1) 生成本月/下月整月文档（写文件）
    doc_path, total, src = GMD.build_doc(ny, nm)
    print(f"[gen] {ny}-{nm:02d} 前瞻文档: {doc_path}  total={total} src={src}")

    # 2) 组装飞书文本
    quote = {}
    try:
        quote = (jin10.get_quotes([""]) or {}).get("", {})
    except Exception:
        pass
    close = quote.get("close", "—")
    chg = quote.get("ups_percent", "—")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    L.append(f"📅  月度宏观前瞻 · {ny}年{nm}月")
    L.append(f"现货黄金 ${close}（{chg}%）· 生成 {now}")
    L.append("")

    # 上月回顾（金十当前周已公布）
    done = _pull_current_week_done()
    if done:
        L.append(f"【近日已公布主线实况回顾】（金十实时 · 当前自然周内已披露的美国/黄金主线，含实际值）")
        L.append("注：金十 MCP 仅返回当前自然周，故只能回顾最近数日已落地的读数；上月更早事件以 outputs/ 复盘文档为准。")
        L.append("最近几项美国/黄金主线实际值：")
        for r in done[:6]:
            st = f"实际={r.get('actual')}" if r.get("actual") not in (None, "") else ""
            con = f" 预期={r.get('consensus')}" if r.get("consensus") not in (None, "") else ""
            pre = f" 前值={r.get('previous')}" if r.get("previous") not in (None, "") else ""
            star = "★" * min(5, r.get("star") or 0)
            tm = str(r.get("pub_time", ""))[:16]
            L.append(f"  · {tm} {star} {r.get('title')}｜{st}{con}{pre}")
        L.append("")
    else:
        L.append(f"【近日已公布回顾】金十当前自然周暂无已公布美国主线读数可回溯，详见 outputs/ 对应月份文档。")
        L.append("")

    # 当月/下月前瞻：抽取 5★/4★ 主线
    cal = month_cal.month_calendar(ny, nm, jin10_rows=jin10.get_calendar_week())
    anchors = []
    for w in cal.get("weeks", []):
        for e in w["events"]:
            if e.get("star", 0) >= 4 or any(k in e["title"] for k in ["FOMC", "非农", "CPI", "PCE"]):
                anchors.append(e)
    anchors.sort(key=lambda x: (x["date"], x["time"]))
    if anchors:
        L.append(f"【{ny}年{nm}月·关键日程前瞻】")
        last_d = None
        for e in anchors:
            md = e["date"][5:].replace("-", "/")
            pre = "  └" if last_d == md else ""
            last_d = md
            L.append(f"  · {e['date'][5:].replace('-','月')}日{pre} {e['title']}（{e['time']}，{'★'*e['star']}）")
        L.append("")
    L.append(f"完整分周表见 {os.path.basename(doc_path)}（含逐条来源标注/筛选口径）。")
    L.append("数据双源：🟥金十实时(当周已披露)/⬜排期推算(官方锚点)；仅供决策参考，非投资建议。")
    text = "\n".join(L)

    if dry:
        print("=== [dry] 飞书推送预览 ===")
        print(text)
        print("=== end ===")
        return doc_path, None

    status, body = _feishu(text)
    print(f"[feishu] status={status} body={body[:120]}")
    return doc_path, (status, body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="不推飞书，仅生成文档+打印预览")
    a = ap.parse_args()
    p, push = build_pulse(a.dry)
    print(f"done doc={p}")
