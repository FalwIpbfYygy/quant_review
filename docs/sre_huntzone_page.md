# SRE 考量：狩猎区 K 线叠加页（huntzone）

> 作者：sre-engineer（雷克斯）｜ 范围：在 `D:/quant_review` 新增一页，叠加历史狩猎区档位 + what-if 回测事件到 K 线图（ 1d/1h/1m，Binance fapi，ECharts 渲染）。
> 代码基线：`main.py` `/api/realtime/klines` + `_fapi_fetch`、`huntv2_core.py` `fetch_daily_1d`/`compute_ladder`、`hz_engine.py`、`hz_signal.py` `S_MODEL_FROZEN`。

---

## 0. 数据底座实测（来自 breakeven 报告样本）

为量化量级，解析了 `hunting_zone_breakeven_report.html` 内嵌 payload（`id="payload"` 的 JSON，2.1MB 文件 / 1.95MB JSON）：

| 指标 | 数值 |
|------|------|
| 回测区间 | 2026-01-01 ~ 2026-10-07 |
| 交易日数（纯工作日） | **200 天**（`DAYS=200`）|
| 预计算的保本触发档位 | **19 档**（8~26 点，滑块用）|
| 单触发（origin）事件总数 | **654**，约 **3.3 个/天** |
| 全 19 档矩阵事件总数 | **15,141**（origin+be）|
| 事件类型 | fill / stop / tp1 / tp2 / be_arm / be_out / force22 / force_sl2（报告 CSS class）|
| payload JSON 体积 | **1.95 MB** |
| 单日 1m 柱数（加密 24/7） | **1,440 根/天** |
| 200 天隐含 1m 柱总量 | **288,000 根** |
| Binance 1m 拉取请求数（`limit=1500`） | **≈192 次** |

结论：**全量 1m 数据不可在页面加载时实时拉取**，必须服务端预计算 + 缓存；单日计算极轻（1,440 次迭代），200 天整体也可秒级完成，瓶颈在**网络取数**而非 CPU。

---

## 1. 数据量与延迟

- **1m 柱/天**： 在 Binance fapi 为 24/7 交易，自然日 = 1,440 根 1m 柱（即便页面只渲染工作日，单日仍是 1,440 根）。
- **API 延迟**：
  - `huntv2_core.fetch_daily_1d()` 取 1d 仅需 60 根（`limit=60`）→ 单次 GET，<1s。
  - 1h 数据（如需要）200 天 ≈ 4,800 根 → 4 次 GET。
  - **1m 全量**：288,000 根 ÷ 1500/次 = **192 次 GET**，受 `data_sync.PROXIES` + `timeout=15`（`_fapi_fetch`）。串行 ≈ 2–6 分钟；并行需限流（见 §6）。
- **页面加载时间（目标）**：历史数据全部预计算后，页面只需下载一份 JSON（参考样本 1.95MB）+ 一次性渲染 → 期望首屏 < 2s（受限于浏览器渲染，见 §4）。**禁止在请求链路内做 192 次 fapi 拉取**。
- **实时叠加**：若页面像 `/realtime` 那样轮询 `/api/realtime/klines` 取最新 1m，注意现有代码对实时接口强制 `Cache-Control: no-store` 以避免图表“冻住”——本页实时刷新沿用同一策略。

---

## 2. 缓存策略

**核心原则：预计算每日档位 + 1m 回测结果，按「日期区间 + 构建版本」缓存；历史日不可变、永久缓存，最新进行中日每日收盘后重建。**

- **缓存载体**：
  - 磁盘缓存文件 `.cache/huntzone_<start>_<end>_v<BUILD>.json`，带 `as_of` 水印（最新已收盘日）。
  - 进程内热缓存（仿 `main.py` `_MONTH_CACHE` + `_MONTH_LOCK` + TTL），避免每次请求重算/重读盘。
- **TTL 与失效**：
  - 历史日（close 已定）：**永久有效**，除非 `BUILD` 版本号变化或官方卡修订 → 整表重建。
  - 最新进行中日：每天 UTC+8 收盘（或固定 09:00 切）后触发该日重建；TTL 可设 24h。
  - 档位几何依赖日线收盘 → 日级粒度失效即可，无需分钟级。
