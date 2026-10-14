# 狩猎区场景轮播/滑动页 · PRD（评审稿）

> 项目：`D:\quant_review`
> 关联页面：现有 `/huntback` 效果图（`huntback_mockup.html`，设计稿，尚未接入路由）；本 PRD 新增一页「狩猎区场景轮播/滑动页」
> 版本：v0.1（评审稿，待用户审核签字后进入开发）
> 状态：**待开发（本文档为需求基线）**
> 约束摘要：纯**新增**，保留现有 `/huntback`；数据全部复用已验证的 `huntback_sim.py`（M1 what-if 引擎）；严格因果、零未来函数；单文件 Python 实现；不修改既有功能与引擎逻辑

---

## 0. 一句话版本目标（TL;DR）

新增一个**滑动/轮播页**：在保留现有 `/huntback` 效果图的前提下，让用户通过**左右滑动**逐日浏览多个「狩猎区交易日案例」——每张卡片 = 单日 1h K 线（聚合自 1m，对齐 MT4 H1）+ 狩猎区阶梯 overlay（MT4 比例 0.0/19.1/38.2/50/61.8/100/161.8/261.8/423.6）+ 方向箭头 + 事件标记 + 触发器（be/origin、trigger 8–26）展示，所有数字**可溯源到 `huntback_sim.py` 回放输出、无未来函数**。

---

## 1. 背景与目标

用户已有一个 `/huntback` 效果图页面（`huntback_mockup.html`），展示了单日的「1h K 线（聚合自 1m）+ 狩猎区阶梯叠加 + 三区 P&L + 事件时间线」，视觉灵感来自 **MT4 截图： H1 上连续多日的 hunting zone ladder**（0.0/19.1/38.2/50/61.8/100.0/161.8/261.8/423.6 档位色带、方向箭头）。

现状痛点：现有效果图**只展示单日一个样例**（写死的合成数据），无法横扫「连续多日」的狩猎区形态——而这正是 MT4 截图的精髓（多日 ladder 对比）。

**目标**：把单日卡片**轮播化**——新增一个滑动页，复用已验证的 `huntback_sim.py` 每日模拟输出（三区独立持仓、零未来函数），让用户在多个真实交易日案例之间流畅滑动切换，并可挑选/筛选要纳入轮播的日子集。

**与既有 `/huntback` 的关系**：本期**保留并继承**其视觉语言（深色主题、gold/cyan/red 配色、阶梯线/zone 色带/事件标记样式），但本页是独立新页，不改动 `huntback_mockup.html` 的既有内容。两页共享同一数据底座（`huntback_sim.py`）。

---

## 2. 现状审计（代码级溯源）

| 项 | 位置 | 当前实现 / 事实 |
|----|------|----------------|
| 现有 `/huntback` 页 | `huntback_mockup.html`（L1–286） | **纯设计稿（inline SVG + 合成数据）**，未接路由；`main.py` 中**无 `huntback` 路由**（已 grep 确认） |
| 回测内核 | `huntback_sim.py` | M1 what-if 保本引擎，docstring 明确声明「严格因果、零未来函数」（L1–12） |
| 单日三区模拟 | `huntback_sim.py` `simulate_day` L252–267 | 返回 `date / direction / missing / origin / be{trigger} / outcome / events_all / origin_events` |
| 多 trigger 模拟 | `huntback_sim.py` `simulate_triggers` L270–288 | 循环 trigger∈[8..26]，返回 `be{8..26}`，数据与 `simulate_day` 同源 |
| 取数薄封装 | `huntback_sim.py` `compute_day_levels` L294–327 / `fetch_day_1m` L330–360 | 档位（日线，≤D-open 已收盘）+ 1m 柱（本地 DB 优先 / fapi 兜底） |
| 事件结构 | `huntback_sim.py` `Event` L55–62 | 字段：`tag, type, time(HH:MM BJ), ts_ms(UTC ms, 图表 x 轴), price, note` |
| 事件类型 | `_run` L111–188 | `fill / stop / tp1 / tp2 / be_arm / be_out / force22 / force_sl2` 共 8 类 |
| 档位生成 | `hz_engine.build` L74–124 | 产出 `lad` dict，含 `open_px, S, R, stop, zone_hi, zone_lo, zone_mid, exh1, exh2, t1, direction, direction_cn, levels[], zone_width` 等 |
| 阶梯比例常量 | `hz_engine` L24–33 | `LADDER = (0.0,19.1,38.2,50.0,61.8,80.9,100.0,161.8,261.8,423.6)`；`R_STOP=0.191 / R_ZONE_A=0.382 / R_ZONE_MID=0.5 / R_ZONE_B=0.618 / R_EXH1=1.618 / R_EXH2=2.618` |
| 比例→价格 | `hz_engine.price_at(ratio, open_px, S, direction)` L67–71 | `lad["levels"]` 即 `[{ratio,name,price}]`，**已含全部阶梯线的价格** |

