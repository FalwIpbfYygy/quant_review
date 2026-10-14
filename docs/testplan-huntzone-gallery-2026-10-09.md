# 狩猎区场景轮播/滑动页 · 测试计划（Tessa · 测试专家）

> 项目：`D:\quant_review`
> 被测特性：新增「狩猎区画廊 / `huntzone-gallery`」滑动页（每屏=单交易日 1m/1h K 线 + 狩猎区阶梯 overlay + 事件标记 + 三区 P&L），数据全部复用已验证的 `huntback_sim.py`（M1 what-if 引擎）。
> 关联文档：`PRD-huntzone-gallery-2026-10-09.md`（§7 验收标准 AC-1~AC-4）、`design-huntzone-gallery-2026-10-09.md`（§11 测试要点）、`sre_huntzone_page.md`（§7.5/§B/§C/§D/§5）、`huntback_mockup.html`（视觉基线）、`tests/test_huntback_sim.py`（已有 11 单测）。
> 范围约束（PRD §NF4/§NF3）：纯新增，不修改 `huntback_sim.py`/`hz_engine.py`/`hz_signal.py`/`huntv2_core.py`；测试只针对新增展示/编排层 + 既有内核补缺口。

---

## 0. 测试策略总览（金字塔）

```
            /\  E2E / 视觉验证  少量：浏览器走真实滑动、像素/结构断言
           /  \ 性能与边界      少量：200 天压测、30 天连续滑动、缺数/休市日
          /集成\ FastAPI 路由    中量：200/400/429/502 + 与引擎一致性
         /------\ 前端单元      中量：滑动组件/trigger 滑块/ECharts ≤3 生命周期
        / 单元   \ 数据转换/编排 大量：_agg_1m_to_1h、build_gallery_*、状态机
       /----------\ 内核补缺口  大量：long 方向、公共 API 聚合、无未来函数移位(P0)
```

- **原则**：内核（`huntback_sim.py`）已高覆盖，本计划以「补缺口 + 新增编排/前端/集成」为主，不重复造轮子。
- **高风险优先**：无未来函数不变式（P0，PRD AC-1 / SRE §7.5）、long 方向（当前 0 覆盖）、API 与引擎一致性（AC-1）排在最前。
- **可运行性**：内核与编排层纯函数单测零网络/零 DB（用 `hz_engine.build` 合成几何 + 合成 1m 柱）；数据层（`compute_day_levels`/`fetch_day_1m`）用 mock DB/mock fapi 注入。

---

## 1. 测试什么 —— 组件 → 区域映射

| # | 区域 | 被测对象 | 主要测试类型 |
|---|------|----------|--------------|
| A | 内核补缺口 | `huntback_sim`：long 分支、`simulate_day`、`simulate_triggers`、`no_future` 移位、trigger 边界、tz 对齐 | 单元 |
| B | 数据转换（新增） | `huntzone_gallery_core._agg_1m_to_1h`、`build_gallery_day`、`build_gallery_range`、状态机 | 单元 |
| C | 滑动组件（新增） | 索引导航（5 方式）、`IntersectionObserver` 懒渲染、ECharts ≤3 生命周期、trigger 滑块纯前端切换 | 单元（JS）/组件 |
| D | 事件渲染（新增） | 8 类事件 → CSS 类映射、9 档阶梯集合、zone 色带几何、方向箭头、事件计数 | 单元（JS）/结构 |
| E | FastAPI 路由（新增） | `/api/huntzone-gallery/slides`、`/day`、缺数 502、合法 200、错误 400/429、与引擎一致性、no-store | 集成 |
| F | 端到端视觉 | 每 slide 阶梯线数/zone 色带/事件标记数/配色，对齐 `huntback_mockup.html` | E2E /视觉 |
| G | 性能与边界 | 多 slide 加载（30 天连续滑动 / 200 天画廊）、缺数日、休市日、进行中当日 `live_only` | 性能 /边界 |
| H | 跨层红线 | 无未来函数不变式（P0）、错误码消费（200/400/429/502 + ok/reason/error） | 单元 + 集成 |

