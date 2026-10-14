# -*- coding: utf-8 -*-
"""狩猎区画廊（/huntzone-gallery）编排层。

纯新增，零修改既有引擎 / 页面。复用（import，不改）：
  - huntback_sim.compute_day_levels / fetch_day_1m / simulate_day
  - huntback_sim 的私有时间/趋势原语（_date_to_open_ms / trend_series / trend_direction /
    Config / build / predict_S / S_MODEL_FROZEN）—— 仅 import，不改动。
  - hz_engine.build 几何正解。

红线（与 M1 引擎一致）：
  - 严格因果、零未来函数：档位只用 ≤D-open 已收盘数据；模拟按 1m bar 升序前向扫描。
  - 1m→1h 聚合只用已逝 bar（按 UTC 整点分桶），无 look-ahead。
  - 取数失败 / 无信号 → 明确返回 missing:True，绝不猜 S、绝不静默填数。
"""
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta

from huntzone import huntback_sim as hs
from huntzone.huntback_sim import (
    _date_to_open_ms, trend_series, trend_direction, Config,
    predict_S, S_MODEL_FROZEN, build as _hz_build,
)

DEFAULT_TRIGGER = 20
ZONE_TAGS = ("zone_a", "zone_mid", "zone_b")
UTC = timezone.utc

# 画廊展示用 9 档（4.236 过远不展示；0.809 可选展示）。集合用于过滤 build().levels。
_GALLERY_RATIO_SET = {0.0, 0.191, 0.382, 0.500, 0.618, 0.809, 1.000, 1.618, 2.618}
_GALLERY_RATIO_ORDER = (0.0, 0.191, 0.382, 0.500, 0.618, 0.809, 1.000, 1.618, 2.618)

# L1 缓存：key = (date, trigger, symbol, with_1m) -> slide dict
_CACHE: Dict[tuple, dict] = {}


GALLERY_SCHEMA = {
    "slide": {
        "date": "str YYYY-MM-DD（UTC 自然日）",
        "missing": "bool；为 True 时只剩 date/reason，前端展示灰卡",
        "reason": "str 缺失原因（missing=True 时）",
        "direction": "'short' | 'long'",
        "direction_cn": "做空 / 做多",
        "source": "'local' | 'fapi'（1m 数据源）",
        "open_px": "float 当日开盘价 = 100.0 档",
        "S": "float 跨度",
        "S_mae": "float S 预测 MAE（低置信度）",
        "trigger": "int 保本触发点",
        "levels": "[{ratio,name,price}] 9 档展示用",
        "zone_lo/zone_hi/zone_mid": "float 狩猎区价格边界",
        "stop/exh1/exh2/t1": "float 关键档位价",
        "zone_band": "{lo,hi,color} color=green(多)/pink(空)",
        "candles_1h": "[[ts_ms,o,h,l,c],...] 1m→1h 聚合（无 1m 细部）",
        "candles_1m": "[[ts_ms,o,h,l,c],...] 仅 with_1m=True 时返回",
        "events": "[{tag,type,time,ts_ms,price,note,zone}] 最多 8 个事件 marker",
        "zones_pnl": "{zone_a/zone_mid/zone_b:{origin,be}} USD",
        "total": "{origin,be} USD",
        "outcome": "盈利 / 亏损 / 持平",
        "special_gap": "bool 跳空特殊日",
    },
    "range": {
        "trigger": "int", "symbol": "str",
        "dates": "[str] 实际入列（非缺失）的日期列表",
        "slides": "[slide]", "count": "int", "missing_count": "int",
    },
}


# ----------------------------------------------------------------------------
# 时间枚举（纯计算，不触网）
# ----------------------------------------------------------------------------
def _iter_recent_dates(n: int = 60, end_date: Optional[str] = None) -> List[str]:
    """最近 n 个 UTC 自然日，降序（今日在首）。"""
    if end_date:
        end_dt = datetime.fromtimestamp(_date_to_open_ms(end_date) / 1000, tz=UTC)
    else:
        end_dt = datetime.now(UTC)
    out = []
    for i in range(n):
        out.append((end_dt - timedelta(days=i)).strftime("%Y-%m-%d"))
    return out