**关键结论**：

1. **MT4 截图的 9 档比例（0.0/19.1/38.2/50/61.8/100/161.8/261.8/423.6）与 `hz_engine.LADDER` 完全对应**（仅缺 `80.9` 这一档；`build()` 产出的 `lad["levels"]` 含 10 档含 80.9）。阶梯线的**实际价格**由 `hz_engine.price_at(ratio, open_px, S, direction)` 计算，与引擎同源——可直接消费 `lad["levels"]`，无需页面端重新推算。
2. **可交易档位 ↔ 比例映射清晰**：`zone_hi/zone_mid/zone_lo` ↔ 38.2/50/61.8；`stop` ↔ 19.1（R_STOP）；`exh1` ↔ 161.8（R_EXH1）；`t1`（昨收）非固定比例；`open_end`(100.0) = 当日开盘价；`leg_start`(0.0) = open + S。
3. **画廊所需全部数据已可由 `huntback_sim.py` 产出**：每日期 = `compute_day_levels(date)`→`lad` + `fetch_day_1m(date)`→`bars` + `simulate_triggers(lad, bars)`→`zones/events/outcome`。无需新增计算逻辑。
4. **零未来函数已内建**：引擎 docstring + `hz_engine` 趋势/回归输入严格用 `≤D-open` 已收盘数据，`_run` 按 1m bar 升序前向扫描，仅用当前/已逝 bar（SRE 文档 §7 详述）。画廊为**纯展示层**，必须不引入任何前瞻逻辑。

> ⚠️ **澄清点 C1（已决议 · 致 architect-2）**：需求简报写「复用 `huntback_sim.py/huntback_core.py`」，但**代码树中不存在 `huntback_core.py`**（已 Glob/Grep 确认）。经与 architect-2 对齐，决议为**第三方案**：不新建 `huntback_core.py`（避免与已验证内核 `huntback_sim` 重名混淆的「幽灵模块」），也不止步于「仅 huntback_sim」。改为：**新增编排层 `huntzone_gallery_core.py`** 作为画廊唯一 import 面——
> - `huntzone_gallery_core.py` 内部 import `huntback_sim`（数据内核，零改动）+ `huntv2_core`（1d 取数/档位）+ `db`；
> - 对外暴露 `build_gallery_day(date, trigger, symbol)` / `build_gallery_range(start, end, trigger, symbol)` / `GALLERY_SCHEMA`；
> - 页面与 PRD 的 import 面 = 仅 `from huntzone_gallery_core import ...`，**不直接碰 `huntback_sim`**。
> `huntback_sim.py` 作为已验证内核**红线：不被修改**（M1 已验证）。本 PRD §4 已据此改写。

---

## 3. 功能范围（Scope）

### In Scope（本期必做）

1. **滑动/轮播组件（Swipe/Carousel）**
   - 横向滑动在多个单日案例卡片间切换：支持触摸滑动（移动端）、鼠标拖拽、鼠标滚轮、键盘 ←/→、底部圆点指示器。
   - 当前卡片居中、相邻卡片预加载（±1），切换用 GPU 合成 `translateX` 过渡，目标 ≤ 300ms、60fps、无布局抖动。
   - 顶部进度/页码（如「第 7 / 30 日 · 2026-09-08」）。