---

## 2. 各区域详细测试设计

### 2.1 区域 A —— 内核补缺口（对齐 PRD AC-1 / SRE §7.5）

> 现状：已有 11 单测 **全部** 使用 `direction="short"`，且只测 `_run`，未测公共 API `simulate_day`/`simulate_triggers`。

**A1. long 方向全分支（最高优先级缺口）**
- 复刻 short 的 6 个场景，但 `direction="long"`：fill（l≤entry）、tp1（h≥t1）、tp2（h≥exh1）、be_arm（h≥entry+trigger）、be_out（l≤entry）、stop（l≤stop）、force22。
- 断言 long 几何（`zone_a=1938.2/zone_mid=1950.0/zone_b=1961.8/stop=1919.1/exh1=2061.8`，见 `test_huntback_sim.py` L36）与 `build()` 产出一致；三区独立持仓的盈亏符号与 short 镜像。

**A2. 公共 API 聚合（AC-1「origin vs be(20) 一致」）**
- `simulate_day(lad, bars, trigger=20)` → 断言 `res["origin"]` 与 `simulate_day(lad, bars, None)` 等价；`res["be"]["20"]` 与 `simulate_day(lad, bars, 20)` 等价；`res["events_all"]` == `be["20"]["events"]`（be_arm/be_out 随 trigger 变化）。
- `simulate_triggers(lad, bars)` → 断言返回 `be{8..26}` 共 19 档，且 `be["20"]==simulate_day(...,20)`、`be["8"]` 与 `be["26"]` 边界档均含有效 events。

**A3. 无未来函数移位不变式（P0，PRD AC-1 / SRE §7.5）**
- 强不变式（超出已有 `test_determinism_and_no_future` 的 `ts_ms<=force_close_ms` 必要条件）：**在 `bars` 末尾追加任意「收盘后」柱（ts > force_close_ms），`force_close_ms` 之前的事件序列与 realized 必须完全不变**。
- 另：对 `compute_day_levels` 喂入「含明日日线」的输入，断言当日 `lad["levels"]` 与只喂「≤D-open 已收盘日线」时完全一致（证明档位生成不泄漏未来）。

**A4. trigger 边界值（8 与 26）**
- `trigger=8`：be_arm 阈值 entry±8，构造刚好触发/不触发的边界柱，断言行为正确。
- `trigger=26`：同上；并断言 `simulate_triggers` 循环边界（首档 8、末档 26）完整。

**A5. 时区互算一致性（AC-1「事件可对账」）**
- 对每个 `Event`：断言 `datetime.fromtimestamp(ts_ms/1000, BJ).strftime("%H:%M") == time`。
- 特例：force22 事件 `time=="22:30"`（BJ）且 `ts_ms` 解析为 UTC 14:30。

**A6. force_sl2 集成路径（非白盒）**
- 构造「2 区硬止损、第 3 区已成交未退出」场景（如 zone_a/zone_mid 同根触 stop，zone_b 未触），断言 `_run` 在整根判定结束后对 zone_b 触发 `force_sl2` 强平（当前 11 测只覆盖「三区同触 stop→force_sl2 休眠」与白盒 `force_close`）。

### 2.2 区域 B —— 数据转换（新增纯函数，对齐 AC-1 溯源）

**B1. `_agg_1m_to_1h`（设计 §ADR-G3，无前视）**
- 输入 1440 根 1m → 输出 24 根 1h；断言每根 1h 的 O=该小时首根 O、H=max、L=min、C=末根 C，**且只用自身窗内数据**（在中间插入一根「未来高值」不得改变已聚合小时）。
- 边界：UTC 自然日切分，首/末小时不满 60 根时仍闭合；空输入 → 空列表。

