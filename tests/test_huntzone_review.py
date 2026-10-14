# -*- coding: utf-8 -*-
"""多日狩猎区复盘工具（/huntzone-review）单测。合成数据 + monkeypatch，零触网。

覆盖：30m 聚合纯聚合、复刻 hunting_system/daily_push 取数/信号口径、
输出 schema、零未来函数（日线只用 ≤ 该日）、交易日枚举口径、
顺势方向、缺失日透明化。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime

from huntzone import huntzone_review_core as rc
from huntzone.huntback_sim import _date_to_open_ms

UTC = datetime.timezone.utc


def _make_daily(rows_start=datetime.date(2026, 9, 1),
                rows_end=datetime.date(2026, 10, 7), base=100.0, step=2.0):
    """合成日线：仅工作日（模拟 Twelve Data 丢弃周末），收盘价单调上升 → 顺势做多。"""
    out = []
    idx = 0
    cur = datetime.datetime(rows_start.year, rows_start.month, rows_start.day, tzinfo=UTC)
    end = datetime.datetime(rows_end.year, rows_end.month, rows_end.day, tzinfo=UTC)
    while cur <= end:
        if cur.weekday() < 5:
            t = cur.strftime("%Y-%m-%d")
            o = base + idx * step
            c = o + 1.5
            out.append((t, float(o), float(o + 5), float(o - 5), float(c)))
            idx += 1
        cur += datetime.timedelta(days=1)
    return out


def _make_30m_for_day(date_str, base=100.0):
    """合成某日的 30m 蜡烛（48 根）。"""
    d_ms = _date_to_open_ms(date_str)
    candles = []
    for i in range(48):
        ts = d_ms + i * 30 * 60000
        p = base + i * 0.1
        candles.append([ts, round(p, 2), round(p + 1, 2),
                        round(p - 1, 2), round(p + 0.5, 2)])
    return candles


def _patch(daily):
    rc.hs_data.load_bars_primary = lambda end_date: (daily, "twelvedata")
    rc._fetch_30m_for_day = lambda date, symbol="": (_make_30m_for_day(date), False)


def test_agg_1m_to_30m_pure():
    bars = [(1000 + i * 60000, 2000 + i, 2005 + i, 1995 + i, 2001 + i) for i in range(30)]
    out = rc._agg_1m_to_30m(bars)
    assert len(out) == 1
    o, h, l, c = out[0][1], out[0][2], out[0][3], out[0][4]
    assert o == 2000
    assert h == 2005 + 29
    assert l == 1995
    assert c == 2001 + 29


def test_review_schema_and_no_future_fn():
    start, end = "2026-10-01", "2026-10-07"
    daily = _make_daily()
    _patch(daily)

    out = rc.build_review_view(start, end, symbol="")
    assert out["ok"] is True, out.get("reason")
    # panels 数量 = 窗口内工作日数（合成日线仅工作日）
    wd = 0
    c = datetime.date(2026, 10, 1)
    while c <= datetime.date(2026, 10, 7):
        if c.weekday() < 5: wd += 1
        c += datetime.timedelta(days=1)
    assert len(out["panels"]) == wd

    # 每个 panel 都有 30m K线且无未来函数（ts 落在当日）
    for p in out["panels"]:
        assert len(p["candles_30m"]) > 0
        d_ms = _date_to_open_ms(p["date"])
        for cc in p["candles_30m"]:
            assert d_ms <= cc[0] < d_ms + 86400000
        assert p["has_signal"] is True
        assert p["direction"] == "long"
        assert p["警戒"] is not None
        assert p["zone_lo"] < p["zone_hi"]
        assert len(p["levels"]) == 10  # engine.py LADDER 10 档


def test_review_daily_fetch_fail_502():
    rc.hs_data.load_bars_primary = lambda end_date: (None, "error: mocked")
    rc._fetch_30m_for_day = lambda date, symbol="": ([], True)
    out = rc.build_review_view("2026-10-01", "2026-10-07")
    assert out["ok"] is False
    assert len(out["panels"]) == 0


def test_review_missing_days_transparent():
    start, end = "2026-10-05", "2026-10-07"
    daily = _make_daily()
    # 只返回 10-07 的 30m，其余缺失
    rc.hs_data.load_bars_primary = lambda end_date: (daily, "twelvedata")
    rc._fetch_30m_for_day = lambda date, symbol="": (_make_30m_for_day(date), False) if date == "2026-10-07" else ([], True)
    out = rc.build_review_view(start, end)
    assert out["ok"] is True
    assert "2026-10-05" in out["missing_days"]
    assert "2026-10-06" in out["missing_days"]
    assert "2026-10-07" not in out["missing_days"]


def test_review_insufficient_history_no_signal():
    # 窗口第一天历史不足 7 根日线 → has_signal=False，但 panel 仍存在
    daily = _make_daily(rows_start=datetime.date(2026, 10, 1),
                        rows_end=datetime.date(2026, 10, 2))
    rc.hs_data.load_bars_primary = lambda end_date: (daily, "twelvedata")
    rc._fetch_30m_for_day = lambda date, symbol="": (_make_30m_for_day(date), False)
    out = rc.build_review_view("2026-10-01", "2026-10-02")
    assert out["ok"] is True
    # 2026-10-01 只有 1 根历史（不够 7）→ 无信号
    p1 = next(p for p in out["panels"] if p["date"] == "2026-10-01")
    assert p1["has_signal"] is False


if __name__ == "__main__":
    test_agg_1m_to_30m_pure()
    test_review_schema_and_no_future_fn()
    test_review_daily_fetch_fail_502()
    test_review_missing_days_transparent()
    test_review_insufficient_history_no_signal()
    print("ALL REVIEW TESTS PASSED")