2. **单日场景卡片（Single-day Scenario Card）**
   - 等价于现有 `huntback_mockup.html` 的「② 单日下钻」面板，但数据来自真实模拟而非写死样例：
     - 1h K 线主图（聚合自 1m，对齐 MT4 H1；阳线红/阴线绿，沿用 mockup 配色）。
     - 标题行：`日期 · 方向(direction_cn) · trigger=N`。
     - 三区 P&L 盒（zone_a / zone_mid / zone_b / 单日合计）+ 单日 `outcome`（盈利/亏损/持平）。

3. **阶梯 overlay（Ladder Overlay）**
   - 在 K 线图上叠加水平参考线，比例严格取 MT4 参考集：`0.0 / 19.1 / 38.2 / 50.0 / 61.8 / 100.0 / 161.8 / 261.8 / 423.6`（即 `LADDER` 去掉 80.9 的子集；完整 10 档含 80.9 可选展示）。
   - 线价格 = `lad["levels"]` 对应项（=`price_at(ratio, open_px, S, direction)`），以 `name + price` 标注于右侧（如 `zone_a 38.2 = 2061.8`）。
   - **狩猎区色带**：在 `[zone_lo, zone_hi]` 区间画半透明矩形 band（沿用 mockup `#2a3650` 35% 透明度 + 「狩猎区 [38.2, 61.8]」文字）。

4. **方向箭头（Direction Arrow）**
   - 卡片显著位置给出方向箭头：做空 = 向下箭头（预期价格下行），做多 = 向上箭头；与 MT4 截图语义一致，颜色用 `direction_cn` 配色。

5. **事件标记（Event Markers）**
   - 在 K 线图上以圆点 + 文字标注 8 类事件：`fill / tp1 / tp2 / stop / be_arm / be_out / force22 / force_sl2`。
   - 颜色与现有 mockup CSS 类一致：`.e-fill` gold / `.e-tp1` cyan / `.e-tp2` 浅 cyan / `.e-stop` red / `.e-force22` yellow / `.e-be` purple。
   - 卡片底部给出**事件时间线**（trading 时间线）：`HH:MM(BJ) · 类型 · 价格 · 备注`（数据来自 `Event.time/type/price/note`）。

6. **触发器展示（Trigger Display）**
   - `be`（保本）/ `origin`（原点）切换 + `trigger` 滑块（8–26，默认 20），交互与 mockup 一致。
   - **trigger 策略（v1 vs 优化）**：v1 采用 `slides?trigger=T` 带缓存重取（SRE 缓存键 `(date,trigger,symbol)`，命中 <50ms，payload 最小）；因 `be_arm/be_out` 随 trigger 变，v1 按 active trigger 下发 + 按需 `/day` 重取。**优化项（v1 非必做）**：endpoint 内部改调 `simulate_triggers` 一次返回全部 19 档 zones，前端切滑块零延迟即时算 P&L。

7. **多日案例选择（Multi-day Case Selection）**
   - 提供「案例选择器」：参考 mockup ① 的月份日历热力图 + 权益曲线作为**入口/导向**，用户可勾选/过滤要纳入轮播的日子集（如「仅盈利日」「仅 short 日」「指定日期区间」）。
   - 选择器确定后，轮播组件按所选日序列渲染卡片。
   - 无信号日（`compute_day_levels` 返回 None / `d==0`）与缺 1m 日，在选择器与轮播中**显式标记 `missing`/「无信号」**，绝不静默丢弃（对齐 SRE 铁律）。

### Out of Scope（本期不做）

