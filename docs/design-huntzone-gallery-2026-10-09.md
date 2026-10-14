# 设计草案：狩猎区画廊 `/huntzone-gallery`（滑动切换多交易日案例）

> 作者：architect-2 ｜ 类型：设计草案（ADR 风格）｜ 日期：2026-10-09
> 范围：在 `D:/quant_review` **新增**一页，通过滑动/轮播切换多个「狩猎区（Hunting Zone）交易日」案例。
> 状态：**Proposed（仅设计，未改任何代码）** ｜ 约束：不修改既有代码，仅新增。

---

## 0. 一句话结论

复用已验证的 `huntback_sim.py`（M1，11/11 单测通过）作为**唯一计算内核**，新增一个**多交易日滑动画廊**：每个 slide 是一天的狩猎区回放（1h 聚合 K 线 + 斐波那契阶梯/zone 色带 + 事件标记 + 当日 P&L + 方向），滑动/轮播在多个独立交易日间切换，复刻用户 MT4 截图里「连续多日 hunting zone ladder」的观感。画廊**只展示**已算好的结果，**不引入任何新计算**，因此天然继承 `huntback_sim` 的「零未来函数」属性。

---

## 1. 定位与边界（避免与既有设计重复）

| 页面 | 职责 | 本设计的关系 |
|------|------|------|
| `/huntv2` | 单日 ladder 档位图（档位表 + 距离） | 画廊复用其 `build` 几何 + 档位角色映射（`huntv2_core._ROLE`） |
| `/huntback`（architect 任务 #1，见 `huntback_mockup.html`） | **单日 1m 下钻 + 阶梯 overlay** | 本画廊是**多日轮播**；画廊的「看 1m 细部」可复用 `/huntback` 的单日渲染思路，甚至通过 `/huntback?date=YYYY-MM-DD` 跳转，二者共享同一 sim 数据源，**不重复造轮子** |
| **`/huntzone-gallery`（本设计）** | **多交易日滑动画廊**（一天 = 一屏） | 互补视图，新增 |

> 关键区分：architect 的 `/huntback` 是「**钻进某一天看 1m**」；本画廊是「**在多天之间滑来滑去**」。两者数据源完全一致（都是 `huntback_sim` 的 per-day 输出），前端裁剪不同（一屏 vs 多屏）。

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│  浏览器：/huntzone-gallery  (huntzone_gallery_template.py 内联 HTML)   │
│                                                                       │
│  ┌─ header ──────────────────────────────────────────────────────┐   │
│  │ 日期范围选择器 │ be/origin 切换 │ trigger 滑块(8~26) │ 统计条    │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─ 横向 scroll-snap 容器 ───────────────────────────────────────┐   │
│  │  [slide 日1] [slide 日2] [slide 日3] ... [slide 日N]          │   │
│  │   每屏 = 1 天：ECharts 蜡烛 + 阶梯/zone 色带 + 事件 + P&L 面板  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌─ footer ──────────────────────────────────────────────────────┐   │
│  │  ◀ 上一日 │ ●●● 指示点/日历 │ 下一日 ▶  │ 「看 1m 细部」开关    │   │
│  └───────────────────────────────────────────────────────────────┘   │
│         │  fetch(range, trigger)            │  fetch(date, 1m) 按需    │
│         ▼                                ▼                          │
└─────────┼────────────────────────────────┼───────────────────────────┘
          │                                │
   GET /api/huntzone-gallery/slides   GET /api/huntzone-gallery/day
   ?start&end&trigger&symbol          ?date&trigger&symbol&granularity=1m
          │                                │
          ▼                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  huntzone_gallery_core.py（新增·薄编排层，不改 huntback_sim）           │
│   ① huntv2_core.fetch_daily_1d()        → 取 1d 日线（一次/请求）     │
│   ② huntback_sim.compute_day_levels(d)   → 每日起跑档位 lad           │
│   ③ huntback_sim.fetch_day_1m(d)         → 每日 1m 柱（DB 优先/回退） │
│   ④ huntback_sim.simulate_day(lad,bars,T)→ 事件+三区 P&L（@触发 T）  │
│   ⑤ _agg_1h(bars)                        → 1m→1h 聚合（画廊默认）     │
│   ⑥ L1 缓存：(date,trigger,symbol) → sim 结果（仿 SRE §B）          │
└──────────────────────────────────────────────────────────────────────┘
          │ 复用  │
          ▼      ▼
   hz_engine.build / hz_signal.S_MODEL_FROZEN / db.query_kline / binance_src
