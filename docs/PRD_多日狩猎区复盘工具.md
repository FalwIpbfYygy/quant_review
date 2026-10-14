# PRD · 多日狩猎区复盘工具

> 版本：V1.0（待评审）
> 日期：2026-10-09
> 范围：quant_review 新增页面 `/huntzone-review` + 后端 API
> 约束：纯新增，不修改 `<HUNTING_SYSTEM_PATH>/` 任何代码；复用其狩猎区计算逻辑。

---

## 一、需求摘要

构建一个**多日连续复盘页**，以固定 **30 分钟 K 线**为时间精度，把每一天的狩猎区关键价位区域（腿端/止损/狩猎区/衰竭位）叠加在 K 线图上，支持连续滚动查看多天，并可通过日期范围切换和滑动条快速定位任意一天。

| 功能点 | 说明 |
|---|---|
| 多日连续展示 | 单张 ECharts 图横向连续展示 N 天 30m K 线，每天狩猎区以水平带/线叠加 |
| 固定 30m 级别 | 每根 K 线固定 30 分钟，不随页面缩放改变周期 |
| 日期范围切换 | 快捷按钮「最近 3 个交易日」「最近 7 个交易日」+ 自定义起止日期 |
| 滑动条浏览 | 底部滑动条按日期刻度拖动，点击/拖动快速定位到某一天并高亮其狩猎区 |
| 数据来源 | 30m K 线由 quant_review 本地 1m 库聚合；狩猎区逻辑复用 `hunting_system/hunting_zone` |

---

## 二、狩猎区逻辑口径（与 hunting_system 严格对齐）

复用 `<HUNTING_SYSTEM_PATH>/hunting_zone` 的以下原语，保证与官方卡字节级一致：

1. **日线数据**：Twelve Data XAU/USD spot D1，`timezone=America/New_York`，剔除周末伪 bar。
   - quant_review 现有 `huntv2_core.fetch_daily_1d()` 已实现同源取数（Twelve Data 优先，回退 fapi）。
2. **方向**：`trend_direction(prev_close, SMA10)`，其中 `prev_close = bars[-2].close`，`SMA10 = trend_series(bars[:-1], 10, 'sma')[-1]`。
3. **跨度 S**：`predict_S(S_MODEL_FROZEN, prev_bar)`，使用冻结系数：
   - `a=45.555`, `b1=0.411`, `b2=7.803`, `s_min=36.21`, `s_max=117.63`, `loo_mae=21.95`。
4. **档位**：`build(open_px, S, direction, prev_close=prev_close)`。
   - 0.0 档 = 腿端/失效线
   - 19.1 档 = 止损
   - [38.2, 61.8] = 狩猎区（半透明色带）
   - 50.0 档 = 区中
   - 100.0 档 = 当日开盘价（锚）
   - 161.8 / 261.8 = 衰竭① / 衰竭②
   - 目标① = 昨收（跳空日 skip）

**复用方式（待你拍板）**：
- **方案 A（推荐）**：`sys.path.insert(0, r'<HUNTING_SYSTEM_PATH>')` 后直接 `from hunting_zone.engine import build, trend_series, trend_direction, Config` 和 `from hunting_zone.signal import S_MODEL_FROZEN, predict_S`。
- **方案 B**：把 `engine.py` / `signal.py` 的核心函数/常量复制一份到 quant_review 内（例如 `hz_engine.py` 已存在大部分，只需补 `S_MODEL_FROZEN` 与 `predict_S`）。

> 建议方案 A，完全复用原逻辑、避免漂移；但会在 quant_review 中引入对外部 Downloads 路径的依赖。若你担心服务器部署路径不同，可选方案 B。

---

## 三、页面与路由

| 项 | 内容 |
|---|---|
| 页面路由 | `/huntzone-review` |
| API | `GET /api/huntzone-review/data?start=YYYY-MM-DD&end=YYYY-MM-DD` |
| 入口 | `topnav-bar` 新增导航项「狩猎区复盘」，排在「狩猎区画廊」右侧（纯新增，不改既有页面入口顺序） |
| 技术栈 | FastAPI + 内联 HTML + Vue3 + ECharts（与现有 `/huntzone-daily` / `/huntzone-gallery` 一致） |

---

## 四、后端 API 设计

### `GET /api/huntzone-review/data`

**参数**：
- `start`：起始日期 `YYYY-MM-DD`
- `end`：结束日期 `YYYY-MM-DD`

