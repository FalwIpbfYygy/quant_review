# quant_review — AI 开发上下文（AGENTS.md）

> 给"未来的 AI 同事"看的项目说明书。**新开会话、新需求时，先读这个文件**，即可在不通读整个仓库的情况下安全开发。
> 用户：本地个人使用（ 量化 / 黄金日内交易复盘）。沟通偏好：一句话结论先行 + 结构化要点 + 全中文；改代码前先对齐方案；拒绝动既有功能（只新增 / 只修 bug）。

---

## 1. 项目是什么

本地运行的 **（现货黄金）交易复盘 + 每日交易计划 + AI 分析师报告** Web 应用。

- 多周期 K 线四分屏复盘、K 线回放、实时图表、信号复盘
- 交易心理 / 交易惯性记录
- 市场环境看板（ 关联资产、金十消息面）
- **每日交易计划（核心新增）**：基于 Binance 期货  5m，v2 突破跟随 PDH/PDL 信号，生成可实盘的计划 + 回测 + 百炼大模型报告

技术栈：**FastAPI + uvicorn（禁用 --reload）** / 前端 **Vue3 global build + ECharts + marked + DOMPurify**（全部本地 vendored，无构建步骤）/ 数据 **Binance fapi（，零偏移）** + **TwelveData（DXY 合成 + 交叉盘）** / 大模型 **阿里云百炼（OpenAI 兼容网关）**。

---

## 2. 目录结构与模块职责（权威清单）

```
main.py                  唯一后端入口。所有路由 + uvicorn 一键启动逻辑都在这里。
config.py                DB 配置 + 百炼大模型配置（BAILIAN_MODEL / API_KEY / BASE_URL / WORKSPACE_ID）。
data/db.py + data/data_sync.py   本地 MySQL（ 库，kline_1m/5m/15m/30m 表）+ 行情同步线程。PROXIES 也在这里。
core/xau_report.py       ★ 每日计划核心引擎（v2 突破跟随）。纯计算 + fetch_fn 注入，不直连网络。
pages/xau_report_template.py    /xau 页面 HTML（内联常量，避开 .html 被同步工具覆写）。
core/wuyuan_core.py      ★ 乌圆狩猎区档位引擎。**唯一入口 = 自研腿 auto_leg**（系统自己取日线、
                         自己算腿端、自己判方向、自己出档位，零人工输入）。
                         纯计算：无网络、无第三方依赖。
                         ⚠ **人工输入路径已全部移除**（四线反解 invert / 单档 from_single /
                           反推 guess_s / 敏感性 sens_rows 及 slim_inv 均已删除，勿再引用）。
                         ⚠ 自研腿**不是已验证策略**：六门槛 5 FAIL；样本外实证过拟合
                           （IS 最优 +70.4R t=3.30 → OOS −14.1R t=−0.84，10 规则仅 1 个 OOS 为正）。
                           仅作结构生成器，输出必带 verdict/tag/auto_warnings，前端不得隐去。
                         ⚠ 两道闸门别混：min_r_bp=15 是**结构宽度**下限；
                           COST_FLOOR_BP=100 是**可交易性**下限（实测 taker 往返 10bp × 10 安全垫）。
                           不过成本地板不拒绝出图，只置 tradable=False + trade_note 告警。
                         ⚠ 闸门比较用 1e-9 相对容差：浮点除法恰达闸门时裸 `<` 会误判。
                         ⚠ 取数失败**明确报错（502），绝不猜一个 S 出来**。
pages/wuyuan_template.py /wuyuan 页面 HTML（内联常量）；Options API + 运行时生成的内联 SVG 档位图。
                         **只有自研腿一个按钮**，无任何输入框。
data/xau_macro.py        TwelveData 宏观：6 外汇对按 ICE 公式合成 DXY + EURUSD/GBPUSD/AUDUSD。15min 缓存。
core/daily_report_ai.py  百炼大模型报告生成（OpenAI client + 3500 字 5 模块 SYSTEM_PROMPT）。
core/ai_report.py        ★ 旧链路：基于本地 MySQL K 线的 AI 复盘报告（stream/非 stream/多轮对话）。
core/ai_store.py         复盘历史库（json 落盘；ai_history.html 为运行时产物）。
core/backtest.py + data/binance_src.py   旧回测（本地库 / Binance 实时）引擎。
core/daily_plan.py       ★ 旧每日计划链路（依赖 MySQL kline_*m 表）。/api/dailyplan/* 走它 —— 属遗留。
pages/trade_template.py  /trade 页面（旧每日计划 UI，/dailyplan 302 跳转目标）。
web/                     独立 HTML 页面（web/index.html / realtime.html / replay.html /
                        review.html / psych.html / market.html / habits.html + mockups/ 原型稿）。
                        注意：其余页面 HTML 由 pages/*.py 内联常量返回；ai_history.html 为运行时产物。
static/components/topnav.js + topnav.css   ★ 共享导航 Web Component（NAV 数组 = 唯一权威源）。
vendors/                 vendored 前端库：echarts / marked / purify / vue.global.prod.js。
data/jin10.py + core/month_cal.py   金十数据代理 + 整月消息面日历。
data/market.py / core/psych.py / data/data_sync.py  各功能后端模块。
scripts/server_ctl.py    服务控制脚本（ROOT 随脚本位置自适应）。
core/ data/ huntzone/ pages/        业务引擎 / 数据层 / 狩猎区 / 页面模板四个包。
docs/ outputs/ scripts/ research/ DataBase/   文档 / 产物 / 脚本 / 独立研究 / 数据库相关。
```