```

**数据流要点**：页面首屏只对后端发 **1 次**范围请求拿到「所有天的 1h 聚合 K 线 + 阶梯 + 事件 + P&L」；1m 仅在用户点「看 1m 细部」时**按需单日**拉取（命中同一条 L1 缓存）。无实时轮询（画廊是历史复盘，非实时页）。

---

## 3. 数据源复用映射（明确澄清）

### ⚠ 重要澄清：`huntback_core.py` 当前不存在
任务描述提到复用 `huntback_core.py`，但仓库中**没有该文件**（已 `ls`/`grep` 核实）。真实可用的计算内核只有：
- **`huntback_sim.py`** — M1 已验证引擎（`simulate_day` / `simulate_triggers` / `compute_day_levels` / `fetch_day_1m` / `Event` / `ZoneResult`）。
- **`huntv2_core.py`** — ladder 编排（`fetch_daily_1d` / `compute_ladder` / `_ROLE` 档位角色映射 / `build_response`）。

本设计**只 import、不修改**上述模块。新增的编排逻辑放在新文件 `huntzone_gallery_core.py`，符合「只新增、不动既有」红线。

### 逐字段映射（slide 数据 ← sim 内核）

| 画廊字段 | 来源函数 | 说明 |
|----------|----------|------|
| 日期 / 方向 / direction_cn | `compute_day_levels`→`lad` | 与 `/huntv2` 同口径 |
| 阶梯档位（zone_lo/hi/mid, stop, exh1/exh2, t1, open_px, S, R, prev_close, levels[]） | `compute_day_levels`→`lad`（`build()` 输出） | 直接复用 `huntv2_core._ROLE` 的 ratio→角色标注 |
| 1m 柱（下钻用） | `fetch_day_1m(date)` → `(bars, source, missing)` | DB 优先，缺口回退 fapi |
| 1h 聚合 K 线（画廊默认） | `_agg_1h(bars)`（新·纯函数） | 由 1m 柱按 UTC 小时聚合，无前视 |
| 事件序列（fill/stop/tp1/tp2/be_arm/be_out/force22/force_sl2） | `simulate_day(lad, bars, T)` → `events_all`（**@当前 trigger T**） | 注意：`events_all` 即 be 档在触发 T 的事件，be_arm/be_out 随 T 变化 |
| 三区 P&L（zone_a/mid/b） | `simulate_day` → `be[str(T)].zones` / `origin.zones` | be/origin 切换两档 |
| 单日合计 / outcome | `be[str(T)].realized_usd` / `origin.realized_usd` / `outcome` | K=1（1 点=$1） |
| 当日状态 | `missing` / `compute_ladder` 无信号判定 | `ok` / `missing` / `incomplete` / `no_signal` / `live_only`（状态机见 SRE §D） |

---

## 4. API 接口设计

### 4.1 `GET /api/huntzone-gallery/slides`（加载整段画廊）

```
query:
  start=YYYY-MM-DD   # 区间起点（含）
  end=YYYY-MM-DD     # 区间终点（含）；缺省=最新已收盘日
  trigger=int(8~26)  # 保本触发，缺省 20
  symbol=str         # 缺省 