def _iter_dates_range(start: str, end: str) -> List[str]:
    """[start, end] 闭区间所有自然日，升序。"""
    s = _date_to_open_ms(start)
    e = _date_to_open_ms(end)
    if e < s:
        s, e = e, s
    out = []
    cur = datetime.fromtimestamp(s / 1000, tz=UTC)
    end_dt = datetime.fromtimestamp(e / 1000, tz=UTC)
    while cur <= end_dt:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


# ----------------------------------------------------------------------------
# 1m → 1h 纯聚合（按 UTC 整点分桶；只用已逝 bar，无未来函数）
# ----------------------------------------------------------------------------
def _agg_1m_to_1h(bars_1m) -> List[List[float]]:
    if not bars_1m:
        return []
    buckets: Dict[int, List[float]] = {}
    order: List[int] = []
    for b in bars_1m:
        ts, o, h, l, c = b[0], b[1], b[2], b[3], b[4]
        hour_start = ts - (ts % 3600000)
        if hour_start not in buckets:
            buckets[hour_start] = [o, h, l, c]
            order.append(hour_start)
        else:
            bu = buckets[hour_start]
            bu[1] = max(bu[1], h)
            bu[2] = min(bu[2], l)
            bu[3] = c
    return [[hs0, buckets[hs0][0], buckets[hs0][1],
             buckets[hs0][2], buckets[hs0][3]] for hs0 in order]


# ----------------------------------------------------------------------------
# 批量档位（一次取数复用，避免逐日 60× 触网）
# ----------------------------------------------------------------------------
def _levels_from_rows(rows, date: str, symbol: str = ""):
    """复刻 huntback_sim.compute_day_levels 的本地计算（复用已取 rows，不重复触网）。
    严格对齐 ADR-4：关 ma3/vol，仅 SMA10 顺势符号 + 冻结 S。"""
    d_open_ms = _date_to_open_ms(date)
    day_bars = []
    for r in rows:
        ts = int(r[0])
        if ts <= d_open_ms:                       # 含 D 当日（已收盘）
            day_bars.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    day_bars = sorted(day_bars, key=lambda b: b[0])
    if len(day_bars) < 7:
        return None
    today = day_bars[-1]
    prev_bar = day_bars[-2]
    prev_history = day_bars[:-1]
    cfg = Config(trend_period=10, trend_mode="sma", trend_filter="", vol_filter=0.0)
    ma = trend_series(prev_history, cfg.trend_period, cfg.trend_mode)
    prev_close = prev_bar[4]
    d = trend_direction(prev_close, ma[-1])
    if d == 0:
        return None
    direction = "short" if d == -1 else "long"
    S, _b1, _p1 = predict_S(S_MODEL_FROZEN, prev_bar)
    lad = _hz_build(today[1], S, direction, prev_close=prev_close)
    lad["mae"] = S_MODEL_FROZEN["loo_mae"]
    return lad


def list_recent_signal_days(symbol: str = "", n: int = 30, span: int = 120) -> List[str]:
    """枚举最近 span 天中、有信号（方向非临界 / 数据足够）的降序日期，最多 n 个。
    取数失败 → 返回空列表（前端明确报错，绝不猜 S）。"""
    from huntzone.huntv2_core import fetch_daily_1d
    rows, err, _source = fetch_daily_1d(symbol, limit=span)
    if err or not rows:
        return []
    rows = sorted(rows, key=lambda r: int(r[0]))
    out = []
    for d in _iter_recent_dates(span):
        lad = _levels_from_rows(rows, d, symbol)
        if lad is not None:
            out.append(d)
            if len(out) >= n:
                break
    return out


