# -*- coding: utf-8 -*-
"""狩猎区画廊编排层单测（testplan G1/G2/G3）。

纯合成数据 + monkeypatch 取数薄，零触网、可本地复现。
G1 多方向（尤其 long）几何与 P&L 正确；
G2 公共 API 返回体 schema 完整 + missing 路径；
G3 零未来函数：追加闭市后 / 未来 bar 不改变已发生事件与合计。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from huntzone import huntzone_gallery_core as gc
from huntzone import huntback_sim as hs
from huntzone.hz_engine import build

UTC_DAY = "2026-09-02"
TS0 = gc._date_to_open_ms(UTC_DAY)  # UTC 00:00 of that day
# force-close offset 复用引擎常量
from huntzone.huntback_sim import _FORCE_CLOSE_OFFSET_MS
FCL = TS0 + _FORCE_CLOSE_OFFSET_MS


def _make_lad(direction="short", open_px=2000.0, S=50.0, prev_close=1980.0):
    lad = build(open_px, S, direction, prev_close=prev_close)
    lad["mae"] = 21.95
    return lad


def _make_1m(open_px=2000.0, n=400, step_ms=60000, drift=0.3, start_ts=TS0):
    bars = []
    px = open_px
    for i in range(n):
        o = px
        h = px + 6
        l = px - 6
        c = px + drift
        px = c
        bars.append((start_ts + i * step_ms, round(o, 2), round(h, 2),
                     round(l, 2), round(c, 2)))
    return bars


def _patch(lad, bars):
    hs.compute_day_levels = lambda date, symbol="": lad
    hs.fetch_day_1m = lambda date, symbol="": (bars, "local", False)


def test_agg_1m_to_1h_pure_no_lookahead():
    # 同一小时内 60 根 1m → 1 根 1h：o=首, h=max, l=min, c=末
    bars = [(TS0 + i * 60000, 2000 + i, 2005 + i, 1995 + i, 2001 + i) for i in range(60)]
    out = gc._agg_1m_to_1h(bars)
    assert len(out) == 1
    o, h, l, c = out[0][1], out[0][2], out[0][3], out[0][4]
    assert o == 2000
    assert h == max(2005 + i for i in range(60))
    assert l == min(1995 + i for i in range(60))
    assert c == 2001 + 59


# ---- G1 多方向几何 ----
def test_g1_short_geometry():
    lad = _make_lad("short", 2000.0, 50.0, 1980.0)
    # 价格序：zone_hi > zone_mid > zone_lo（做空时空头腿在开盘上方展开）
    assert lad["zone_hi"] > lad["zone_mid"] > lad["zone_lo"]
    # 9 档展示过滤：不含 4.236
    slide = _build_patched(lad, _make_1m(2000.0))
    ratios = [round(lv["ratio"], 3) for lv in slide["levels"]]
    assert 4.236 not in ratios
    assert 0.0 in ratios and 0.191 in ratios and 2.618 in ratios
    assert len(slide["levels"]) == 9
    assert slide["direction"] == "short"
    assert slide["direction_cn"] == "做空"
    assert slide["zone_band"]["color"] == "pink"


def test_g1_long_geometry():
    lad = _make_lad("long", 2000.0, 50.0, 2020.0)
    # 价格序同样 zone_hi > zone_mid > zone_lo（仅方向标注与色带不同）
    assert lad["zone_hi"] > lad["zone_mid"] > lad["zone_lo"]
    slide = _build_patched(lad, _make_1m(2000.0))
    assert slide["direction"] == "long"
    assert slide["direction_cn"] == "做多"
    assert slide["zone_band"]["color"] == "green"


# ---- G2 公共 API schema + missing ----
def test_g2_build_gallery_day_schema():
    lad = _make_lad("short", 2000.0, 50.0, 1980.0)
    slide = _build_patched(lad, _make_1m(2000.0))
    for k in ("date", "direction", "levels", "zone_lo", "zone_hi", "zone_mid",
              "candles_1h", "events", "zones_pnl", "total", "outcome"):
        assert k in slide, "缺失字段 %s" % k
    assert slide["missing"] is False
    assert set(slide["zones_pnl"].keys()) == {"zone_a", "zone_mid", "zone_b"}
    for z in slide["zones_pnl"].values():
        assert set(z.keys()) == {"origin", "be"}
    assert set(slide["total"].keys()) == {"origin", "be"}
    # 1h 聚合点数 <= 24（一天 ≤24 小时，闭市后不计入模拟）
    assert len(slide["candles_1h"]) <= 24


def test_g2_missing_no_signal():
    # compute_day_levels 返回 None → missing:True，绝不猜 S
    gc.clear_cache()
    hs.compute_day_levels = lambda date, symbol="": None
    slide = gc.build_gallery_day(UTC_DAY, 20, "", with_1m=False)
    assert slide["missing"] is True
    assert "reason" in slide
    hs.compute_day_levels = lambda date, symbol="": _make_lad()


def test_g2_range_schema_and_count():
    lad = _make_lad("short", 2000.0, 50.0, 1980.0)
    bars = _make_1m(2000.0)
    hs.compute_day_levels = lambda date, symbol="": lad
    hs.fetch_day_1m = lambda date, symbol="": (bars, "local", False)
    gc.clear_cache()
    rng = gc.build_gallery_range(start="2026-09-01", end="2026-09-05",
                                 trigger=20, symbol="")
    assert rng["trigger"] == 20
    assert rng["count"] == 5
    assert rng["missing_count"] == 0
    assert len(rng["slides"]) == 5
    assert all(not s["missing"] for s in rng["slides"])


# ---- G3 零未来函数：追加闭市后 / 未来 bar 不改变已发生事件与合计 ----
def test_g3_no_future_function_post_close_bars_ignored():
    lad = _make_lad("short", 2000.0, 50.0, 1980.0)
    bars = _make_1m(2000.0, n=400)  # 400 分钟 ≈ 6.6h，全部在闭市前
    _patch(lad, bars)
    s1 = gc.build_gallery_day(UTC_DAY, 20, "", with_1m=False)

    # 追加大量闭市后（> 14:30 UTC）的 bar —— 模拟引擎必须忽略
    future = [(FCL + i * 60000, 3000.0 + i, 3005.0 + i, 2995.0 + i, 3001.0 + i)
              for i in range(200)]
    bars2 = bars + future
    _patch(lad, bars2)
    s2 = gc.build_gallery_day(UTC_DAY, 20, "", with_1m=False)

    assert s1["total"] == s2["total"], "闭市后 bar 不应改变合计（未来函数）"
    assert len(s1["events"]) == len(s2["events"]), "事件数不应因未来 bar 改变"
    for e1, e2 in zip(s1["events"], s2["events"]):
        assert e1["ts_ms"] == e2["ts_ms"] and e1["price"] == e2["price"]


def test_g3_shift_invariant_same_relative_shape():
    # 同几何输入换到另一天，档位价格与合计必须不变（不泄露日期相关未来数据）
    ladA = _make_lad("short", 2000.0, 50.0, 1980.0)
    ladB = _make_lad("short", 2000.0, 50.0, 1980.0)
    barsA = _make_1m(2000.0, n=400, start_ts=TS0)
    tsB = gc._date_to_open_ms("2026-09-10")
    barsB = _make_1m(2000.0, n=400, start_ts=tsB)
    _patch(ladA, barsA)
    sA = gc.build_gallery_day(UTC_DAY, 20, "", with_1m=False)
    _patch(ladB, barsB)
    gc.clear_cache()
    sB = gc.build_gallery_day("2026-09-10", 20, "", with_1m=False)
    pa = [round(l["price"], 4) for l in sA["levels"]]
    pb = [round(l["price"], 4) for l in sB["levels"]]
    assert pa == pb, "档位几何应仅由 open/S/方向决定，与日期无关"
    assert sA["total"] == sB["total"], "合计应仅由相对走势+几何决定"


def _build_patched(lad, bars):
    _patch(lad, bars)
    gc.clear_cache()
    return gc.build_gallery_day(UTC_DAY, 20, "", with_1m=False)


if __name__ == "__main__":
    test_agg_1m_to_1h_pure_no_lookahead()
    test_g1_short_geometry()
    test_g1_long_geometry()
    test_g2_build_gallery_day_schema()
    test_g2_missing_no_signal()
    test_g2_range_schema_and_count()
    test_g3_no_future_function_post_close_bars_ignored()
    test_g3_shift_invariant_same_relative_shape()
    print("ALL GALLERY TESTS PASSED")