- **失效触发**：
  - 数据源新增日线 → 增量重算该日（用日期键定位，不重算全表）。
  - `BUILD` 常量（引擎版本 / `S_MODEL_FROZEN` 修订）变化 → 全表失效重建。
- **命中标识**：返回体带 `source: "cache"|"fapi"`、`built_at`、`as_of`，便于观测与排障。
- **多 worker 注意**：若 uvicorn 多 worker，内存缓存各自独立 → 用**磁盘缓存为真相源**，worker 启动时或缺失时读盘；避免 N 份并发重算。

---

## 3. 失败模式与降级

| 失败 | 表现 | 处理（对齐现有红线） |
|------|------|----------------------|
| fapi 不可达 | `requests.get` 抛异常 / 非 200 | 返回 **502** `{"code":502,"ok":False,"error":"取数失败：…⇒ 不猜 S"}`（仿 `api_huntv2_ladder`）；若有 last-good 缓存则**降级返回缓存 + `stale:true` 警告条**，而非整体 502 |
| 代理（PROXIES）宕 | `requests` 经代理超时/连接失败 | 同上；记录代理名与耗时；可加无代理兜底探测并告警 |
| 缺 1m 数据（某日 Binance 历史缺口） | 该日无法跑 1m 模拟 | 该日返回 `200 + ok:False + reason:"1m 数据不足"`，**其余日照常渲染**，不整页崩溃 |
| 无信号日 | 方向临界 / 趋势过滤 / 波动过滤（见 `hz_engine.trend_direction`/`trend_confirm`/`vol_spike_filter`）| 仿 `compute_ladder`：`200 + ok:False + reason`，图表不画该日 overlay（留空或占位）|
| 构建中（首访缓存缺失） | 后台预计算未就绪 | 返回 **429** `{"code":429,"building":true}`（仿 `/api/sync/db`）+ 状态轮询端点，前端轮询 |
| 参数非法 | 区间/日期格式错 | **400** + 明确 msg（仿 `/api/kline/review`）|

**铁律**：取数失败一律显式报错，**绝不猜 S / 绝不静默用占位档位**（沿用 `/wuyuan`、`/huntv2` 红线）。

---

## 4. 资源占用（CPU / 内存 / 浏览器渲染）

- **服务端计算**：1m 回测 = 单日 1,440 次廉价算术迭代；200 天 ≈ 288k 次 → Python 下单次构建 **1–3s**（不含网络）。内存：288k 柱 + 15k 事件 ≈ 数 MB，远低于风险线。
- **网络取数**：瓶颈在 192 次 fapi GET（见 §1），必须离线/后台、限并发。
- **浏览器渲染（高风险点）**：ECharts 在以下量级会卡死/掉帧：
  - 200 天 × 每/~10 档位 = **最多 ~2,000 条 markLine**；ECharts `markLine` 数量高时性能急剧下降（每条 per-series 绘制）。
  - 15k 事件 `markPoint` 直接铺满 → 可能冻结交互。
  - **缓解（给前端/architect 的硬约束）**：
    1. 狩猎区用 **`markArea`（带状）** 表达，而非 10 条独立 markLine；每日一条 band。
    2. 事件点用**独立 scatter 系列** + `large: true`，配合 `dataZoom` 仅渲染可视窗口；超量时聚合/抽稀。
    3. K 线主序列开 `large: true` / `sampling` / `progressive`；用 **canvas 渲染器**（默认），禁用 SVG。
    4. **分级下钻（LOD）**：全区间默认按日汇总（档位 band + 每日盈亏），点选某日再加载该日 1m 事件明细——避免一次性渲染 288k 柱 + 15k 点。
    5. JSON 解析（~2MB）放在 worker/微任务，避免阻塞首屏。

---

## 5. 可观测性

- **日志（结构化，仿现有 `print("[模块] ...")` 但加维度）**：每条预计算/请求记录 `req_id, range, source(fapi|cache), fapi_latency_ms, bars_fetched, days_computed, events_total, cache_hit, build_ms, error{type,msg}`。
- **指标（建议 `print` 或 `/api/huntzone/metrics`）**：
  - `fapi_request_total` / `fapi_request_latency_ms{p99}` / `fapi_error_total{type}`（含代理失败）。
  - `cache_hit_rate`、`build_total`、`build_duration_ms`、`build_days`、`build_events`。
  - `render_days`、`render_marklines`（前端可上报）。
  - `no_future_function_selftest_pass`（见 §7）。