- 修改 `huntback_sim.py` / `hz_engine.py` / `hz_signal.py` / `huntv2_core.py` 的任何计算逻辑或档位几何。
- 修改现有 `/huntback` 效果图（`huntback_mockup.html`）的既有内容。
- 新增回测算法、统计口径、信号发现逻辑。
- 实时 tick 刷新（本期轮播为**历史交易日**案例；实时进行中当日不在轮播范围，标 `live_only` 不渲染）。
- 跨页（index / replay / realtime / ai_history / review）改动。
- 新建 `/huntback` 正式路由（若用户要求两页合并或复用路由，另立决策点 D，见 §8）。

---

## 4. 数据接口（数据源 `huntback_sim.py` · 编排层 `huntzone_gallery_core.py`）

> 数据面分两层（已与 architect-2 设计稿对齐）：
> - **数据内核（零改动复用）**：`huntback_sim.py` 的 `compute_day_levels` / `fetch_day_1m` / `simulate_day`·`simulate_triggers`——引擎逻辑、档位几何、无未来函数性质**全部不动**。
> - **画廊编排层（新增单文件）**：`huntzone_gallery_core.py`，是页面/PRD 的**唯一 import 面**；内部再 import `huntback_sim` + `huntv2_core` + `db`。下方接口为 `huntzone_gallery_core` 的公开 API，本身**不新增**任何回测/档位计算。

### 4.1 单日 slide 数据准备（huntzone_gallery_core.build_gallery_day）

```python
from huntzone_gallery_core import build_gallery_day, build_gallery_range, GALLERY_SCHEMA

# v1：按当前 active trigger 带缓存取单日 slide（SRE 缓存键 (date,trigger,symbol)，命中 <50ms）
def build_gallery_day(date: str, trigger: int = 20, symbol: str = "") -> dict:
    lad = compute_day_levels(date, symbol)          # huntback_sim -> dict 或 None(无信号)
    if lad is None:
        return {"date": date, "status": "no_signal", "missing_reason": "no_signal"}
    bars, source, missing = fetch_day_1m(date, symbol)   # huntback_sim：1m 柱，引擎回放用
    if missing or not bars:
        return {"date": date, "status": "1m_insufficient", "missing_reason": "1m_insufficient", "source": source}
    sim = simulate_day(lad, bars, trigger)          # huntback_sim：单 trigger 回放
    kline_1h = aggregate_1h(bars)                   # 由 1m 基础聚合 1h 蜡烛，对齐 MT4 H1 灵感
    return {
        "date": date,
        "symbol": symbol,
        "trigger": trigger,
        "direction": lad["direction"],
        "direction_cn": lad["direction_cn"],
        "status": "ok",
        "source": source,                            # "db" | "fapi_fallback"（SRE §C）
        "lad": lad,                                 # 含 levels[]、zone_*、stop、exh1、t1、open_px、S、R
        "ladder": lad["levels"],                    # 阶梯线（价格已算好）；画廊默认渲染简报 9 档子集
        "kline_1h": kline_1h,                       # 显示用 1h 蜡烛（聚合自 1m）
        "zones": {
            "origin": sim["origin"]["zones"],
            "be": sim["be"][str(trigger)]["zones"],  # 当前 trigger 的 3 区 P&L
        },
        "outcome": sim["outcome"],
        "events": [e.__dict__ for e in sim["events_all"]],  # 当前 trigger 的 8 类事件
        "bars_ref": {"count_1m": len(bars),
                     "open_time_ms": bars[0][0],
                     "close_time_ms": bars[-1][0]},
    }
```

> **trigger 策略（v1 vs 优化）**：v1 采用 `slides?trigger=T` 带缓存重取（缓存键 `(date,trigger,symbol)`，命中 <50ms，payload 最小；事件因 `be_arm/be_out` 随 trigger 变，v1 按 active trigger 下发 + 按需 `/day` 重取）。**优化项（v1 非必做）**：endpoint 内部改调 `simulate_triggers` 一次返回全部 19 档 zones，前端切滑块即时算 P&L（零延迟）。

### 4.2 多日范围（huntzone_gallery_core.build_gallery_range）

