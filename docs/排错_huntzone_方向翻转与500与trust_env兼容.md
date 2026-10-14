# 排错 · huntzone 方向翻转 + /huntv2 500 + 全页"无信号"

> 时间：2026-10-07 ~ 2026-10-09
> 范围：`huntzone-daily` / `huntzone-gallery` 两页 + `/api/huntv2/ladder` 接口
> 触发：用户报"2026-10-07 在画廊/每日页显示做多，但 hunting_system 官方卡是做空"，随后又报"bug 这么多"——附 `/huntv2` 500 日志 + 画廊/每日页"无信号"截图。

---

## 〇、结论先行

同一套 `fetch_daily_1d` 改动，先后埋下 **3 个独立根因**，导致两类现象：

| 现象 | 根因 | 层数 |
|---|---|---|
| 2026-10-07 显示**做多**（应为做空） | 日线数据源不同源：quant_review 用 Binance fapi  1d，官方卡用 Twelve Data XAU/USD spot D1 → 收盘价不同 → SMA10 翻转 | 数据层 |
| `/huntv2` 报 500 `ValueError: too many values to unpack` | 把 `fetch_daily_1d` 返回值从 2 元组升 3 元组时**漏改 `main.py:1347`** | 签名层 |
| 画廊"无有信号日" + 每日页"无信号/日线不足" | `requests.get(..., trust_env=False)` 在用户系统 Python 的 requests 版本里抛 `unexpected keyword argument 'trust_env'`，**Twelve Data 与 fapi 双双取数失败** | 依赖层 |

**元根因（最该不二过）**：测试环境（托管 venv，requests 较新）与生产环境（用户系统 Python `D:\sortware\python_3_10`，requests 较旧）不一致——pytest 全绿 + py_compile 全过，却只在用户机器上炸。

---

## 一、现象与排查路径

### 阶段 1：方向翻转（做多 vs 做空）
- 用户贴图：画廊/每日页把 2026-10-07 显示成**做多**，而 `hunting_system/daily_push.py` 官方卡为**做空**（昨收 4169.39 < SMA10 4193.19）。
- 第一直觉（错误）：公式错 / 前端反转 / 旧缓存。
- 验证公式：本地用官方卡数字喂 `hz_engine.trend_direction(4169.39, 4193.19)` → −1 → 做空。公式**字节级一致**，前端模板仅按 `direction` 渲染，无反转。
- 查 `hunting_system/daily_push.py` 的 `fetch_d1`：用的是 **Twelve Data XAU/USD spot D1**（`timezone=America/New_York`、剔除周末伪 bar）。
- 查 `huntv2_core.fetch_daily_1d` 旧实现：用的是 **Binance fapi  1d**（UTC 00:00、7 天永续、含周末、带基差）。
- **结论：不是公式/缓存，是喂给公式的日线历史不同源** → SMA10 翻转。

### 阶段 2：500 + 全页无信号
- 用户贴 uvicorn 日志：`/api/huntv2/ladder?live=1` 反复 500，`main.py:1347 rows, err = hc.fetch_daily_1d()` `ValueError: too many values to unpack (expected 2)`。
- grep 全仓 `fetch_daily_1d` 调用点，发现漏改 2 处 + 1 处测试 monkeypatch：
  - `main.py:1347` `/api/huntv2/ladder`（2 元组解包）
  - `huntzone_daily_core.py:60` `_recompute_direction`（2 元组解包，被 try/except 吞掉 → 诊断返回 ok=False）
  - `tests/test_huntzone_daily.py:96`（返回 2 元组）
- 改完上述 3 处后，画廊/每日页**仍**显示"无信号"。说明还有更深的根因。
- 本地用**用户系统 Python** 直接调 `fetch_daily_1d`：
  ```
  source= None
  err= twelvedata: Session.request() got an unexpected keyword argument 'trust_env';
       fapi: Session.request() got an unexpected keyword argument 'trust_env'
  rows count= 0
  ```
- **真因锁定**：`requests.get(url, ..., trust_env=False)` 在旧版 requests 里不是合法关键字参数 → Twelve Data 与 fapi 都抛 `TypeError` → 取数全失败 → 所有依赖日线的页面"无信号"。

---

## 二、三处根因与修复

### 根因 1 · 数据源不同源（方向翻转）
**修复**：`huntv2_core.fetch_daily_1d` 改为**优先 Twelve Data XAU/USD spot D1**（与官方卡同源：
API key（来自环境变量 `TWELVE_KEY`，见 `.env.example`）、symbol `XAU/USD`、timezone `America/New_York`、
lookback 130 天、剔除 Sat/Sun 伪 bar），失败再回退 fapi 。返回由 2 元组升 **3 元组** `(rows, err, source)`。
新增 `_fetch_twelve_daily()` / `_date_to_ms()`。`huntback_sim.compute_day_levels` 与
`huntzone_gallery_core.list_recent_signal_days` 同步解包 3 元组。`hunting_system` 代码**零改动**。