- **统一错误码**（沿用 `main.py` 的 `{code,msg,data}` schema）：
  - `200` 成功｜`200 + ok:False + reason` 无信号/无数据日（**不**用 204，避免空 body 丢失 reason）｜`400` 参数错｜`429` 构建中/限流｜`500` 内部异常｜`502` fapi 不可达/代理宕（不猜 S）。
  - 错误响应**必须带 `error` 字段与异常类型**（`type(e).__name__`），便于排障，与现有 `/api/xau/plan` 等一致。

---

## 6. 部署与运维风险

- **预计算必须离开请求主链路**：首访全量构建（192 次 GET）会阻塞事件循环/超时。采用：① 离线构建脚本（cron/计划任务）每日收盘后写缓存；② 缺失时 `threading.Thread(...,daemon=True)` 后台构建（仿 `data_sync.run_fetch_all_bg`），返回 429 + 状态轮询。计算部分用 `asyncio.to_thread` 卸载，网络取数用**有界并发**（5–10）避免 Binance IP 权重限（2400/min，klines weight≈1–2）→ 超限返回 418/429 时遵守 `Retry-After`。
- **启动/端口**：现有 `__main__` 用 `_free_port` 对 8000 端口 `taskkill /T /F`——在本机唯一实例 OK，但在共享/容器环境有风险；新端点挂在**同一 uvicorn app**（不新建进程）。部署禁用 `--reload`（本机 uvicorn --reload 会崩），用进程管理器或现有一键启动。
- **页面交付**：仿 `/huntv2`、`/wuyuan` 用**内联 HTML 模板**（`huntzone_template.py`）经 `Response(...)` 返回，避免 `.html` 被同步工具改写；响应头 `no-store` + `nosniff`。
- **内存**：多 worker 时以磁盘缓存为真相源（§2）；2MB JSON 常驻单 worker 内存无害。
- **CORS/代理**：沿用 `CORSMiddleware(allow_origins=["*"])` 与 `data_sync.PROXIES`；新增端点复用 `_fapi_fetch` 单一取数入口，避免代理污染（参考 `huntv2_core` 不 import `hunting_zone/data.py` 的教训）。

---

## 7. 无未来函数（No-Future-Function）保障

回测可信性的底线（报告已声明「信号只用 ≤ 当日 D open，执行按 1m bar 顺序」）。**强制机制**：

1. **决策时间戳封口**：每日 `as_of = D_open_ts`（该日 1m 开盘时刻，UTC）。所有指标只用 `close_time < as_of` 的数据。
2. **档位生成只用历史日线**：日线输入严格取 `close_time < D_open` 的已收盘根（仿 `huntv2_core.compute_ladder` 的 `closed = [r for r in rows if int(r[6]) < now_ms]` + `prev_history = bars[:-1]`）；**禁止**把当日进行中那根（`today`）放进趋势/回归输入。
3. **S 来源封冻**：`hz_signal.predict_S(S_MODEL_FROZEN, prev_bar)` 只用**昨日** `prev_bar`（bars[-2]），`S_MODEL_FROZEN` 为冻结常数，**运行/构建期不读取任何官方卡、不重拟合**（已工程化剥离 `hunting_zone/data.py`）。
4. **1m 模拟单遍前向**：按 `open_time` 升序遍历当日 1m 柱，**仅用当前及过去柱**做入场/出场判定，永不窥探未来价；时间窗锁定 `[D_open, D_close)`。
5. **不变式自检（建议加单测）**：对每个样本日，将 `as_of` 后移 +1 天重算，断言**当日 D 的档位结果不变**（证明无泄漏）；任何变更触发 CI 失败。
6. **数据窗口可审计**：每条日记录附 `data_window{start_ts, end_ts, used_daily_bars, used_1m_bars}`，日志留存；并加断言 `max(used_bar.open_time) < D_close` 与 `max(daily.close_time) < D_open`。
7. **拒绝越界数据**：任何 `open_time >= as_of` 的柱不得进入指标计算；任何 `close_time >= D_open` 的日线不得进入档位生成。