**B2. `build_gallery_day` 字段映射**
- 用真实 `compute_day_levels`+合成 `fetch_day_1m` 桩，断言输出含 `date/direction/direction_cn/ladder/levels/zones{origin,be}/events_by_trigger/outcome/source`，且 `zones.be["20"]` 与 `simulate_triggers` 直出一致（AC-1 溯源）。

**B3. 状态机（设计 §11 / PRD §9.2）** —— `ok | no_signal | missing | incomplete | live_only`
- `compute_day_levels` 返 None（d==0）→ `status="no_signal"`。
- `fetch_day_1m` 返 `missing=True` 或空 bars → `status="missing"` + `missing_reason` 非空，**绝不返回任何占位数字**（AC-1「missing 不造假」）。
- bars 数 `<1300` → `status="incomplete"`。
- 日期 == 最新进行中当日 → `status="live_only"`，不渲染后视。
- 正常 → `status="ok"`。
- 断言：任意缺失状态 slide 渲染占位卡、不抛异常、不拖垮整列（设计 §11 第一条）。

### 2.3 区域 C —— 滑动组件（对齐 AC-3 流畅 / 设计 §8）

**C1. 索引导航（5 种方式）**：触摸 swipe / 鼠标拖拽 / 滚轮 / 键盘 ←→ / 底部圆点。各方式断言 `currentIndex` 正确变更、页码「第 k / N 日」更新、±1 邻居预加载。

**C2. ECharts 生命周期（设计 §8.1 硬约束）**：`IntersectionObserver` 进入视口（±1 缓冲）才 `echarts.init`；移出远区 `dispose()`。断言**任意时刻 `echarts.getInstanceByDom` 活跃实例数 ≤3**，与 N（30/200）无关。

**C3. trigger 滑块纯前端切换（PRD AC-3 末条）**：拖动滑块 → `currentTrigger` 变更并直接重读 `payload.zones.be[trigger]` / `events_by_trigger[trigger]`，**断言全程零 `fetch` 调用**（mock fetch 计数=0）、无掉帧（用 `requestAnimationFrame` 计数间接验证）。

**C4. scroll-snap 过渡**：切换过渡 `≤300ms`，使用 `transform: translateX` + `will-change`，不触发 reflow（断言无 layout thrash：对比切换前后 `document.body.offsetHeight` 不变）。

### 2.4 区域 D —— 事件渲染（对齐 AC-2 视觉）

**D1. 8 类事件 → CSS 类映射**：`fill/.e-fill(gold)`、`tp1/.e-tp1(cyan)`、`tp2/.e-tp2(浅青)`、`stop/.e-stop(red)`、`be_arm|be_out/.e-be(purple)`、`force22/.e-force22(yellow)`、`force_sl2/.e-force22(orange)` —— 与 `huntback_mockup.html` CSS 类逐一对应（PRD AC-2 末两条）。

**D2. 9 档阶梯集合**：渲染线集合严格为 `{0.0,19.1,38.2,50.0,61.8,100.0,161.8,261.8,423.6}`，价格取自 `lad["levels"]`（`price_at(ratio,open_px,S,direction)` 同源），右标注「名称+价」；线间距按真实价格线性比例（非任意像素）。

**D3. zone 色带几何**：`markArea` 覆盖 `[zone_lo, zone_hi]`（38.2~61.8），标签「狩猎区 [38.2, 61.8]」，配色 `#2a3650` 35%（对齐 mockup）。断言 band 的 y 范围 == 两档价格换算坐标。

**D4. 方向箭头**：`direction=="short"` → 向下箭头；`direction=="long"` → 向上箭头。

**D5. 事件标记计数**：对给定 trigger `t`，渲染的事件圆点数 **严格等于** `len(events_by_trigger[t])`（AC-1「事件可对账」的可视化 counterpart）。

### 2.5 区域 E —— FastAPI 集成（对齐 AC-1 溯源 / SRE §5 错误码）