**成功返回 200**：
```json
{
  "range": {"start": "2026-10-01", "end": "2026-10-07"},
  "bars_30m": [
    {"ts": "2026-10-01 00:00", "o": 4165.0, "h": 4170.0, "l": 4162.0, "c": 4168.0},
    ...
  ],
  "days": [
    {
      "date": "2026-10-07",
      "direction": "short",
      "direction_cn": "做空",
      "open_px": 4169.14,
      "S": 63.60,
      "sma10": 4193.19,
      "prev_close": 4169.39,
      "source": "twelvedata",
      "levels": {
        "leg_start": 4232.73,
        "stop": 4220.58,
        "zone_lo": 4193.43,
        "zone_hi": 4208.44,
        "zone_mid": 4200.94,
        "exh1": 4129.83,
        "exh2": 4066.24,
        "t1": 4169.39
      }
    }
  ],
  "missing_days": ["2026-10-05"]
}
```

**字段说明**：
- `bars_30m`：覆盖 `[start 00:00 UTC, end+1 00:00 UTC)` 的全部 30m K 线。
- `days`：每一天 D1 计算出的狩猎区；方向临界/数据不足/周末的日子不进入此数组。
- `missing_days`：日期在范围内但无信号（direction=0 或数据不足），前端仍画 K 线但不画色带。

**错误返回**：
- 502：`fetch_daily_1d` 取数失败 → `{code:502, error:"...", source:null}`
- 400：start > end 或日期格式非法 → `{code:400, error:"..."}`

---

## 五、前端设计

### 5.1 布局（自上而下）

```
┌─────────────────────────────────────────────────────────────┐
│ 标题：多日狩猎区复盘 · 30m                                  │
├─────────────────────────────────────────────────────────────┤
│ 控制栏： [最近3日] [最近7日]  起始日 [____] 结束日 [____]   │
├─────────────────────────────────────────────────────────────┤
│ 信息卡：聚焦日 2026-10-07 ｜ 做空 ｜ 开 4169.14 ｜ S 63.60  │
│        狩猎区 4193.43~4208.44 ｜ 止损 4220.58 ｜ 衰竭① ...  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                    ECharts 30m K 线图                        │
│         （紫色/绿色水平色带 = 当日狩猎区）                   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ 滑动条：◄══●═══════════════════════════════════════►       │
│        10-01  10-02  10-03  10-04  [10-05]  10-06  10-07    │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 图表绘制规范

**K 线**：
- 30m 蜡烛，颜色按 A 股惯例：**红涨绿跌**（涨 = 收盘 > 开盘，红色；跌 = 收盘 < 开盘，绿色）。
- x 轴为时间，按 UTC 展示；tooltip 同时显示北京时间。

**日界分隔**：
- 每天 00:00 UTC（北京 08:00）处画一条浅灰色垂直虚线，并标注日期 `MM-DD`。

**狩猎区价位层**：
- 对 `days` 中每一天，在其 00:00~24:00 时间区间内绘制水平元素：

| 元素 | 图形 | 颜色 | 标签 |
|---|---|---|---|
| 狩猎区 [zone_lo, zone_hi] | 半透明水平带状（矩形 markArea） | 做空=紫色 `#c2185b` / 做多=绿色 `#388e3c` | 38.2 / 61.8 |
| 止损 stop | 虚线 | 做空=深紫 `#880e4f` / 做多=深绿 `#1b5e20` | 19.1 |
| 腿端 leg_start | 点划线 | 同方向深色 | 0.0 |
| 区中 zone_mid | 实线 | 同方向中色 | 50.0 |
| 衰竭① exh1 | 实线 | 灰色/棕色 | 161.8 |
| 衰竭② exh2 | 实线 | 灰色/棕色 | 261.8 |
| 目标① t1 | 短划线（仅在非跳空日） | 蓝色 | t1 |

> 与截图一致：紫/绿带表示当日狩猎区，黑色/灰色细线表示各档位。ECharts 用 `markLine` + `markArea` 实现。

**聚焦日高亮**：
- 滑动条/点击选中的日期，其狩猎区色带透明度加浓、边框加粗；其他日期色带变淡。
- 信息卡同步显示该日 `direction_cn` / `open_px` / `S` / 各关键价位。

---

## 六、日期范围与滑动条

### 6.1 快捷选项

| 按钮 | 含义 |
|---|---|
| 最近 3 个交易日 | 从今天倒推 3 个交易日（跳过周末、无数据日），end=最近交易日，start=前 2 个交易日 |
| 最近 7 个交易日 | 同上，取 7 个交易日 |
| 自定义 | 用户手动选择 start / end |

### 6.2 滑动条