- 签名：`build_gallery_range(start, end, trigger=20, symbol="") -> {"days": [...slide], "summary": {...}}`。
- 输入：日期区间（如 2026-09-01 ~ 2026-09-30），逐日调用 `build_gallery_day(date, trigger, symbol)`。
- **按日缓存**（键 `(date, trigger, symbol)`，沿用 SRE §B 的 L1 缓存：历史日 ∞ TTL、随 `BUILD` 失效；`source/db_hit_rate` 可观测）。
- **首屏 payload 轻量**：每日期返回 `lad + ladder + zones + events + kline_1h(聚合) + status`（选择器/卡片头/阶梯/事件时间线/1h K线 所需），体积可控（≈ 30 日 × ~15KB ≈ 450KB）。
- 滑动性能：当前卡片 + 相邻 ±1 的明细随 range 预取；离屏卡片释放，避免内存膨胀（SRE §4）。

### 4.3 显示 K 线粒度：1h 聚合（对齐 MT4 H1 灵感）

- **显示层用 1h 蜡烛**（MT4 截图即  H1），由当日 1m 基础柱 `aggregate_1h(bars)` 聚合（本地 1m 已就绪，无需额外取数）；引擎回放仍严格用 **1m**（`fetch_day_1m` → `huntback_sim.simulate_day`），无未来函数性质不变。
- 单卡 1h 蜡烛 ≈ 24 根/日，渲染极轻；滑动流畅（见 AC-3）。
- 渲染建议（沿用 SRE 致前端硬约束）：K 线用 canvas + `large/sampling/progressive`；事件点独立 scatter（`large:true`）；阶梯用 `markArea` 带状；LOD 分级。

### 4.4 输出 JSON Schema（单日 slide，v1 · GALLERY_SCHEMA 契约）

```jsonc
{
  "date": "2026-09-02",
  "symbol": "",
  "trigger": 20,
  "direction": "short", "direction_cn": "做空",
  "status": "ok", "missing_reason": null, "source": "db",
  "lad": { "open_px": 2000.0, "S": 100.0, "R": 19.1,
           "stop": 2080.9, "zone_hi": 2061.8, "zone_mid": 2050.0, "zone_lo": 2038.2,
           "exh1": 1938.2, "t1": 1980.0, "prev_close": 1980.0, "special_gap": false,
           "direction_cn": "做空",
           "levels": [ {"ratio":0.0,"name":"0.0","price":2100.0}, ... ] },
  "ladder": [ {"ratio":0.0,"name":"0.0","price":2100.0},
              {"ratio":0.191,"name":"19.1","price":2080.9},
              {"ratio":0.382,"name":"38.2","price":2061.8},
              {"ratio":0.5,"name":"50.0","price":2050.0},
              {"ratio":0.618,"name":"61.8","price":2038.2},
              {"ratio":1.0,"name":"100.0","price":2000.0},
              {"ratio":1.618,"name":"161.8","price":1938.2},
              {"ratio":2.618,"name":"261.8","price":1838.2},
              {"ratio":4.236,"name":"423.6","price":1576.4} ],
  "kline_1h": [ {"open_time_ms":..., "o":..,"h":..,"l":..,"c":..}, ... ],
  "zones": {
    "origin": {"zone_a":102.7,"zone_mid":90.9,"zone_b":79.1,"total":272.7},
    "be": {"zone_a":102.7,"zone_mid":90.9,"zone_b":79.1,"total":272.7}
  },
  "outcome": "盈利",
  "events": [ {"tag":"zone_a","type":"fill","time":"08:06","ts_ms":<utc>,"price":2061.8,
             "note":"limit 成交（bar H≥挂单 2061.8）"}, ... ],
  "bars_ref": {"count_1m":1440,"open_time_ms":<utc D00:00>,"close_time_ms":<utc D23:59>}
}
```
> `GALLERY_SCHEMA` 声明上述 slide/day 字段契约，供 API 生产方、前端消费方、testing 契约测试三方共用，确保数据面一字不差。
> 数值示例沿用 `huntback_mockup.html` 的 2026-09-02 short 样例（open=2000 / S=100 / prevClose=1980），便于 1:1 还原与对账。