**两条每日计划链路（务必分清）：**
- ✅ **当前推荐**：`/xau` + `core/xau_report.py` + `pages/xau_report_template.py` + `data/xau_macro.py` + `core/daily_report_ai.py`。数据源直连价格接口基址（`BINANCE_FAPI_BASE`），**不依赖 MySQL、无 PAXG+12 偏移**。新需求一律在这条链路上加。
- ⚠️ **遗留**：`/dailyplan`(302→`/trade`)、`pages/trade_template.py`、`/api/dailyplan/*`、`core/daily_plan.py`。依赖本地 MySQL，属旧设计。不要在新需求里扩展它，除非用户明确要求。

---

## 3. 路由清单（来自 main.py，可直连验证）

页面：`/`、`/replay`、`/realtime`、`/review`、`/ai_history`、`/psych`、`/habits`、`/market`、`/xau`、`/wuyuan`、`/trade`（`/dailyplan` 与 `/dailyplan_page` 为 302/410 重定向，已废弃）。

API（节选关键）：
- `/api/realtime/klines?symbol=&interval=1m&limit=1000` — 实时 K 线代理（前端经它访问 fapi，避开跨域）。
- `/api/xau/plan?asof=YYYY-MM-DD HH:MM` — 当前每日计划（默认 BJ 09:00）。
- `/api/wuyuan/ladder?open_px=&offset=&live=` — 乌圆狩猎区档位表。**自研腿是唯一路径**：
  系统自己取日线算腿、判方向、出档位，**可以不传任何参数**（零输入）。
  `open_px` 仅作可选覆盖（缺省由服务端取当日开盘价 = 100.0 档）。
  ⚠ 已删除的入参（传了会被忽略）：`lines` / `ref` / `at` / `S` / `dir` / `close` / `auto`。
  ⚠ 取数失败 → **502 + 明确 error，绝不猜腿**；结构不可用时 → `code:200, ok:false, reason`（规则的一部分）。
  返回 `auto{rule,lookback,r_bp,min_r_bp,cost_floor_bp,tradable,trade_note,offset,prev_close,P0,tag,verdict}`
  + `auto_warnings[]`（4 条过拟合/成本实证警示）。前端必须原样展示，**不得隐去**。
  实测：多数量级下 `tradable=False`（15m 级结构止损仅 16.8bp，远低于成本地板 100bp）。
- `/api/xau/backtest?start=2026-08-07&end=2026-09-04` — 月回测。
- `/api/xau/report?asof=...` — 聚合 fapi 计划 + TwelveData 宏观 + 百炼报告，返回 Markdown。
- `/api/dailyplan/plan|backtest|report` — 旧链路（MySQL），遗留。
- `/api/ai/summary[|/stream]`、`/api/ai/chat[|/stream]`、`/api/ai/history` — AI 复盘。
- `/api/jin10/quotes|calendar|flash|gold_news|month_cal` — 金十。
- `/api/market/overview|trend|correlations` — 市场看板。
- `/api/sync/db|data|status` — 行情同步。
- `/api/kline/review|fastrange` — 历史 K 线查询（本地 MySQL）。