---

## 附：给前端的硬性约束清单（致 architect）

1. 全量 1m **不实时拉取**：页面只读服务端预计算缓存 JSON（含档位 band + 事件点）。
2. 档位用 `markArea` 带状，事件用 `large` scatter + `dataZoom`，K 线开 `large/sampling/progressive`，canvas 渲染。
3. 分级下钻：全区间按日汇总，点选单日再拉该日 1m 明细。
4. 无信号/缺数据日**留空不报错**；取数失败显示 stale 警告条而非白屏。
5. 实时刷新沿用 `no-store`，避免轮询被浏览器缓存冻图。
6. 错误码消费 `200/400/429/500/502`，解析 `ok`/`reason`/`error` 字段。

## 附：给测试（致 testing-expert）

- 无未来函数不变式测试（§7.5）列为 P0 验收。
- 失败模式冒烟：fapi 超时→502、缺 1m→该日空、无信号日→`ok:False`、缓存缺失→429+轮询。
- 渲染压测：200 天 × 全事件下 FPS / 内存不爆（§4）。

---

## 补充（v2）：本地 DB 优先数据源下的缓存与监控方案

> 前提变更（architect 锁定）：历史 **1m 数据源 = 本地 `kline_1m` DB 优先，缺失/缺口回退 live fapi**（`limit≤1500`）。以下基于对该 DB 的实测（read-only 查询）给出缓存与监控方案，并回答 §11 的覆盖/缺日问题。

### A. 数据层实测事实（已验证）

| 项 | 实测 |
|----|------|
| `kline_1m` 内容 | **PAXGUSDT** 经 `data_sync` 入库，`PRICE_OFFSET=12` → 已是 XAU 量纲（样本价 ~4154，≈ ）|
| 覆盖区间 | **2026-01-01 00:00 UTC → 2026-10-08 09:47 UTC** |
| 天数 | **281 个自然日，0 缺口**（span 281 = distinct 281）|
| 日均柱数 | **1437 根/天**（加密 24/7，≈1440）|
| NULL 价格行 | **0**（`query_kline` 本身 `IS NOT NULL` 过滤）|
| 唯一“短日” | 2026-10-08 = 588 根 → **进行中当日**（sync 截至 09:47），非缺陷 |
| 存在的表 | 仅 `kline_1m/5m/15m/30m`；**无 `kline_1d` / `kline_1h`** |
| `query_kline` 上限 | `MAX_ROWS=10000` → **多日区间查询会被截断（约 7 天）**，须按日查 |

**结论**：对狩猎区区间（2026-01-01~2026-10-07），本地 1m **完整覆盖、无缺口**。因此“DB 优先”在历史区间命中率≈100%；回退 fapi 仅用于进行中当日或未来日。

### B. 缓存方案（粒度 / TTL / 失效 / 退避 / 预计算）

**两层缓存：**
- **L0 原始 1m 柱**（可选）：key=`(symbol,date)`，来自 DB；本地库快，TTL 5min 仅作查询阻尼。
- **L1 计算结果**：key=`(date, trigger, symbol)`（即 architect 指定的三元组），value=该日 sim 的 events+zones+realized。这是主缓存。

**粒度 = 按日（非按区间）**：因 `MAX_ROWS` 截断多日查询，且按日增量重建更干净；区间 = 各日缓存并集。

**TTL：**
- 历史（已收盘）日 L1：`∞`（数据不可变），仅随 `BUILD` 版本号翻转失效。
- 进行中当日：短 TTL（如 60s）或每次 live tick 重算；**绝不**对当日跑历史回测。
- L0 原始柱：5min。

**失效：**
- `BUILD` 常量变更 → 清空全部 L1。
- 新日出现（date > 已缓存最大日）→ 按需计算并缓存。
- **陈旧守卫**：历史日缓存写入时存 `bars_n`（当日柱数）；读取时若 `SELECT COUNT(*)` 与该日 `bars_n` 不符 → 重算（防 sync 回填后 stale）。