---

## 5. 非功能约束（Non-functional Constraints）

| # | 约束 | 含义与落地 |
|---|------|-----------|
| NF1 | **严格因果 / 零未来函数** | 全部数字来自 `huntback_sim.py` 回放（已声明严格因果）。画廊为**纯展示层**，禁止引入任何前瞻：事件只画在 `ts_ms ≤ 当前视口时间`；不得用未来 bar 推算任何展示值。不变式自检（SRE §7.5）：将 `as_of` 后移 +1 天重算，当日档位/事件不变 → 列为 P0 单测（CI 卡死）。 |
| NF2 | **零代理纪律** | 对齐 SRE 铁律：**绝不猜 S、绝不静默用占位档位**。取数失败/缺 1m/无信号日 → 显式标 `missing`/「无信号」并降级展示，**绝不**用合成/默认档位填充。代理（PROXIES）宕 → 走 fapi 兜底或显式报错，不静默吞。 |
| NF3 | **单文件 Python 实现（编排层）** | 新增功能后端逻辑收敛在**一个**新建 Python 文件 `huntzone_gallery_core.py`（画廊编排层）：内含数据准备 `build_gallery_day/range` + `GALLERY_SCHEMA` 契约，**页面唯一 import 它**（内部再 import `huntback_sim`/`huntv2_core`/`db`，均零改动）。HTML 渲染仿 `/huntv2`、`/wuyuan` 的 `*_template.py` 单文件内联模式，经 `main.py` 同一 uvicorn app 的**新增 3 条路由**返回（不新建进程、不加 `--reload`）。**不**为本次需求拆分多模块；`huntback_sim.py` 红线不改。 |
| NF4 | **不修改既有功能** | 不改 `huntback_sim.py`/`hz_engine.py`/`hz_signal.py`/`huntv2_core.py` 的计算逻辑；不改现有 `/huntback` 效果图；不改 `main.py` 既有路由；仅**新增**路由与文件。既有页面行为零回归。 |
| NF5 | **预计算 + 缓存，禁止请求链路实时取数** | 多日 1m 不可在页面加载时实时拉取（SRE §0/§1：192 次 fapi GET）。服务端按日 `simulate_day`(或优化 `simulate_triggers`) + 缓存（L1 `(date,trigger,symbol)`）；首屏只下 JSON。计算在请求外（cron/后台线程），缺失返回 429+轮询（仿 `/api/sync/db`）。 |
| NF6 | **渲染性能（滑动流畅）** | 单卡 1h 蜡烛(聚合自 1m) 用 canvas + `large/sampling/progressive`；阶梯 `markArea` 带状；事件 `large` scatter；LOD 分级（全量按日汇总 → 滑入再取明细）。避免一次性渲染全区间 288k 柱 + 15k 事件（SRE §4）。 |
| NF7 | **可观测 / 错误码** | 沿用 `main.py` 的 `{code,msg,data}` schema：200 成功 / 200+`ok:False`+`reason`（无信号/缺 1m，不用 204）/ 400 参数错 / 429 构建中 / 500 内部 / 502 fapi 不可达（不猜 S）。响应带 `source`/`as_of`/`build` 维度。 |

---

## 6. 默认行为与边界（明确口径，避免歧义）