---

## 4. 不可违反的红线（CRITICAL）

1. **启动永远不用 `--reload`**。本机 uvicorn `--reload` 改代码即崩（SystemError / worker SIZE=0 崩溃循环）。改完代码手动重跑 `python main.py`。
2. **数据源零偏移**。用价格接口基址（`BINANCE_FAPI_BASE`）的 ****，绝不用 PAXGUSDT + 12 偏移对齐。
3. **前端不直接连 fapi**。前端 → `/api/...` → 后端 `requests` + `data_sync.PROXIES`。新增数据接口必须走后端代理（跨域 + 代理 + 缓存都在后端）。
4. **导航单一权威源**。`static/components/topnav.js` 里的 `NAV` 数组是全部导航项的唯一来源。新增导航项**只改这个数组**，页面里用 `<topnav-bar data-active="/xau">`。绝不在各页硬编码链接（曾经因此漏链）。
5. **页面 HTML 内联进 .py 常量**，不要用独立 `.html` 文件承载关键页面——曾被同步/Notion 工具循环覆写导致白屏。现存独立 `.html`（index/replay 等）是历史遗留，新页面请仿 `xau_report_template.py` 用常量。
6. **反未来函数**。回测严格因果，`close_time` 为信号戳；asof 截断只取 `open_time <= asof_ms` 的 bar。
7. **红涨绿跌**（中国习惯）：上涨红、下跌绿。大模型 prompt 与 UI 均遵守。
8. **DOMPurify 保留 `<font color>`**：渲染 AI 报告时 `DOMPurify.sanitize(raw, {ADD_TAGS:['font'], ADD_ATTR:['color']})`，否则红绿标注被剥掉。

---

## 5. 这次踩过的坑（经验教训，避免重蹈）

以下问题在"做每日计划页"时各出现至少一次，逐个排查才根治：

| # | 现象 | 根因 | 解法 |
|---|------|------|------|
| 1 | 页面空白 / `{{ }}` 原样显示 / Vue 不挂载 | 浏览器 **304 缓存**了早期 f-string 泄漏的坏 HTML（磁盘代码早已修，但缓存没更新） | 换**全新 URL 路径**（/xau，避开 /dailyplan 历史缓存）+ 响应头强反缓存 `no-store, no-cache` |
| 2 | 改了 HTML 第二天又被打回旧版 | **同步/Notion 工具循环覆写** `dailyplan.html` | 页面 HTML 改为 `.py` 内联常量，删除独立 `.html` |
| 3 | uvicorn worker 全死（日志 SIZE=0） | `--reload` 在本机崩溃循环 | 启动参数 `reload=False`；改代码手动重启 |
| 4 | 端口 8000 偶发 "address already in use" / 请求被分流 | **Windows ghost socket**（旧实例残留） | `main.py` 已内置 `_free_port()` 启前清场；或 `quant_review_PORT=8080` 临时换端口 |
| 5 | 计划价位整体错位 | 误用 **PAXGUSDT + 12 偏移**而非真实  | 直连价格接口基址（`BINANCE_FAPI_BASE`），零偏移 |
| 6 | AI 报告红绿标注消失 | DOMPurify 默认剥离 `<font color>` | sanitize 加 `ADD_TAGS:['font'], ADD_ATTR:['color']` |
| 7 | 导航栏缺"交易计划"链接 | 各页**硬编码** nav，新增页面漏改 | 抽成 `topnav.js` Web Component，`NAV` 单一权威源 |
| 8 | 导航组件化误删 `<topnav-bar>` 兄弟节点（同步按钮） | `<header>` 内的 `.topnav-actions` 一起被删，浮窗和 JS 还在 | **改造组件时只动目标节点，别带兄弟**；同步按钮在 4 页手动补回（`index` / `realtime` / `replay` / `review`） |
| 9 | 点"校验库/同步行情"**有反应但看不到日志** | JS 顶层引了**HTML 里不存在的 ghost ID** `syncDbDot`/`syncDataDot` → `setDot(null, cls)` 抛 TypeError → `pollStatus` 的 `catch(e){/* 静默 */}` 把错误吞掉 → 状态点/状态文字/日志轮询整个哑火 | `setDot` 永远带 `if (el)` null 守卫；**`catch(e){}` 是高危静音模式**，异步轮询失败要么 throw 要么 `console.error`，别静默 |
| 8 | 同步数据库按钮"凭空消失" | 导航组件化改造时只替换了 `<nav>` 块，把紧邻的 `.topnav-actions`（校验库/同步行情按钮）**兄弟节点**一起删了，浮窗+JS 残留 → 功能看似丢失、JS 报错 null | header 内 `<topnav-bar>` 与同步按钮是**兄弟节点**；组件化只动 `<topnav-bar>` 本身，**绝删其兄弟**。已修复：index/realtime/replay/review 4 页 header 补回 `.topnav-actions`（syncDbBtn→/api/sync/db，syncDataBtn→/api/sync/data） |

