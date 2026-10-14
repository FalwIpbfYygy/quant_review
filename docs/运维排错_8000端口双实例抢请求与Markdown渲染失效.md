# 运维排错：8000 端口双实例抢请求 & Markdown 渲染"失效"

> 记录一次 `/mindmap` 页面"AI 回复不渲染 Markdown + 访问接口无日志"的完整排查。
> 结论先行：**根因不是渲染代码 bug，也不是 uvicorn 关了日志，而是 8000 端口存在多实例竞争，请求被旧实例（旧模板）抢走。**

---

## 1. 背景

`quant_review` 项目的 `/mindmap`（思维导图知识库智能体）页面含三块能力：

- 智能体问答（BM25 检索，纯规则，不参与交易决策，硬合规闸门拦截方向/点位类提问）
- 知识库浏览
- 行情对话（接 LLM 做  真实行情分析，AI 回复用 Markdown 渲染）

为让 AI 回复在网页里直接渲染 Markdown，已落地的管线：

- `vendors/marked.min.js` + `vendors/purify.min.js`（离线 vendored，无需外网）
- 模板 `xau_mindmap_template.py` 的 `renderMD()` 函数（`marked.parse` + `DOMPurify.sanitize`）
- `.bub` 内 Markdown CSS（h1/h2/table/code/blockquote/ul/ol）
- 行情 `mSend()` 与知识库 `send()` 中 `esc(d.answer)` 全部替换为 `renderMD(d.answer)`

---

## 2. 症状（用户报告）

1. 访问 `/mindmap` 行情对话 tab，AI 回复**不渲染**：浏览器显示原始 `**趋势**`、`## 一、盘面定性`、`| 顶 | 数值 | 依据 |` 这类 Markdown 源码。
2. 用 `python -m uvicorn main:app --reload` 启动后，访问接口时**控制台没有访问日志打印**。

---

## 3. 根因（关键）

**8000 端口上有两个（或多个）进程同时 LISTENING，请求被内核随机分流——大部分被旧实例（跑早期无 Markdown 模板的代码）吃掉了。**

完整链路：

1. 用户最早在自己终端用 `python main.py` 起了旧实例（记为 PID 7256），一直没退。
2. 后来用户又用 `python -m uvicorn main:app --reload` 起新实例，但**该命令绕过了 `main.py` 自带的端口清理逻辑**，于是两个进程同抢 8000。
3. 内核随机把请求分给其中一个。旧实例（7256，旧模板）处理的请求，回复自然是无 Markdown 渲染的纯文本，且日志打印在旧终端（不可见）→ 用户侧表现为"没日志 + 不渲染"。
4. **netstat 假象（最坑的一点）**：某刻旧父进程 7256 已死，但 `multiprocessing` fork 出的子进程（PID 18232，孤儿进程）继承了 8000 的监听 socket；`netstat` 仍显示 `LISTENING 7256`（缓存了死父进程 PID），而 `taskkill /F /PID 7256` 报"没有找到进程"（rc=128）。**真正的占用者其实是 18232。**

---

## 4. 诊断命令

```bash
# 1. 看 8000 当前所有 LISTENING 及 PID
netstat -ano | grep ":8000" | grep LISTENING

# 2. 看所有 python 进程（以 tasklist 为准，别只信 netstat）
tasklist | grep -i python

# 3. 强杀进程
taskkill /F /PID <pid>
```

**判活原则（血泪经验）**：

> `netstat` 显示 `LISTENING` 的 PID **不等于**一定活着。
> - `netstat` 有该 PID、`tasklist` 无 → 该进程已死，且 netstat 是缓存显示；
> - 真正占用端口的是它的 **fork 子进程（孤儿）**，继承了 socket；
> - 去 `tasklist` 里找其父/子进程（同一命令行、`python -c "from multiprocessing.spawn..."` 的 fork 子）杀掉才是真解决。

---

## 5. 解决方案

1. 杀掉所有占用 8000 的 python 进程（含 fork 子进程），确保 8000 完全释放（`netstat` 复检为空）。
2. 用**唯一推荐方式**启动单实例：
   ```bash
   cd D:/quant_review
   D:\sortware\python_3_10\python.exe main.py
   ```
   `main.py` 自带 `_free_port()`（netstat + taskkill 端口清理），且 `uvicorn.run(reload=False)`。
3. 浏览器对 `/mindmap` 按 **Ctrl+F5 强刷**（清掉缓存的旧 JS，否则 `marked/purify/renderMD` 与导航栏新按钮都不会更新）。

---

## 6. 启动方式约定（已在 `main.py` 注释固化）

| 方式 | 结论 |
|------|------|
| `python main.py` | ✅ 推荐：单实例，自带端口清理，改代码后手动重启即可 |
| `python -m uvicorn main:app --reload` | ❌ 禁止：绕过端口清理；本机 `--reload` 一改代码就崩（`SystemError`），且易与残留实例同抢 8000 导致请求随机分流 |

`main.py` 原注释（节选）：
> 否则若之前有过残留实例 / 另一个 uvicorn 在跑，直接 `uvicorn.run` 会报 address already in use，或两个实例同抢 8000 导致请求被随机分流。
> 不用 `--reload`：这台机器上 uvicorn `--reload` 一改代码就崩（SystemError），关掉最稳；改代码后手动重跑本文件即可。

单实例时，uvicorn 访问日志正常打印，例如：
```
INFO:     127.0.0.1:13245 - "GET /static/components/topnav.js HTTP/1.1" 304 Not Modified
INFO:     127.0.0.1:5785 - "GET /api/sync/status HTTP/1.1" 200 OK
```

---

## 7. 验证清单

- [ ] `netstat -ano | grep :8000 | grep LISTENING` 只剩 **1 个** PID
- [ ] 启动日志出现 `Application startup complete.`
- [ ] 访问接口时终端**正常打印访问日志**
- [ ] 浏览器 Ctrl+F5 后，AI 回复里的 `##` / `**` / 表格 渲染正确
- [ ] 顶部导航栏出现"思维导图库"按钮
