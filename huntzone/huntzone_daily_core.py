# -*- coding: utf-8 -*-
"""狩猎区每日效果图（/huntzone-daily）编排层。

纯新增，零改既有引擎/页面。复用 huntback_sim.compute_day_levels / fetch_day_1m（零改）。
只返回最简单的：30m K线 + 9档阶梯线 + 狩猎区色带 + 方向。
不计算持仓、挂单、止盈止损、事件、P&L。

纪律：零未来函数；30m 聚合只用已逝 1m bar；取数失败/无信号 → missing:True，绝不猜 S。

方向口径（与 hunting_system/hunting_zone/signal.generate_self_sufficient 完全一致）：
  sign(昨收 − SMA10(收盘,10))；>0 多 / <0 空 / 0 无。
  prev_close = day_bars[-2]（D 的前一根），SMA10 取 prev_history=day_bars[:-1] 末 10 根收盘均值，
  day_bars = fapi  1d 中 open_time <= D 开盘的已收盘日线。
为便于在服务器上核对「本页方向是否与该项目的官方卡一致」，额外暴露 _recompute_direction
（独立复算同一口径），返回 prev_close / sma10 / sign / 复算方向。
"""
from typing import List, Dict, Optional

from huntzone import huntback_sim as hs
from huntzone.hz_engine import trend_series, trend_direction, Config


# 画廊展示用 9 档（4.236 过远不展示）
_GALLERY_RATIO_ORDER = (0.0, 0.191, 0.382, 0.500, 0.618, 0.809, 1.000, 1.618, 2.618)


def _agg_1m_to_30m(bars_1m) -> List[List[float]]:
    """纯聚合：1m → 30m（按 UTC 30 分钟分桶）。无 look-ahead。"""
    if not bars_1m:
        return []
    buckets: Dict[int, List[float]] = {}
    order: List[int] = []
    for b in bars_1m:
        ts, o, h, l, c = b[0], b[1], b[2], b[3], b[4]
        bucket_start = ts - (ts % (30 * 60000))
        if bucket_start not in buckets:
            buckets[bucket_start] = [o, h, l, c]
            order.append(bucket_start)
        else:
            bu = buckets[bucket_start]
            bu[1] = max(bu[1], h)
            bu[2] = min(bu[2], l)
            bu[3] = c
    return [[b0, buckets[b0][0], buckets[b0][1], buckets[b0][2], buckets[b0][3]] for b0 in order]


def _recompute_direction(date: str, symbol: str = "") -> dict:
    """独立复算顺势方向（与 hunting_system.generate_self_sufficient 同口径）。

    用于核对：本页方向是否与该项目的官方卡一致。best-effort：
    导入/取数/计算任一异常都返回 ok:False，绝不抛错、绝不影响主流程。
    返回 {ok, prev_close, sma10, sign(-1空/1多/0临界), direction, open_px, reason}。
    """
    try:
        from huntzone.huntv2_core import fetch_daily_1d
        from huntzone.huntback_sim import _date_to_open_ms
    except Exception as e:
        return {"ok": False, "reason": "导入失败: %s" % e}
    try:
        rows, err, _source = fetch_daily_1d(symbol, limit=90)
    except Exception as e:
        return {"ok": False, "reason": "取数异常: %s" % e}
    if err or not rows:
        return {"ok": False, "reason": err or "无日线"}
    try:
        d_open_ms = _date_to_open_ms(date)
        day_bars = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
                    for r in rows if int(r[0]) <= d_open_ms]
        day_bars.sort(key=lambda b: b[0])
        if len(day_bars) < 7:
            return {"ok": False, "reason": "日线不足(<7)"}
        today = day_bars[-1]
        prev_bar = day_bars[-2]                # D 的前一根 = 昨日完整 bar
        prev_history = day_bars[:-1]           # 不含 D（进行中/已收盘）
        cfg = Config(trend_period=10, trend_mode="sma", trend_filter="", vol_filter=0.0)
        ma = trend_series(prev_history, cfg.trend_period, cfg.trend_mode)
        prev_close = prev_bar[4]
        sma10 = ma[-1]
        d = trend_direction(prev_close, sma10)
        direction = "short" if d == -1 else "long"
        return {
            "ok": True,
            "prev_close": round(float(prev_close), 2),
            "sma10": round(float(sma10), 2) if sma10 is not None else None,
            "sign": d,
            "direction": direction,
            "open_px": round(float(today[1]), 2),
        }
    except Exception as e:
        return {"ok": False, "reason": "复算异常: %s" % e}


def build_daily_view(date: str, symbol: str = "") -> dict:
    """返回单日 30m 狩猎区视图（最简单版本）。

    返回体：
      { date, missing, reason,
        direction, direction_cn, open_px, S, S_mae,
        zone_lo, zone_hi, zone_mid, stop, exh1, exh2, t1,
        levels:[{ratio,name,price}], candles_30m:[[ts,o,h,l,c]], source,
        prev_close, sma10, diag_sign, diag_direction }
    """
    lad = hs.compute_day_levels(date, symbol)
    if lad is None:
        return {"date": date, "missing": True,
                "reason": "无信号（方向临界 / 日线不足）"}

    bars_1m, source, missing = hs.fetch_day_1m(date, symbol)
    if missing or not bars_1m:
        return {"date": date, "missing": True, "direction": lad.get("direction"),
                "reason": "1m 数据缺失（取数失败）"}

    direction = lad.get("direction")
    levels = []
    for r in _GALLERY_RATIO_ORDER:
        for lv in lad["levels"]:
            if abs(round(lv["ratio"], 3) - round(r, 3)) < 1e-9:
                levels.append({
                    "ratio": lv["ratio"], "name": lv["name"],
                    "price": round(float(lv["price"]), 2)
                })
                break

    # 诊断：独立复算顺势方向（与 hunting_system 同口径），用于服务器核对
    diag = _recompute_direction(date, symbol)

    return {
        "date": date,
        "missing": False,
        "direction": direction,
        "direction_cn": lad.get("direction_cn", "做空" if direction == "short" else "做多"),
        "source": source,
        "open_px": round(float(lad["open_px"]), 2),
        "S": round(float(lad["S"]), 2),
        "S_mae": round(float(lad.get("mae", 0)), 2),
        # 主流程方向来自引擎 lad；诊断方向来自独立复算，二者应一致
        "prev_close": (round(float(diag["prev_close"]), 2)
                       if diag.get("ok") else lad.get("prev_close")),
        "sma10": diag.get("sma10"),
        "diag_sign": diag.get("sign"),
        "diag_direction": diag.get("direction"),
        "diag_ok": diag.get("ok", False),
        "diag_reason": diag.get("reason"),
        "zone_lo": round(float(lad["zone_lo"]), 2),
        "zone_hi": round(float(lad["zone_hi"]), 2),
        "zone_mid": round(float(lad["zone_mid"]), 2),
        "stop": round(float(lad["stop"]), 2),
        "exh1": round(float(lad["exh1"]), 2),
        "exh2": round(float(lad["exh2"]), 2),
        "t1": (round(float(lad["t1"]), 2) if lad.get("t1") is not None else None),
        "levels": levels,
        "candles_30m": _agg_1m_to_30m(bars_1m),
    }