响应 200:
{
  "code":200, "ok":true,
  "builds_at":"2026-10-09T09:00:00Z", "as_of":"2026-10-08",
  "source":"cache|db|fapi",          // 观测用，仿 SRE §5
  "trigger":20, "symbol":"",
  "range":{ "start":"2026-08-10", "end":"2026-10-08", "days":60 },
  "summary":{ "win":38, "loss":16, "flat":6, "total_usd": <Σ>, "best_day":"...", "worst_day":"..." },
  "days":[
    {
      "date":"2026-09-02",
      "direction":"short", "direction_cn":"空",
      "status":"ok",                      // ok|no_signal|missing|incomplete|live_only
      "ladder":{ "open_px":2000.0, "S":100.0, "R":..., "zone_lo":2038.2, "zone_hi":2061.8,
                 "zone_mid":2050.0, "stop":2080.9, "exh1":1938.2, "exh2":..., "t1":1980.0,
                 "prev_close":1980.0, "direction_cn":"空",
                 "levels":[ {"ratio":0.0,"name":"腿端/中枢","price":...,"role":"..."}, ... ] },
      "kline_1h":[ {"t":<ts_ms>,"o":..,"h":..,"l":..,"c":..,"v":..}, ... ],  // 24 根/日
      "events":[ {"tag":"zone_a","type":"fill","time":"08:06","ts_ms":..,"price":2061.8,"note":"..."}, ... ],
      "pnl":{ "be":   {"zone_a":102.7,"zone_mid":90.9,"zone_b":79.1,"total_usd":272.7,"outcome":"盈利"},
              "origin":{"zone_a":..,"zone_mid":..,"zone_b":..,"total_usd":..,"outcome":"..."} }
    }, ...
  ]
}
```

**错误码（沿用 SRE §5 / 现有 `{code,msg,data}` schema）**：
- `200 + ok:False + reason`：某日无信号/缺 1m（**逐日**标 `status`，不整页崩）
- `400`：日期格式/区间非法
- `429 + {"building":true}`：冷启动区间未构建完（仿 `/api/sync/db`），前端轮询
- `502 + {"error":"取数失败：…⇒ 不猜 S"}`：fapi/代理不可达（若有 last-good 缓存则降级 `stale:true` 警告条）

> 体量估算：1h 默认 = 24 根/日 × 6 数 ≈ 144 数/日；60 天 ≈ 8.6k 数 + 元数据 ≈ **<200KB**；即便 200 天 ≈ **<600KB**，远低于 SRE §0 的 1.95MB 上限。安全。

### 4.2 `GET /api/huntzone-gallery/day`（按需单日 1m 下钻）

```
query: date, trigger(8~26, 缺省20), symbol, granularity=1m
响应 200:
{ "code":200,"ok":true,"date":...,"trigger":20,
  "kline_1m":[ {"t","o","h","l","c","v"}, ... ],   // ~1440 根 ≈ 50~80KB
  "events":[ ... 同 4.1 ],                          // @trigger
  "pnl":{ "be":{...}, "origin":{...} } }