- 刻度：范围内每个交易日一个点（跳过周末/无数据日）。
- 拖动/点击：改变「聚焦日」，图表自动横向滚动到该日居中，并高亮该日狩猎区。
- 键盘支持：← → 方向键按日切换聚焦日。

---

## 七、数据流程

```
1. 用户选择范围 → 前端调 GET /api/huntzone-review/data?start=&end=
2. 后端：
   a. 取 [start, end+1] 区间内 30m K 线（本地 kline_1m 聚合，纯规则、无未来函数）
   b. 对范围内每个交易日 D：
      - 调用 huntv2_core.fetch_daily_1d() 获取 D1 spot 序列
      - 用 hunting_zone.engine/signal 计算 D 的狩猎区
      - 生成 levels + direction
3. 后端返回 {bars_30m, days, missing_days}
4. 前端 ECharts 绘制 K 线 + markArea/markLine 叠加狩猎区
```

**聚合规则（1m → 30m）**：
- 按 UTC 30 分钟桶聚合：`bucket_ts = open_time // 1800000 * 1800000`。
- open=桶首 open，high=max，low=min，close=桶末 close。
- 严格因果：只用已收盘 1m bar，不向前看。

---

## 八、性能与缓存

- 30m 数据密度：7 天 × 48 根 = 336 根；30 天 ≈ 1440 根。ECharts 完全可承受。
- 自定义范围上限建议 **30 个交易日**，前端/后端均可做硬限制。
- 后端可加短期内存缓存：key = `(start, end)`，TTL 60 秒；D1 信号也可按日缓存。

---

## 九、边界与异常

| 场景 | 处理 |
|---|---|
| 某交易日方向临界（d=0） | 不进入 `days`，仅进入 `missing_days`；仍画 K 线 |
| 某交易日 D1 取数失败 | `missing_days` 标记 `"data_error"`，前端提示但不阻塞其他日期 |
| 本地 1m 数据缺某段 | 30m 图在该段留空（不补 fapi，避免复盘时引入未来数据） |
| 日期跨周末 | 周末无 D1/30m 数据，自动跳过；滑动条只显示交易日 |
| start > end | 400 错误 |
| 范围超过 30 个交易日 | 400 错误，提示缩小范围 |

---

## 十、不改动范围

- 不修改 `<HUNTING_SYSTEM_PATH>/` 任何文件。
- 不修改既有 `/huntzone-daily`、`/huntzone-gallery`、`/huntv2` 页面的核心逻辑。
- 不修改 `huntback_sim.py`、`huntzone_gallery_core.py`、`huntzone_daily_core.py` 的已有功能。
- 新增页面所需的 topnav 条目，仅扩展 `topnav.js` 的导航数组。

---

## 十一、待确认项（需要你拍板）

1. **复用方式**：方案 A（直接 import `Downloads/hunting_system/hunting_zone`）还是方案 B（复制函数到 quant_review）？
2. **页面路由**：`/huntzone-review` 是否可以？还是希望 `/huntzone-multi` / `/huntzone-30m-review`？
3. **快捷按钮**：「最近 3 个交易日」「最近 7 个交易日」是否满足？是否需要「最近 14 日」或「本月」？
4. **自定义上限**：最大允许选多少个交易日？建议 30。
5. **是否需要在图表上显示成交量**？截图未见成交量，默认不加。
6. **是否需要点击某根 30m K 线后显示该 30m 的 OHLC 详情**？默认 tooltip 已含。

---

## 十二、后续开发计划（PRD 通过后再执行）

1. 新建 `huntzone_review_core.py`：计算多日数据、30m 聚合、调用 hunting_system 逻辑。
2. 在 `main.py` 新增 `/api/huntzone-review/data` 与 `/huntzone-review` 路由。
3. 新增内联 HTML 页面模板（Vue3 + ECharts）。
4. 扩展 `topnav.js` 导航。
5. 编写临时自检脚本（mock 日线 + 30m 数据），验证聚合、档位计算、API 响应、图表 markArea 坐标。
6. 用户确认后删除临时脚本（零垃圾）。

---

## 十三、验收标准

- [ ] `/huntzone-review` 页面能打开，显示多日 30m K 线。
- [ ] 2026-10-07 显示做空，狩猎区 4193.43~4208.44，与官方卡一致。
- [ ] 切换「最近 3 日/7 日/自定义」后图表与滑动条同步更新。
- [ ] 拖动滑动条，聚焦日高亮，信息卡同步更新。
- [ ] 周末/无信号日被跳过或正确留空，不报错。
- [ ] pytest 新增用例全过；`py_compile` 全过。