**退避（fapi 回退 / DB）：**
- fapi 回退（DB 缺某日）：单日 ≤1500 根 = 1 次 GET；**有界指数退避**（仿 `data_sync` `MAX_RETRIES=5`、`RETRY_DELAY=2`+jitter），遵守 Binance `418/429` 的 `Retry-After`。
- DB 连接：`PooledDB(blocking=True)` 已有；建议 `db.py` 连接加 `connect_timeout=5`，DB 宕时**快速失败**转 fapi，不挂起。
- **单飞（singleflight）**：冷启动多日同时缺失时，按 date 加锁，并发请求共享同一次构建；构建并发上限 ~8。

**预计算是否必要：**
- **基线 = 按需按日计算 + 缓存**（首次访问某日触发，之后秒回）。200 天×19 档 = 3800 次 (date,trigger) 计算，每次 ~1440 迭代，**CPU 可忽略**。
- **可选离线预计算**：每日 sync 后 cron 跑全区间写缓存，使首次页面加载即时。⚠️ **不得放在请求主链路**（仍可能触发少次 fapi 回退），缺失时返回 429+轮询（沿用 §3）。

### C. 监控项（含新增“本地 DB 命中率”）

- `db_hit_rate` = 历史日 sim 命中 DB / 总数（目标≈100% 历史区间；掉点=同步缺口）。
- `fapi_fallback_total{reason=missing|incomplete}`（历史区间应≈0，突增=告警）。
- `db_query_latency_ms{p50,p99}`（本地应 <20ms）。
- `db_coverage_days` / `db_gap_days`（`<1300` 柱的日数；历史日现=0）。
- `null_price_rows`（应=0）。
- `cache_hit_rate`(L1) / `cache_miss_compute_ms`(单日构建耗时)。
- 保留：fapi_request_latency/error、`build_duration_ms`、`no_future_function_selftest_pass`。
- 响应体按日标 `source:"db"|"fapi_fallback"|"live_only"`，便于排障与§11核对。

### D. §11 答复：覆盖与缺日标记

- **是否覆盖 2026 全年 1m**：对狩猎区区间 **是，完整连续、0 缺口**（281/281 天，~1437 柱/天）。仅 2026-10-08（进行中当日）为部分数据，属预期。
- **缺日如何标 `missing`**：
  - 定义：`SELECT COUNT(*) FROM kline_1m WHERE DATE(FROM_UNIXTIME(open_time/1000))=?` → `=0` 为 missing，`<1300` 为 incomplete（注意 `open_time` 是 **epoch-ms BIGINT**，须 `FROM_UNIXTIME(open_time/1000)`，直接 `DATE(open_time)` 会得到错误年份）。
  - 缓存日状态：`ok | incomplete | missing | fapi_fallback | live_only`。
  - 历史 missing → **按日回退 fapi**（1 GET≤1500）并标 `fapi_fallback`；incomplete/进行中当日 → 不跑历史 sim，标 `live_only`。
  - 建议加定时 `db_coverage_check`：列出缺口日并告警，使同步问题在用户看到空白前被发现。

### E. 须写入 PRD 的两条澄清（致 tech-writer / architect）

1. **“DB 优先”仅适用于 1m**。`kline_1d`、`kline_1h` 表不存在 → 档位生成所需的 **1d 仍走 fapi**（`huntv2_core.fetch_daily_1d` 已是 fapi）；1h 同理。若未来要把 1d 也本地化，需新增 `kline_1d` 同步任务。
2. **价格量纲**：本地 1m 是 PAXG+12（已 XAU 量纲），与  fapi 残余基差在 bps 级；因档位为“当日 open 起的比例/价差”，常数偏移对回测无影响，但叠加层须确保 1m 序列与档位序列**同一价格基准**（建议直接用 DB 1m 作 XAU 量纲，或在 PRD 标注 ±12pt/基差容差）。
3. **日切分对齐**：按日取 1m 的窗口必须与档位生成的“日”边界一致（`daily_plan` 用 BJ 08:00=UTC 00:00 切分）；DB `open_time` 为 UTC，若页面用 BJ 日须窗口 +8h，否则当日 1m 与当日档位错位。