**E1. `GET /api/huntzone-gallery/slides` 成功**：合法 `start/end` → `200` + `ok:true` + `summary{win,loss,flat,total_usd,best_day,worst_day}` + `days[]`；断言 `no-store, no-cache` 响应头存在。

**E2. 与引擎一致性（AC-1 核心）**：对返回的每个 `day`，用其 `date` 重新调用 `huntback_sim.compute_day_levels`+`fetch_day_1m`+`simulate_triggers`，断言 `pnl.be["20"]` 与 `events` 与接口返回**逐字段相等**（不二过：任何展示数字必须能 1:1 溯源到引擎）。

**E3. 缺数 → 502 红字（任务明确要求）**：mock fapi/DB 不可达 → 返回 `502 + {"error":"取数失败：…"}`（不猜 S）；前端消费该错误 → 顶部**红色警告条**（`stale:true` 或错误条），断言 DOM 出现 `.banner.red`/`.warn` 且文本含「取数失败」。

**E4. 无信号/缺 1m 日（逐日 status，不整页崩）**：区间内混入 `no_signal`/`missing` 日 → 接口仍 `200` + 该 `day.status` 标 `no_signal`/`missing` + `ok:False` + `reason`；断言其余 ok 日数据完整（SRE §5 / PRD §4.1）。

**E5. 参数错误 → 400**：`start` 格式非法 / `start>end` / `trigger` 越界 → `400` + `error` 字段。

**E6. 冷启动 → 429 + 轮询**：区间未构建完 → `429 + {"building":true}`；前端轮询直到 `ok:true`（仿 `/api/sync/db`）。

**E7. `/api/huntzone-gallery/day`**：`date`+`trigger` → `200` + `kline_1m`（~1440 根）+ `events@trigger` + `pnl`；命中 L1 缓存键 `(date,trigger,symbol)`，与 `slides` 共享零重复计算（SRE §B）。

### 2.6 区域 F —— 端到端视觉验证（对齐 AC-2）

用真实浏览器（Playwright/pytest-playwright）走 `/huntzone-gallery?start=2026-09-01&end=2026-09-30`：
- F1. 每屏渲染**恰好 9 条阶梯线**（D2 集合），且 zone 色带矩形存在并带正确标签。
- F2. 某 trigger 下事件圆点数 == 引擎 `events_by_trigger[t]` 长度（D5）。
- F3. 三区 P&L 盒数值 == 接口 `pnl.be[t]`/`origin`（含合计与 outcome 配色）。
- F4. 视觉回归：对关键屏截图与 `huntback_mockup.html` 基线 diff（主色/圆角/面板风格一致，设计 §7 ADR-G1）。
- F5. 缺失日屏：显示占位卡 + `reason`，**无空白崩溃**、无 Chart 实例残留。

### 2.7 区域 G —— 性能与边界（对齐 AC-3 / 设计 §8/§9.3）

- G1. **30 天连续滑动**：触摸连续翻页，断言单页切换过渡 `≤300ms`、过程 `≥50fps`（中端设备：i5/8GB 或主流手机）、滑动 30 屏后 JS 堆内存不持续增长（离屏释放 1m 原始柱，SRE §4/§6）。
- G2. **200 天画廊压测**：断言活跃 ECharts 实例 `≤3`（设计 §8.1）、首屏 JSON `<600KB`（PRD §4.1 估算）、页面不卡死、`summary` 聚合正确。
- G3. **缺数日**：区间内随机插入 `missing`/`no_signal`/`incomplete` 日，断言仅该屏占位、轮播顺序与索引不偏移（状态机不污染邻屏）。
- G4. **休市日**：某自然日无 1m 柱（持平/休市）→ `status="missing"` 或 `flat` 处理，不渲染伪 K 线。
- G5. **进行中当日 `live_only`**：`end`=今日 → 该屏标 `live_only` 且仅渲染截至当前的 1m，不出场判定不前瞻（PRD §9.1）。

### 2.8 区域 H —— 跨层红线