1. **保留 `/huntback`**：现有效果图原样保留；本页为独立新页（路由名见决策点 D）。
2. **空选择 = 全量**：进入页面未筛选 → 默认渲染近期 N 日（如最近 30 个有信号日）的轮播。
3. **无信号/缺数据日**：在案例选择器中以灰/警示标记，轮播中如被选入则显示「无信号/数据不足」占位卡，**不**跳过序号、不静默消失。
4. **trigger 滑块默认 20**，be/origin 默认 be；v1 拖动按 active trigger 带缓存重取（`slides?trigger=T`，命中 <50ms），**不重算**；优化项可前端即时切 19 档（见 §4.1 注）。
5. **阶梯比例固定为简报 9 档**（0.0/19.1/38.2/50/61.8/100/161.8/261.8/423.6）；完整 10 档（含 80.9）是否展示由决策点 D 决定。
6. **日边界对齐**：1m 窗口按 UTC 自然日切分（与 `fetch_day_1m` 一致），避免与档位「日」错位（SRE §E.3）。
7. **价格量纲**：本地 1m 为 PAXG+12（已 XAU 量纲）；叠加层须与 `lad` 同基准（SRE §E.2），PRD 不引入额外偏移。

---

## 7. 验收标准（Acceptance Criteria）

### AC-1 数字可溯源（Traceability，P0）

对轮播中任意一日 `d` 与任意 trigger `t`：

- [ ] **三区 P&L 可复算**：页面 `zones.be.zone_*`（当前 trigger t）= `round(realized * K_USD, 4)`，用 `huntback_sim.simulate_day(lad, bars, t)` 独立重算后**逐字节相等**（K_USD=1.0，L25）。
- [ ] **单日合计 = 三区之和**：`zones.be.total == zone_a+zone_mid+zone_b`（容差 1e-9）。
- [ ] **阶梯线价格 = `price_at`**：每个 `ladder[i].price` 用 `hz_engine.price_at(ratio, open_px, S, direction)` 重算相等；且 `lad.levels` 与 `ladder` 同源。
- [ ] **事件可对账**：每个事件 `price/time/note` 来自 `Event` 字段；`time`（HH:MM BJ）与 `ts_ms`（UTC ms）互算一致（`datetime.fromtimestamp(ts_ms/1000, BJ).strftime("%H:%M") == time`）。
- [ ] **origin vs be 一致**：`zones.origin` 与 `simulate_day(lad,bars,trigger=None)` 输出一致；默认 trigger=20 时 `zones.be` 与 `simulate_day(lad,bars,20)` 一致（v1 `zones.be` 为当前 trigger 单档，非 19 档字典）。
- [ ] **missing 不造假**：无信号/缺 1m 日 `missing=true` 且 `missing_reason` 非空，页面显式标记，无任何占位数字。
- [ ] **CI 不变式**：将 `as_of` 后移 +1 天重算断言当日档位/事件不变（SRE §7.5，P0）。

### AC-2 视觉效果与 MT4 截图对齐（Visual Fidelity）

- [ ] **9 档阶梯完整呈现**：比例轴严格含 `0.0/19.1/38.2/50.0/61.8/100.0/161.8/261.8/423.6`，右标注名称+价格；线间距按**真实价格线性比例**（非任意像素）。
- [ ] **狩猎区色带**：`[zone_lo, zone_hi]` 区间半透明 band，标签「狩猎区 [38.2, 61.8]」，与 mockup 配色一致（`#2a3650` 35%）。
- [ ] **方向箭头**：做空↓/做多↑，与 MT4 截图语义及 `direction_cn` 一致。
- [ ] **事件标记配色**：8 类事件颜色与 `huntback_mockup.html` CSS 类（`.e-fill/.e-tp1/.e-tp2/.e-stop/.e-force22/.e-be`）逐一对应。
- [ ] **与现有 `/huntback` 视觉语言统一**：深色主题、gold/cyan/red 主色、字体/圆角/面板风格一致（继承而非新建风格）。

### AC-3 滑动流畅（Smooth Swipe，P0 体验）

- [ ] 触摸/拖拽/滚轮/←→/圆点 五种切换方式均可用。
- [ ] 切换过渡 ≤ 300ms，滑动过程 **≥ 50fps**（中端设备：笔记本 i5/8GB 或主流手机），无布局抖动（用 `transform: translateX` + `will-change`，不触发 reflow）。
- [ ] 相邻 ±1 卡片**预加载**（含 1h 明细），切换无白屏/无 >100ms 卡顿。
- [ ] 轮播 30 日连续滑动，内存不持续增长（离屏卡片释放明细，SRE §4/§6）。
- [ ] trigger 滑块拖动实时更新 P&L/事件，**无服务端请求、无掉帧**。