**核心方法论**：每次"改了没生效"，先怀疑（a）浏览器缓存 / （b）被外部同步工具覆写 / （c）旧进程没杀干净 / （d）数据源/偏移错，再怀疑逻辑。用 `curl -I` + 反缓存头 + 全新 URL 快速隔离。

---

## 6. 如何运行

```bash
cd D:/quant_review
python main.py          # 不要加 --reload。自动清 8000 端口 + 自动开浏览器
```
- 默认 `http://127.0.0.1:8000/`。临时换端口：`set quant_review_PORT=8080 && python main.py`（Windows）。
- 依赖：`fastapi`, `uvicorn`, `requests`, `openai`, `pandas`（及本地 MySQL 仅旧链路需要）。vendored 前端库已随仓库，无需 npm。

---

## 7. 如何新增页面 / 功能

**新增导航项（最常见需求）：**
1. 打开 `static/components/topnav.js`，在 `NAV` 数组加一项 `{ path:'/newpath', label:'新页', icon:'<svg.../>' }`。
2. 新页面 HTML 里放 `<link rel="stylesheet" href="/static/components/topnav.css">` + `<topnav-bar data-active="/newpath">` + `<script src="/static/components/topnav.js" defer></script>`。
3. `main.py` 加路由返回 HTML（**用 .py 内联常量**，仿 `xau_report_template.py.HTML`），并加 `no-store` 反缓存头。
4. 若需数据：加 `/api/...` 路由，后端 `requests` + `data_sync.PROXIES` 取数，前端只调 `/api`。

**修改每日计划逻辑：**
- 信号/计划规则在 `xau_report.py` 的 `make_plan()` / `run_day()` / `backtest_range()`。
- 策略参数集中在 `xau_report.py` 顶部 `CFG` 字典（止损 ATR 倍数、TP1/TP2 倍数、账户、单笔风险等），改这里即可调参。
- 宏观数据在 `xau_macro.py`；AI 报告 prompt 在 `daily_report_ai.py` 的 `SYSTEM_PROMPT`。
- 永不在引擎内直连网络：`xau_report.py` 的 `fetch_fn` 由 `main.py._fapi_fetch` 注入（复用 `data_sync.PROXIES`）。

---

## 8. 数据来源与密钥（当前值，改动请同步本文件）

- **行情**：价格接口基址（由 `.env` 的 `BINANCE_FAPI_BASE` 配置）的 `/fapi/v1/klines?symbol=&interval=5m&limit=1000`（主决策 5m；realtime 页用 1m）。代理统一走 `config.PROXIES`（**默认直连**；本地 Windows 出网在 `.env` 设 `KLINE_PROXY` 或标准 `HTTP_PROXY`/`HTTPS_PROXY`，源码不再硬编码任何代理地址）。
- **百炼大模型**（`config.py`，全部来自环境变量，见 `.env.example`）：
  - `BAILIAN_MODEL`：来自环境变量 `BAILIAN_MODEL`（缺省 `qwen3-max`，可在 `.env` 覆盖）。
  - `BAILIAN_API_KEY`：来自环境变量 `BAILIAN_API_KEY` / `DASHSCOPE_API_KEY`；**仓库内无默认值**，未配置则 AI 功能不可用。
  - `BAILIAN_WORKSPACE_ID`：来自环境变量（用于拼私有空间 `compatible-mode/v1` 网关 URL），源码不再硬编码。
  - `BAILIAN_BASE_URL`：优先显式环境变量，其次按 workspace 拼，再回退公共 DashScope 网关（**无联网检索**，模型只能依据注入的结构化数据）。
  - 客户端：`from openai import OpenAI`，`timeout=600`。