# ----------------------------------------------------------------------------
# 单日 slide
# ----------------------------------------------------------------------------
def build_gallery_day(date: str, trigger: int = DEFAULT_TRIGGER,
                      symbol: str = "", with_1m: bool = False) -> dict:
    """构建单日画廊 slide（见 GALLERY_SCHEMA）。L1 缓存。"""
    key = (date, int(trigger), symbol, bool(with_1m))
    if key in _CACHE:
        return _CACHE[key]

    lad = hs.compute_day_levels(date, symbol)
    if lad is None:
        slide = {"date": date, "missing": True,
                 "reason": "无信号（方向临界 / 日线不足）"}
        _CACHE[key] = slide
        return slide

    bars_1m, source, missing = hs.fetch_day_1m(date, symbol)
    if missing or not bars_1m:
        slide = {"date": date, "missing": True,
                 "direction": lad.get("direction"),
                 "reason": "1m 数据缺失（取数失败）"}
        _CACHE[key] = slide
        return slide

    sim = hs.simulate_day(lad, bars_1m, int(trigger), symbol=symbol)
    be = sim["be"][str(int(trigger))]
    direction = lad.get("direction")

    ladder_9 = []
    for r in _GALLERY_RATIO_ORDER:
        for lv in lad["levels"]:
            if abs(round(lv["ratio"], 3) - round(r, 3)) < 1e-9:
                ladder_9.append({"ratio": lv["ratio"], "name": lv["name"],
                                 "price": round(float(lv["price"]), 2)})
                break

    events = []
    for ev in (sim.get("events_all") or [])[:8]:
        events.append({
            "tag": ev.tag, "type": ev.type, "time": ev.time,
            "ts_ms": ev.ts_ms, "price": round(float(ev.price), 2),
            "note": ev.note, "zone": ev.tag,
        })

    zones_pnl = {}
    for t in ZONE_TAGS:
        zones_pnl[t] = {
            "origin": round(float(sim["origin"]["zones"][t]), 2),
            "be": round(float(be["zones"][t]), 2),
        }
    total = {
        "origin": round(float(sim["origin"]["realized_usd"]), 2),
        "be": round(float(be["realized_usd"]), 2),
    }

    slide = {
        "date": date,
        "missing": False,
        "direction": direction,
        "direction_cn": lad.get("direction_cn", "做空" if direction == "short" else "做多"),
        "source": source,
        "open_px": round(float(lad.get("open_px")), 2),
        "S": round(float(lad.get("S")), 2),
        "S_mae": round(float(lad.get("mae", 0)), 2),
        "trigger": int(trigger),
        "levels": ladder_9,
        "zone_lo": round(float(lad.get("zone_lo")), 2),
        "zone_hi": round(float(lad.get("zone_hi")), 2),
        "zone_mid": round(float(lad.get("zone_mid")), 2),
        "stop": round(float(lad.get("stop")), 2),
        "exh1": round(float(lad.get("exh1")), 2),
        "exh2": round(float(lad.get("exh2")), 2),
        "t1": (round(float(lad["t1"]), 2) if lad.get("t1") is not None else None),
        "zone_band": {
            "lo": round(float(lad.get("zone_lo")), 2),
            "hi": round(float(lad.get("zone_hi")), 2),
            "color": "green" if direction == "long" else "pink",
        },
        "candles_1h": _agg_1m_to_1h(bars_1m),
        "events": events,
        "zones_pnl": zones_pnl,
        "total": total,
        "outcome": sim.get("outcome"),
        "special_gap": bool(lad.get("special_gap", False)),
    }
    if with_1m:
        slide["candles_1m"] = [[b[0], round(b[1], 2), round(b[2], 2),
                                round(b[3], 2), round(b[4], 2)] for b in bars_1m]
    _CACHE[key] = slide
    return slide


# ----------------------------------------------------------------------------
# 多日 range
# ----------------------------------------------------------------------------
def build_gallery_range(start: Optional[str] = None, end: Optional[str] = None,
                        trigger: int = DEFAULT_TRIGGER, symbol: str = "",
                        max_days: int = 60) -> dict:
    """构建画廊 range（多日 slide 列表）。

    - start/end 给定：遍历闭区间内每天，有信号且数据可取者入列；
    - 均空：默认最近 30 个有信号日（list_recent_signal_days）。
    missing 日不进 slides（灰卡不占轮播位），但计入 missing_count。
    """
    if start and end:
        dates = _iter_dates_range(start, end)
    else:
        dates = list_recent_signal_days(symbol, n=30, span=120)

    slides = []
    missing_count = 0
    for d in dates[:max_days]:
        s = build_gallery_day(d, trigger, symbol, with_1m=False)
        if s.get("missing"):
            missing_count += 1
        else:
            slides.append(s)

    return {
        "trigger": int(trigger),
        "symbol": symbol,
        "dates": [s["date"] for s in slides],
        "slides": slides,
        "count": len(slides),
        "missing_count": missing_count,
    }


def clear_cache() -> None:
    """清空 L1 缓存（调试 / 数据刷新后）。"""
    _CACHE.clear()