- H1. **无未来函数（P0）**：除 A3 单测外，CI 增加「golden-file」：对参考报告抽样的真实日 `kline_1m` 重放，断言 events/realized 与参考报告逐日吻合（SRE §2 事实「对参考报告 200 日逐日核对」）。
- H2. **错误码消费（设计 §11）**：前端统一封装 `parseResp(resp)` → 解析 `code/ok/reason/error`；单测覆盖 `200/400/429/502` 四分支与 `stale:true` 降级条渲染。

---

## 3. 覆盖率目标

| 模块 / 区域 | 目标 | 现状 |
|-------------|------|------|
| `huntback_sim._ZoneState` / `_run` | 分支 100% | ~高（仅 short） |
| `huntback_sim.simulate_day` / `simulate_triggers`（公共 API） | 行/分支 100% | **0%**（仅 `_run` 测过） |
| `huntback_sim` long 方向 | 分支 100% | **0%** |
| 无未来函数移位不变式 | P0（CI 卡死） | 仅必要条件（`ts_ms<=fcm`） |
| `compute_day_levels` / `fetch_day_1m`（mock 注入） | 关键路径 100% | **0%**（显式排除） |
| `huntzone_gallery_core._agg_1m_to_1h` | 100% | n/a（新增） |
| `build_gallery_day` / `build_gallery_range` + 状态机 | 100% | n/a（新增） |
| FastAPI 路由（E1~E7 全错误码） | 合同 100% | n/a（新增） |
| 前端滑动组件（C1~C4） | 关键行为 100% | n/a（新增） |
| 视觉结构（D1~D5 / F1~F5） | 关键结构 100% | n/a（新增） |
| 性能（G1~G5） | 基线达标 | n/a |
| **golden-file（参考报告对齐）** | 抽样 ≥20 真实日 | **0%** |

**整体目标**：内核回归 0 漏（不二过，AC-4）；新增编排/前端单测覆盖 ≥90% 分支；集成覆盖全部 5 类错误码；E2E 覆盖 9 档阶梯/zone 带/事件计数三件套。

---

## 4. 示例测试用例（可直接落地）

> 以下片段基于真实 API 签名（`test_huntback_sim.py` 夹具 + `huntback_sim` 公共函数）。

### 4.1 【A1】long 方向 origin tp1/tp2（补最大缺口）

```python
# tests/test_huntback_long.py  (纯函数, 零网络)
import pytest, huntback_sim as H
from hz_engine import build

BASE = 1735689600000  # 2026-01-01 UTC00:00 = BJ08:00
def _lad(direction="long", open_px=2000.0, S=100.0, prev_close=1980.0):
    return build(open_px, S, direction, prev_close=prev_close)
def _bar(t_min, o, h, l, c):
    return (BASE + t_min*60000, o, h, l, c)

def test_long_origin_tp1_tp2():
    lad = _lad("long")                 # zone_a=1938.2 zone_mid=1950 zone_b=1961.8 t1=1980 exh1=2061.8
    bars = [
        _bar(0, 1940, 1945, 1930, 1935),   # l<=1938.2 → 三区全 fill (long: l<=entry)
        _bar(1, 1970, 1990, 1965, 1985),   # h>=1980 → 三区 tp1(平50%)
        _bar(2, 2050, 2070, 2045, 2065),   # h>=2061.8 → 三区 tp2(平余50%)
    ]
    res = H._run(lad, bars, None)          # origin
    types = [e.type for e in res["events"]]
    assert types.count("fill") == 3 and types.count("tp1") == 3 and types.count("tp2") == 3
    # long: realized = p - entry
    # za=0.5*(1980-1938.2)+0.5*(2061.8-1938.2)=20.9+61.8=82.7
    # zm=0.5*30+0.5*111.8=70.9  zb=0.5*18.2+0.5*100=59.1  => 212.7
    assert res["realized_usd"] == pytest.approx(212.7, abs=1e-6)
    assert res["outcome"] == "盈利"
```