```
命中 SRE §B 的 L1 缓存 `(date,trigger,symbol)`，与 `slides` endpoint 共享同一缓存键，**零重复计算**。

---

## 5. 文件拆分（推荐方案）

> 任务要求「单文件 Python 或清晰说明路由/模板/核心拆分」。本设计采用**拆分**（与既有 `huntv2_core.py`+`huntv2_template.py` 同构），理由：画廊逻辑（range 编排 + 聚合 + 缓存）与页面渲染职责不同，拆开可单测、可复用、且不污染 `main.py`。

| 文件 | 作用 | 是否新增 |
|------|------|---------|
| `huntzone_gallery_template.py` | 页面 HTML 内联常量（Vue3 Options API 外壳 + ECharts 渲染 + scroll-snap + 控件）；仿 `huntv2_template.py` 风格 | **新增** |
| `huntzone_gallery_core.py` | 后端编排：range 取数、per-day sim、1m→1h 聚合、L1 缓存、`slides`/`day` 数据组装；**只 import huntback_sim / huntv2_core / db** | **新增** |
| `main.py` | 新增 2 条路由：`@app.get("/huntzone-gallery")` + `@app.get("/api/huntzone-gallery/slides"|"/day")`；返回 `no-store` 反缓存头 | **新增路由（不改动既有）** |
| `static/components/topnav.js` | 在 `NAV` 数组追加一项（唯一权威源）：`{ path:'/huntzone-gallery', label:'狩猎区画廊', icon:'<svg.../>' }` | **新增 1 行** |
| `huntback_sim.py` / `huntv2_core.py` / `hz_engine.py` / `hz_signal.py` / `db.py` | 计算内核 + 数据源 | **不改** |

> 若坚持「单文件」：可把 `_core` 逻辑内联进 `main.py` 路由、模板内联进 `huntzone_gallery_template.py`。但这样 `main.py` 会变胖、且失去单测入口，**不推荐**。拆分是项目已确立的惯例。

---

## 6. 滑动交互方案对比（任务要求 #4）

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **CSS `scroll-snap`（横向）** | 零依赖、原生触摸/滚轮/键盘、GPU 合成稳；`IntersectionObserver` 易接懒渲染；契合项目「无构建、只 vendored 库」哲学；移动端天然支持 | 过渡偏生硬（加 `scroll-behavior:smooth` 缓解）；按钮/指示点/索引需少量手写 JS | ✅ **主方案** |
| **JS Swiper 库** | 手势丰富、pagination/keyboard/lazy/parallax 内置、最像 MT4 丝滑 | 需在 `vendors/` 新增 `swiper.min.js`+css（新增依赖，违最小依赖）；体积+维护；与 ECharts 实例生命周期需协调 | ⏸ 二期可选增强 |
| **左/右按钮 + `translateX`** | 实现极小、完全可控 | 无触摸滑动（移动端差）、无滚轮、索引/按钮状态全手写、易与 ECharts 横向 dataZoom 拖拽冲突 | ❌ 仅作兜底 |

**推荐组合**：以 **CSS scroll-snap（横向 `x mandatory`）** 为主，配 **极简 vanilla JS**：
- `◀/▶` 按钮 → `container.scrollBy({left: ±slideWidth, behavior:'smooth'})`
- 指示点/日历 → 点按 `scrollTo` 到对应 slide；`IntersectionObserver` 回写当前 index 高亮
- `IntersectionObserver` 触发**懒渲染**：slide 进入可视（含 ±1 缓冲）才 `echarts.init`；移出远区 `dispose()` 释放实例（性能约束见 §8）

**⚠ 滚动方向冲突约束（必读）**：画廊是**横向**滑动导航，而 ECharts 默认 `dataZoom` 可横向拖拽 → 二者抢手势。约束：画廊 slide 内 **禁用横向 dataZoom**（或仅保留纵向 inside zoom）；图表内部缩放一律走按钮/滚轮（纵向），横向手势专属于「切天」。在 ECharts `option` 中明确 `dataZoom: [{type:'inside', orient:'vertical'}]` 或干脆不挂 dataZoom。

---

## 7. 每个 slide 展示内容（任务要求 #5）

一屏 = 一天，自上而下：

1. **头部条**：日期 `YYYY-MM-DD` ｜ 方向徽章（空/多，红/绿按中国习惯 `var(--up)` 红涨）｜ 状态（ok/no_signal/missing）｜ 当前 trigger 值 `20 点` ｜ be/origin 切换态。
2. **K 线主图（ECharts candlestick）**：
   - 默认 **1h 聚合** 柱（24 根/日），复刻 MT4 H1 观感；红涨绿跌（`itemStyle` color/color0）。
   - x=时间，y=价格；右侧价格轴标注档位价。
3. **斐波那契阶梯 + zone 色带（overlay）**：
   - **zone 色带**：用 `markArea`（带状，**非** N 条 markLine，满足 SRE §4.2）画狩猎区 `[zone_b, zone_a]`（即 38.2~61.8）填充；按用户截图加**第二条扩展带**（如 100~161.8 衰竭区）填**粉色**，主区填**绿色**——还原「绿色/粉色 zone 色带」。
   - **档位线（markLine，少量关键线）**：day open(100%)、stop(19.1)、zone_a(38.2)、zone_mid(50)、zone_b(61.8)、exh1(161.8)、t1(昨收/TP1)；文字标 `名称+价`。
   - **方向箭头**：在 zone 区加 `graphic` 箭头注解（↑多 / ↓空），对应截图「方向箭头」。
4. **事件标记（scatter / markPoint，color-coded）**：fill（金）· tp1（青）· tp2（浅青）· stop（红）· be_arm/be_out（紫）· force22（黄）· force_sl2（橙）；点旁注 `type`。
5. **当日 P&L 面板**（仿 `huntback_mockup.html` 的 `.pnlbox`）：zone_a / zone_mid / zone_b 三区 USD（随 be/origin 切换）+ 单日合计 + outcome（盈利红/亏损绿/持平灰）。
6. **事件时间线（列表，无障碍/非图表用户）**：`HH:MM BJ` ｜ 类型 ｜ 价 ｜ note；与图表事件同源。
7. **「看 1m 细部」开关**（每屏，按需）：激活后对该日懒调 `/api/huntzone-gallery/day?granularity=1m`，用 1m 重绘该屏（命中缓存，复用 `/huntback` 的单日渲染口径）。

---

## 8. 前端渲染与性能约束（采纳 SRE §4/§B）

1. **懒渲染 + 生命周期**：`IntersectionObserver` 仅在 slide 进入视口（±1 缓冲）时 `echarts.init`；远离视口 `dispose()`。任意时刻活跃 ECharts 实例 **≤3**，与 slide 总数 N 无关 → 200 天画廊也不爆内存。
2. **默认粒度 1h**：首屏 JSON 小（§4.1 估算 <600KB/200天）；1m 仅按需单日拉取。
3. **渲染器与采样**：`renderer:'canvas'`（禁用 SVG）、K 线 `large:true` + `sampling` + `progressive`；zone 用 `markArea` 带状；事件用 scatter `large:true`。
4. **DOM 策略**：所有 slide 的 `<section>` 常驻 DOM（空 mount，便宜）；仅图表实例懒建/销毁。N≤~60 无需虚拟化；若开放 200 天全量，建议仅渲染 `active±1` 的 DOM 节点（真正虚拟滚动），作为二期优化。
5. **单 API 加载**：区间一次请求拿全量 1h；无逐屏 fetch（除 1m 按需）。
6. **缓存**：服务端 `(date,trigger,symbol)` L1 缓存（SRE §B）；历史日持久、随 `BUILD` 翻转失效；进行中当日短 TTL。
7. **反缓存头**：页面与 API 均带 `no-store, no-cache`（仿 `/huntv2` 路由），防 304 白屏。

---

## 9. 风险（任务要求 #7）

### 9.1 未来函数（Future Function）
- **画廊本身不计算**，只展示 `huntback_sim` 已算结果 → 天然继承其严格因果（仅用 ≤D-open 已收盘日线、1m 升序前向、不窥探未来）。无未来函数**来源于内核，不在本页**。
- **唯一新增风险点 = 进行中当日（live_only）**：若画廊包含「今天」这种未收盘日，1m 为部分数据，必须 **复用 `force_close` 的 22:30 北京时（=UTC 14:30）封口**（见 `huntback_sim._FORCE_CLOSE_OFFSET_MS`），**绝不对全天做后视**。默认 `end` 取「最新已收盘日」即可规避；若开放进行中当日，明确标 `live_only` 且仅渲染截至当前、不出场判定不前瞻。
- **1h 聚合无前视**：`_agg_1h` 每根小时柱只用自身 OHLC，`[D_open,D_close)` 窗内，安全。
- **自检建议**（对齐 SRE §7.5 / testing P0）：单测断言「将 `as_of` 后移 +1 天重算，当日档位结果不变」，CI 卡死。

### 9.2 数据缺失（Data Missing）
- **逐日状态机**（SRE §D）：`ok | incomplete | missing | fapi_fallback | live_only`。缺失日 slide 显示**占位卡**（不画图表）+ `reason`，**不拖垮整列轮播**。
- **价格量纲**：本地 1m 为 PAXG+12（已 XAU 量纲），与  残余基差在 bps 级；因档位为「当日 open 起的比例/价差」，常数偏移对回测无影响，但**叠加层须确保 1m 与 lad 同一价格基准**（直接用 DB 1m 作 XAU 量纲，或 PRD 标注 ±12pt 容差）。
- **日边界对齐**：按 UTC 自然日切分（与 `huntback_sim` 窗 `[D_open, D_close)` 一致）；若前端用 BJ 日须窗口 +8h，否则当日 1m 与档位错位。
- **缺 1d/1h 表**：`kline_1d`/`kline_1h` 不存在（SRE §E），档位生成所需 1d **仍走 fapi**（`huntv2_core.fetch_daily_1d` 已如此）；勿误以为本地有 1d。

### 9.3 性能（Performance）
- **N 屏 ECharts**：靠 §8.1 懒渲染 + ≤3 实例上限根治；200 天也不爆。
- **首屏 JSON**：1h 默认体量安全（§4.1）；**切忌**画廊默认下发 1m 全量（SRE §0：288k 柱/200天不可实时拉）。
- **网络取数在请求外**：range 冷启动的 1d/1m 取数走后台构建（429+轮询），不阻塞首屏；有界并发 5~10 避 Binance 限流。
- **ECharts 绘制量**：zone 用 markArea（非多 markLine）、事件用 large scatter+dataZoom 仅可视区、K 线开 large/sampling——直接采纳 SRE §4 硬约束。

---

## 10. ADR 记录

### ADR-G1：页面命名与路由
- **决策**：路由 `/huntzone-gallery`，导航标签「狩猎区画廊」。
- **理由**：用户建议名清晰且与 `/huntv2`、`/huntback` 同族；不与既有路由冲突。
- **影响**：仅需在 `topnav.js` 的 `NAV` 加 1 项；页面 `<topnav-bar data-active="/huntzone-gallery">`。

### ADR-G2：滑动交互主方案
- **决策**：CSS `scroll-snap`（横向 x mandatory）+ 极简 JS（按钮/指示点/IO 懒渲染）。
- **理由**：零依赖、原生手势、易接懒渲染、契合 vendored-only 哲学；Swiper 留作二期。
- **影响**：禁图表内横向 dataZoom（§6 冲突约束）；需少量 JS 维护 index 高亮。

### ADR-G3：默认粒度 = 1h 聚合
- **决策**：画廊默认渲染 1h 聚合 K 线；1m 仅「看细部」按需单日拉取。
- **理由**：复刻 MT4 H1 多日观感；首屏 JSON 小；性能安全（§4.1/§9.3）。
- **影响**：新增纯函数 `_agg_1m_to_1h`（无前视）；`day` endpoint 复用同一 L1 缓存提供 1m。

### ADR-G4：缓存与数据源
- **决策**：服务端 L1 缓存键 `(date, trigger, symbol)`；1d 走 fapi、1m 走 DB 优先回退 fapi（沿用 SRE §B/§E）。
- **理由**：单日计算极轻、CPU 可忽略；瓶颈在网络，缓存解耦；历史日持久。
- **影响**：新增 `huntzone_gallery_core.py` 承载缓存与编排；不动 `huntback_sim.py`。

### ADR-G5：模块拆分（非单文件）
- **决策**：`huntzone_gallery_template.py`（页面）+ `huntzone_gallery_core.py`（编排）+ `main.py` 加路由。
- **理由**：与 `huntv2_core`/`huntv2_template` 同构，可单测、可复用、不胖 `main.py`。
- **影响**：新增 2 文件 + `main.py` 2 路由 + `topnav.js` 1 行；既有文件零改动。

---

## 11. 与验收（testing-expert）对齐的要点
- 每个 slide 的 `status` 必须正确处理 `missing/no_signal/incomplete`，缺失日不崩整列（§9.2）。
- 无未来函数不变式（§9.1）列为 P0。
- 渲染压测：200 天画廊 FPS/内存不爆，活跃 ECharts 实例 ≤3（§8）。
- 错误码消费：`200/400/429/502`，解析 `ok/reason/error`（SRE §5）。

---

## 12. 实施清单（新增 / 不改动）

**新增**：
- [ ] `docs/design-huntzone-gallery-2026-10-09.md`（本文件）
- [ ] `huntzone_gallery_template.py`（页面 + ECharts + scroll-snap + 控件 + 懒渲染 IO）
- [ ] `huntzone_gallery_core.py`（`slides`/`day` 组装、`_agg_1m_to_1h`、L1 缓存、502/429/400）
- [ ] `main.py`：`@app.get("/huntzone-gallery")` + `/api/huntzone-gallery/slides` + `/api/huntzone-gallery/day`（含 `no-store` 头）
- [ ] `static/components/topnav.js`：`NAV` 追加 `/huntzone-gallery`

**不改动（只 import）**：
- [ ] `huntback_sim.py`、`huntv2_core.py`、`hz_engine.py`、`hz_signal.py`、`db.py`、`binance_src.py`
- [ ] 既有 `/huntv2`、`/huntback`（architect 任务）、`/wuyuan` 等所有页面与路由

> 注：`huntback_core.py` 在任务描述中被引用，但仓库中不存在；本设计明确以 `huntback_sim.py` + `huntv2_core.py` 为数据源，并新增 `huntzone_gallery_core.py` 作编排层，不依赖任何不存在的模块。