### AC-4 交付质量（不二过）

- [ ] 新增文件/路由通过 `node --check`（若含内联 JS）与项目既有静态检查；浏览器 Console 无红色报错。
- [ ] 纯新增，硬刷新即见，**无需重启 8000 进程**（仿 `/huntback` 类内联模板 + `no-store` 头）。
- [ ] 既有 `/huntback` 与 `main.py` 其他路由**零回归**（自动化冒烟 + 人工核验）。
- [ ] 满足「代码级溯源」纪律：PRD 中每处数据断言可回溯到 `huntback_sim.py`/`hz_engine.py` 具体行（本文 §2 已建链）。

---

## 8. 需用户/设计方拍板的决策点（对齐用）

| # | 决策 | 推荐 | 备注 |
|---|------|------|------|
| D1 | `huntback_core.py` 不存在，数据面以谁为准？（**已决议**） | **不建 `huntback_core.py`，改用 `huntzone_gallery_core.py` 作编排层**（architect-2 设计稿已定）：页面唯一 import `huntzone_gallery_core`，其内部 import `huntback_sim`（零改动）+ `huntv2_core` + `db`；`GALLERY_SCHEMA` 定契约。见 §2 C1 / §4 | 已闭环 |
| D2 | 新页路由名 | `/huntback/gallery` 或 `/huntzone-gallery`（独立新路由） | 不动现有 `/huntback` |
| D3 | 阶梯是否含 80.9 档 | 默认仅简报 9 档；80.9 可选 | `lad.levels` 含 10 档，渲染子集即可 |
| D4 | 案例选择器形态 | 复用 mockup ① 日历热力图 + 权益曲线作入口，支持「仅盈利/仅 short/日期区间」过滤 | 与现有视觉统一 |
| D5 | 默认纳入轮播的天数 | 最近 30 个有信号日（可配置） | 兼顾首屏体积与体验 |
| D6 | 单文件 Python 的落点文件名（**已定**） | `huntzone_gallery_core.py`（编排层；含 `build_gallery_day/range` + `GALLERY_SCHEMA`） | NF3 |

---

## 9. 交付文件清单

| 文件 | 改动 |
|------|------|
| `huntzone_gallery_core.py`（新建） | 唯一新增后端模块（编排层）：`build_gallery_day/range` + `GALLERY_SCHEMA`，内部 import `huntback_sim`(零改)/`huntv2_core`/`db`；页面唯一 import 它 |
| `<gallery>_template.py` 或内联 HTML（新建） | 画廊页内联 HTML 模板（Vue3 无构建，仿 `*_template.py`） |
| `main.py` | **仅新增 3 条路由**（画廊页 + 范围数据 + 单日数据；具体路径见 architect-2 设计稿），既有路由零改动 |
| `docs/PRD-huntzone-gallery-2026-10-09.md` | 本文档 |
| `huntback_mockup.html` | **不改**（现有 `/huntback` 效果图保留） |
| `huntback_sim.py` / `hz_engine.py` / `hz_signal.py` / `huntv2_core.py` | **不改**（计算逻辑零回归；红线：不动已验证内核） |

---

## 10. 一句话结论

在保留现有 `/huntback` 效果图的前提下，新增一个**滑动/轮播页**：逐日浏览多个真实狩猎区交易日案例（单日 1h K 线（聚合自 1m，对齐 MT4 H1）+ MT4 比例阶梯 overlay + 方向箭头 + 8 类事件标记 + be/origin & trigger 8–26 切换 + 多日案例选择器），**数据内核复用已验证的 `huntback_sim.py`（零改动）、编排层 `huntzone_gallery_core.py` 单文件实现、严格因果零未来函数、纯新增不改动既有功能**，所有展示数字可溯源到引擎回放输出。