### 4.2 【A2/A5】公共 API 一致性 + 时区互算（AC-1）

```python
def test_simulate_day_api_aggregation_and_tz():
    lad = _lad("short"); bars = [_bar(0,2060,2070,2055,2065), _bar(1,2000,2005,1975,1985),
                                 _bar(2,1980,1985,1930,1940)]
    d20 = H.simulate_day(lad, bars, 20)
    dNone = H.simulate_day(lad, bars, None)
    trig = H.simulate_triggers(lad, bars)
    # API 聚合一致性
    assert d20["origin"] == dNone
    assert d20["be"]["20"] == trig["be"]["20"]
    assert d20["events_all"] == trig["be"]["20"]["events"]
    assert set(trig["be"].keys()) == set(range(8, 27))   # 19 档
    # 时区互算：BJ HH:MM == 由 ts_ms 反算
    from datetime import timezone, timedelta
    BJ = timezone(timedelta(hours=8))
    for e in d20["events_all"]:
        from datetime import datetime
        assert datetime.fromtimestamp(e.ts_ms/1000, BJ).strftime("%H:%M") == e.time
```

### 4.3 【A3】无未来函数移位不变式（P0）

```python
def test_no_future_shift_invariant():
    lad = _lad("short"); bars = [_bar(0,2060,2070,2055,2065), _bar(1,2000,2005,1975,1985),
                                 _bar(2,1980,1985,1930,1940)]
    fcm = BASE + H._FORCE_CLOSE_OFFSET_MS
    r0 = H._run(lad, bars, 20)
    # 追加「收盘后」任意柱（ts 远超 force_close_ms）
    future = bars + [(fcm + 10*60000, 9999, 9999, 9999, 9999),
                     (fcm + 20*60000, 1, 1, 1, 1)]
    r1 = H._run(lad, future, 20)
    # force_close_ms 之前的事件序列与 realized 必须不变
    ev0 = [e for e in r0["events"] if e.ts_ms <= fcm]
    ev1 = [e for e in r1["events"] if e.ts_ms <= fcm]
    assert [ (e.type,e.price,e.ts_ms) for e in ev0 ] == [ (e.type,e.price,e.ts_ms) for e in ev1 ]
    assert r0["realized_usd"] == r1["realized_usd"]
```

### 4.4 【B1】`_agg_1m_to_1h` 无前视

```python
def test_agg_1m_to_1h_no_lookahead():
    from huntzone_gallery_core import _agg_1m_to_1h
    bars = [ (BASE+i*60000, 2000+i, 2005+i, 1995+i, 2002+i) for i in range(1440) ]
    h1 = _agg_1m_to_1h(bars)
    assert len(h1) == 24
    # 第 0 小时 O=首根O, H=max, L=min, C=末根C
    assert h1[0]["o"] == 2000 and h1[0]["c"] == 2002 and h1[0]["h"]==2005 and h1[0]["l"]==1995
    # 无前视：把最后一小时的一根改成极端值，不影响前 23 小时
    bars2 = list(bars); bars2[1439] = (BASE+1439*60000, 99999,99999,99999,99999)
    h2 = _agg_1m_to_1h(bars2)
    assert all(h2[i]==h1[i] for i in range(23))
```

### 4.5 【B3】状态机（设计 §11）

```python
@pytest.mark.parametrize("scenario,expect_status", [
    ("no_signal_lad_none", "no_signal"),
    ("missing_1m",         "missing"),
    ("incomplete_bars",    "incomplete"),
])
def test_build_gallery_day_status(scenario, expect_status):
    from huntzone_gallery_core import build_gallery_day
    if scenario == "no_signal_lad_none":
        with mock.patch("huntback_sim.compute_day_levels", return_value=None):
            d = build_gallery_day("2026-09-02")
    elif scenario == "missing_1m":
        with mock.patch("huntback_sim.compute_day_levels", return_value=_lad()), \
             mock.patch("huntback_sim.fetch_day_1m", return_value=([], "db", True)):
            d = build_gallery_day("2026-09-02")
    assert d["status"] == expect_status
    assert d["missing"] is True
    assert d["missing_reason"]                 # 非空，绝不造假
    assert "zones" not in d or d.get("zones") is None   # 不返回占位数字
```