### 根因 2 · 3 元组漏改调用点（500）
**修复**：
- `main.py:1347`：`rows, err, source = hc.fetch_daily_1d()` 且 `compute_ladder(rows, source=source)`；502 返回体补 `source`。
- `huntzone_daily_core.py:60`：`rows, err, _source = fetch_daily_1d(...)`。
- `tests/test_huntzone_daily.py:96`：monkeypatch 返回 `(_fake_daily_rows(), None, "fapi")`。

### 根因 3 · `trust_env=False` 兼容性（全页无信号）
**修复**：新增 `_requests_get(url, proxies, timeout)`，内部用 `requests.Session()` + `session.trust_env = False`
**替代** `requests.get(..., trust_env=False)` 关键字写法；`_fapi_fetch()` 与 `_fetch_twelve_daily()` 统一调用它。
`trust_env` 是 **Session 属性**，不是 request 级关键字参数——这是跨版本安全写法。

---

## 三、验证（用户系统 Python `D:\sortware\python_3_10\python.exe` 实测）

```
fetch_daily_1d()                         → source=twelvedata, 94 根, err=None
compute_day_levels('2026-10-07')         → direction=short/做空, source=twelvedata,
                                            open=4169.13593, S=63.595,
                                            zone=4193.43~4208.44, prev_close=4169.38893
list_recent_signal_days(n=10, span=60)   → ['2026-10-09','2026-10-08','2026-10-07',...,'2026-09-30']
build_daily_view('2026-10-07')           → missing=False, direction=short, diag_direction=short
api_huntv2_ladder()                      → status=200, ok=True, direction=short,
                                            source='twelvedata XAU/USD 1d（已收盘）'
pytest (托管 venv)                         → 24 passed
py_compile (系统 Python)                   → 全过
```

2026-10-07 的方向、档位与官方卡逐位对齐（leg 4232.73 / stop 4220.58 / zone 4193.43~4208.44 / open 4169.14 / exh1 4129.83）。

---

## 四、经验沉淀（不二过铁律补充）

1. **改函数签名 → 先全仓 grep 调用点，再动手。**
   把 `fetch_daily_1d` 返回值 2→3 元组时，必须一次性找出全部调用点（`main.py` / `huntzone_daily_core.py` /
   `huntzone_gallery_core.py` / `huntback_sim.py` / 测试 monkeypatch），改完 `grep fetch_daily_1d` 数一遍确认全覆盖。
   **少一个调用点 = 一个线上 500。**

2. **测试环境必须 == 生产环境。**
   托管 venv 的 requests 较新，`requests.get(trust_env=False)` 不报错；用户系统 Python 的 requests 较旧，直接 `TypeError`。
   **凡依赖第三方库的行为差异，必须用用户实际运行的那套 Python 跑一遍真实调用**，不能只信 pytest/py_compile。

3. **`trust_env` 永远用 Session 写法。**
   `session = requests.Session(); session.trust_env = False; session.get(url, proxies=...)`。
   绝不写 `requests.get(url, trust_env=False)`——它只在较新 requests 生效，旧版直接崩。
   （与项目"零代理"纪律一致：显式 `trust_env=False` 拒绝环境代理，仍是纪律的正确实现，只是写法要兼容。）

4. **数据相关 bug 先 curl/直调数据源，再怀疑公式。**
   本次方向翻转，公式从一开始就被证明正确，真因在数据源。下次遇到"值不对"，第一步应是
   **直接打取数函数看返回的行数/收盘价/时间戳**，而不是反复改下游逻辑或前端。

5. **取数失败要"显式报错"，不要静默降级成"无信号"。**
   之前 `fetch_daily_1d` 两路都失败返回 `(None, err, None)`，上层把"取数失败"和"真无信号"混为一谈，
   掩盖了真实错误。应让 API 层区分 502（取数失败）与 200+ok:False（真无信号），并把 `source`/`err` 透出到响应体便于排错。

---

## 五、受影响文件清单

| 文件 | 改动 |
|---|---|
| `huntv2_core.py` | `fetch_daily_1d` → 3 元组；新增 `_requests_get`；`_fetch_twelve_daily` / `_date_to_ms`；`compute_ladder` 接 source |
| `huntback_sim.py` | `compute_day_levels` 解包 3 元组 + 落 `daily_source` |
| `huntzone_gallery_core.py` | `list_recent_signal_days` 解包 3 元组 |
| `huntzone_daily_core.py` | `_recompute_direction` 解包 3 元组 |
| `main.py` | `api_huntv2_ladder` 解包 3 元组 + 传 source + 502 透出 source |
| `tests/test_huntzone_daily.py` | monkeypatch 返回 3 元组 |

> 全程未改动 `hunting_system/` 任何代码；方向公式与官方卡字节级一致。