- **TwelveData**（`xau_macro.py`）：`TWELVEDATA_API_KEY` 来自环境变量；**仓库内无默认值**。免费版限流 8 次/分、800 次/天；模块已做 1s 间隔 + 15min 缓存 + 失败降级（返回 None 不抛异常）。DXY 用 ICE 公式 6 外汇对合成。

---

## 9. 给未来 AI 的速查清单

- 改代码 → **杀掉旧 uvicorn** → `python main.py`（无 --reload）→ 隐身窗口开新 URL 验证（避开 304）。
- 动每日计划 → 只碰 `core/xau_report.py` / `pages/xau_report_template.py` / `data/xau_macro.py` / `core/daily_report_ai.py` + `main.py` 对应路由。
- 加导航 → 只改 `topnav.js` 的 `NAV`。
- 前端要数据 → 必须走 `/api/...`，后端代理 fapi，前端绝不直连。
- 渲染 AI 报告 → DOMPurify 保留 `font`/`color`。
- 不确定根因 → 先查缓存 / 外部覆写 / 端口占用 / 数据源偏移 / **JS ghost ID + 静默 catch**，再查逻辑。
- 引用任何 DOM ID → **先 grep 确认 HTML 里真实存在**；`getElementById` 对 null 不报错但下游 `.className = ...` 必抛。
- 改完**内联 Vue 页面** → 跑技能 `inline-vue-html-guard` 的四道闸门。注意本项目两种 API 风格并存：
  `*.html` 那 8 个页面是 **Composition API**（用 `scripts/check_inline_vue.py`）；
  **`.py` 内联模板页**（`xau_report_template.py` / `wuyuan_template.py`）是 **Options API**，
  要用同技能的 `scripts/check_options_api_expose.py`，否则会被"全部绑定未暴露"的假故障误导。
- 新增页面还要过两道机械闸：**CSS 变量一致性**（`var(--x)` 必须都在 `:root{}` 定义 ——
  `xau_report_template.py` 曾因 `--txt`/`--accent` 未定义丢掉 h3 蓝色）、
  **前后端字段契约**（前端 `res.*` ⊂ 接口实际返回的 key）。
- 写 `catch (e) {}` → 想清楚：异步轮询里"静默"会让用户看不到任何反馈，必须有可见的副作用（`console.error` / 状态栏兜底 / 浮窗文字提示）。
- 改 Web Component 的 host 时只动 host 自身（`this.innerHTML`），**别删 host 之后的兄弟节点**（同步按钮就吃过这个亏）。

---

## 10. 周期研判方法论（）

- **必读**：`docs/cycle_playbook.md`（v2）—— YIJUN 六阶段（A–F）纯规则研判框架。**阶段判定的唯一真值源是 `docs/t1.py` 的 `detect_stage_raw`（ATR 比率 + 分段 HH/LL + 斜率 + 影线 + 4H>1H>1m 层级），禁 ML**。含多空决策树、真反转 vs 死猫跳对照、宏观归因、策略适配矩阵、错误边界、落地路径、09-08 实跑打脸案例（§11）。
- **v1 的 EMA/MACD/RSI 快照规则已退役**（对箱体品种过拟合，把"箱体反弹"误判"趋势修正"）——禁止再用其套阶段；任何阶段判定直接跑 `python docs/t1.py` 拉真值。
- 当前研判（2026-09-08 09:56 t1.py 直连 fapi 实跑）：**4H=A 震荡均衡（宽箱体 4288–4700）/ 1H=E 冲顶失稳**，默认=中性偏空、只减仓不追；做多只看 1H 放量站上 4514 区（B 突破）。
- 任何"周期定位 / 多空研判 / 阶段卡片 / detect_cycle"类需求，先读 `docs/cycle_playbook.md` 再动手，**`detect_cycle()` 直接移植 `docs/t1.py`，不要另起一套框架**。

---

*本文件由 2026-09-07 的修复 + 开发经验整理。任何架构/红线变动，请同步更新此处。*