### 4.6 【E2/E3】FastAPI 一致性 + 缺数 502

```python
def test_slides_consistency_and_502(client):
    # 一致性（AC-1）
    r = client.get("/api/huntzone-gallery/slides?start=2026-09-01&end=2026-09-05&trigger=20")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.headers["cache-control"].lower() == "no-store, no-cache"  # 反缓存
    for day in r.json()["days"]:
        if day["status"] != "ok": continue
        import huntback_sim as H
        lad = H.compute_day_levels(day["date"]); bars,_,_ = H.fetch_day_1m(day["date"])
        sim = H.simulate_triggers(lad, bars)
        assert day["pnl"]["be"]["20"] == sim["be"]["20"]["zones"]      # 1:1 溯源
        assert len(day["events"]) == len(sim["be"]["20"]["events"])    # 事件对账

    # 缺数 → 502 + 红字（mock fapi/DB 不可达）
    with mock.patch("huntback_sim.fetch_day_1m", side_effect=RuntimeError("fapi down")):
        r2 = client.get("/api/huntzone-gallery/slides?start=2026-09-01&end=2026-09-02")
        assert r2.status_code == 502 and "error" in r2.json()
```

### 4.7 【D5/C3】前端结构 + trigger 滑块纯前端（伪代码/Jest）

```javascript
// 事件计数 == 引擎 events_by_trigger[t] 长度
test('event markers count matches engine payload', () => {
  renderSlide(dayPayload);
  const dots = document.querySelectorAll('.chart-marker');
  expect(dots.length).toBe(dayPayload.events_by_trigger[currentTrigger].length);
});

// trigger 滑块拖动零网络
test('trigger slider switches client-side only', () => {
  const fetchSpy = jest.spyOn(window, 'fetch');
  setTrigger(14);                         // 用户拖动滑块到 14
  expect(dayPayload.zones.be['14']).toEqual(currentPnL);  // 直接读已加载 payload
  expect(fetchSpy).not.toHaveBeenCalled();                // AC-3 末条
});
```

---

## 5. 现有覆盖缺口识别（对照已有 11 单测）

| # | 缺口 | 说明 | 严重度 |
|---|------|------|--------|
| G1 | **long 方向 0 覆盖** | 11 测全 `short`；long 的 fill/stop/tp1/tp2/be_arm/be_out 镜像几何与符号全未验 | 🔴 P0 |
| G2 | **公共 API 未测** | `simulate_day`/`simulate_triggers` 从未被调用，只测 `_run`；origin/be 合并、events_all 选取、19 档循环未验 | 🔴 P0 |
| G3 | **无未来函数移位未实现** | 仅有 `ts_ms<=fcm` 必要条件；SRE §7.5 / PRD AC-1 要求的「as_of+1 天重算不变」缺失 | 🔴 P0 |
| G4 | **trigger 边界(8/26) 未测** | 仅测 20 与 None；边界 be_arm 阈值与循环端点未验 | 🟠 高 |
| G5 | **force_sl2 集成路径未测** | 仅「三区同触→休眠」+ 白盒；「2 区停、第 3 区幸存被强平」整链路未验 | 🟠 高 |
| G6 | **数据层 0 覆盖** | `compute_day_levels`/`fetch_day_1m` 显式排除；d==0→None、PAXG+12 量纲、DB→fapi 回退、BJ/UTC 日切未验 | 🟠 高 |
| G7 | **tz 互算未验** | `time(BJ)` 与 `ts_ms(UTC)` 一致性、22:30 BJ=14:30 UTC 未断言（AC-1 对账） | 🟠 高 |
| G8 | **golden-file 缺失** | 无「重放参考报告真实日 → 与报告吻合」的回归（SRE §2 已核对事实未固化） | 🟡 中 |
| G9 | **新增编排/前端 0 覆盖** | `_agg_1m_to_1h`、状态机、滑动组件、ECharts ≤3、视觉结构、API 全错误码均待建 | 🔴 P0（新增必测） |

