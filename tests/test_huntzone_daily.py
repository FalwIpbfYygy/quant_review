# -*- coding: utf-8 -*-
"""狩猎区每日效果图（/huntzone-daily）单测。合成数据 + monkeypatch，零触网。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from huntzone import huntzone_daily_core as dc
from huntzone import huntback_sim as hs
from huntzone.hz_engine import build

UTC_DAY = "2026-09-02"
TS0 = dc.hs._date_to_open_ms(UTC_DAY)


def _make_lad(direction="short", open_px=2650.0, S=30.0, prev_close=2630.0):
    lad = build(open_px, S, direction, prev_close=prev_close)
    lad["mae"] = 21.95
    return lad


def _make_1m(open_px=2650.0, n=400):
    bars = []
    px = open_px
    for i in range(n):
        o, c = px, px + 0.3
        h, l = o + 4, o - 4
        bars.append((TS0 + i * 60000, round(o, 2), round(h, 2), round(l, 2), round(c, 2)))
        px = c
    return bars


def test_agg_1m_to_30m_pure():
    # 30 根 1m → 1 根 30m
    bars = [(TS0 + i * 60000, 2000 + i, 2005 + i, 1995 + i, 2001 + i) for i in range(30)]
    out = dc._agg_1m_to_30m(bars)
    assert len(out) == 1
    o, h, l, c = out[0][1], out[0][2], out[0][3], out[0][4]
    assert o == 2000
    assert h == 2005 + 29
    assert l == 1995
    assert c == 2001 + 29


def test_build_daily_view_schema():
    lad = _make_lad("short", 2650.0, 30.0, 2630.0)
    bars = _make_1m(2650.0)
    hs.compute_day_levels = lambda date, symbol="": lad
    hs.fetch_day_1m = lambda date, symbol="": (bars, "local", False)
    out = dc.build_daily_view(UTC_DAY, "")
    assert out["missing"] is False
    assert out["direction"] == "short"
    assert out["direction_cn"] == "做空"
    assert len(out["levels"]) == 9
    # 4.236 不展示
    assert 4.236 not in [round(l["ratio"], 3) for l in out["levels"]]
    assert "candles_30m" in out
    assert len(out["candles_30m"]) > 0
    assert out["zone_hi"] > out["zone_mid"] > out["zone_lo"]


def test_build_daily_view_missing_no_signal():
    hs.compute_day_levels = lambda date, symbol="": None
    out = dc.build_daily_view(UTC_DAY, "")
    assert out["missing"] is True
    assert "reason" in out


def test_build_daily_view_missing_1m():
    lad = _make_lad("short", 2650.0, 30.0, 2630.0)
    hs.compute_day_levels = lambda date, symbol="": lad
    hs.fetch_day_1m = lambda date, symbol="": ([], "local", True)
    out = dc.build_daily_view(UTC_DAY, "")
    assert out["missing"] is True
    assert out["direction"] == "short"


def _fake_daily_rows():
    """13 根已收盘日线（TS0-12d .. TS0）；prev_bar(TS0-1d) 收盘=95 < 其余 10 根均值 100 → 做空。"""
    rows = []
    for i in range(13):
        ot = TS0 - (12 - i) * 86400000
        close = 100.0
        if i == 11:            # TS0-1day = prev_bar
            close = 95.0
        rows.append([ot, 100.0, 105.0, 95.0, close, 1000.0, ot + 86399999])
    return rows


def test_build_daily_view_diag_short():
    """独立复算方向（与 hunting_system 同口径）：prev_close<SMA10 → 做空，sign=-1。"""
    lad = _make_lad("short", 2650.0, 30.0, 2630.0)
    bars = _make_1m(2650.0)
    hs.compute_day_levels = lambda date, symbol="": lad
    hs.fetch_day_1m = lambda date, symbol="": (bars, "local", False)
    import huntv2_core
    huntv2_core.fetch_daily_1d = lambda symbol="", limit=90: (_fake_daily_rows(), None, "fapi")
    out = dc.build_daily_view(UTC_DAY, "")
    assert out["missing"] is False
    assert out["diag_ok"] is True
    assert out["diag_direction"] == "short"
    assert out["diag_sign"] == -1
    assert out["prev_close"] == 95.0
    # SMA10 = 末 10 根收盘均值 = (9×100 + 95)/10 = 99.5；prev_close(95) < 99.5 → 做空
    assert out["sma10"] == 99.5
    # 主流程方向（来自引擎 lad）与独立复算方向一致
    assert out["direction"] == out["diag_direction"]


if __name__ == "__main__":
    test_agg_1m_to_30m_pure()
    test_build_daily_view_schema()
    test_build_daily_view_missing_no_signal()
    test_build_daily_view_missing_1m()
    test_build_daily_view_diag_short()
    print("ALL DAILY TESTS PASSED")