> 既有 11 测已稳健覆盖 short 方向的 fill/stop/tp1/tp2/be_arm/be_out/force22/force_sl2(白盒)/SL 优先/确定性/K 系数/缺数据/无成交——**本计划不重复这些**，仅在其基础上补 G1~G9。

---

## 6. 测试优先级与 CI 门禁（对齐 AC-4 不二过）

**执行顺序（按风险降序）**
1. **P0（CI 卡死，阻断合并）**：A1 long 全分支、A2 公共 API 聚合、A3 无未来函数移位、B1 `_agg_1m_to_1h`、B2/B3 编排+状态机、E2 引擎一致性、E3 502、G1 视觉三件套（9 档/zone 带/事件计数）、H1 golden-file。
2. **P1**：A4 trigger 边界、A5 tz 互算、A6 force_sl2 集成、E1/E4/E5/E6/E7 路由合同、C3 trigger 滑块零网络、D1~D4 渲染映射。
3. **P2**：C1/C2/C4 滑动交互与 ECharts 生命周期、F 端到端视觉回归、G2/G3/G4/G5 性能与边界。

**CI 门禁**
- 单元测试（A/B 区）零网络零 DB，`pytest tests/ -q` 必须全绿。
- 新增 `tests/test_huntzone_gallery_*.py` 覆盖 B/C/D 区纯函数与结构。
- 集成测试 E 区用 `fastapi.TestClient` + mock，覆盖 5 类错误码。
- 前端：内联 JS 经 `node --check`；关键交互用 jsdom/Jest（C3、D5 示例）。
- 不二过：任何改动不得使既有 11 测或新增 P0 测回红；golden-file 抽样日固定冻结，防静默回归。

---

## 7. 与上游验收标准对齐矩阵

| PRD §7 / 设计 §11 | 本计划对应区域 | 验证手段 |
|-------------------|----------------|----------|
| **AC-1 数字可溯源 (P0)** | A2/A3/A5/B2/E2/H1 | 公共 API 一致性、移位不变式、tz 互算、引擎 1:1 对账、golden-file |
| **AC-2 视觉对齐 MT4** | D1~D5 / F1~F5 | 9 档阶梯、zone 色带、事件配色、视觉回归 |
| **AC-3 滑动流畅 (P0)** | C1~C4 / G1~G2 | 5 方式导航、≤300ms/≥50fps、ECharts ≤3、trigger 滑块零网络 |
| **AC-4 交付质量(不二过)** | §6 CI 门禁 / E3 红字 / G3 | `node --check`、无 Console 报错、纯新增、硬刷可见、502 红条 |
| **设计 §11 状态机** | B3 / G3 | ok/no_signal/missing/incomplete/live_only 不崩整列 |
| **设计 §11 无未来函数(P0)** | A3 / H1 | 移位不变式 + golden-file |
| **设计 §11 活跃 ECharts≤3** | C2 / G2 | IO 懒渲染生命周期断言 |
| **设计 §11 错误码消费** | E1~E7 / H2 | 200/400/429/502 + ok/reason/error 解析 |
| **SRE §5 缺数 502 红字** | E3 / H2 | 502 + 前端红色警告条 |
| **任务要求：滑动/转换/事件渲染单测** | C / D / B | 见 §2.3/2.4/2.2 |
| **任务要求：集成 200/502 红字/一致性** | E | 见 §2.5 |
| **任务要求：E2E 阶梯/zone/事件数** | F / D5 | 见 §2.6/2.4 |
| **任务要求：性能/边界 多slide/缺数/休市** | G | 见 §2.7 |
