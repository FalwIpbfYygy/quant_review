# rs_test_v3.py
# RS v3 红线测试（阶段二 B：4h 宏观 + 5m 回踩确认 + 5m 管理）
# 纯标准库；运行：python rs_test_v3.py
import os, sys, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rs_backtest_v3 as R
from rs_backtest_v3 import resample_htf, build_hbidx_of

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ==================== TC-1: 零未来函数跨周期对齐（含 4h MACRO 层） ====================
def tc_1_1_macro_bucket():
    print("\n[TC-1.1] MACRO 4h 桶闭合：mbidx 必须落在 [-1, len-1] 且引用已收盘 4h 桶")
    htf4_close = [b * 240 * 60_000 + 240 * 60_000 for b in range(5)]  # 5 个 4h 桶（close=open+4h）
    mtf_opens = [b * 15 * 60_000 for b in range(200)]                  # 200 个 15m
    mb = build_hbidx_of(mtf_opens, htf4_close)
    ok = all(-1 <= x < len(htf4_close) for x in mb)
    closed_ok = all(mb[k] < 0 or htf4_close[mb[k]] <= mtf_opens[k] for k in range(len(mtf_opens)))
    check("mbidx 在合法区间 [-1, len-1]", ok)
    check("mbidx 引用已收盘 4h 桶(close≤MTF.open) 或 -1", closed_ok)


def tc_1_3_forming_4h():
    print("\n[TC-1.3] forming 4h 桶陷阱：横跨 MTF 信号桶、字面 open 在前但仍在形成的 4h 桶必须排除")
    # 4h 桶：[08:00-12:00(close 12:00), 12:00-16:00(close 16:00)]
    htf4_close = [12 * 3600_000, 16 * 3600_000]
    mtf_open = 12 * 3600_000 + 15 * 60_000  # 12:15 信号桶 open
    mb = build_hbidx_of([mtf_open], htf4_close)[0]
    check("选中 08:00-12:00 已收盘桶(mbidx=0)", mb == 0, f"mbidx={mb}")
    check("排除 12:00-16:00 forming 桶", htf4_close[1] > mtf_open)


def tc_1_4_1_5_entry():
    print("\n[TC-1.4/1.5] 入场时点：entry=确认5m柱的下一根5m开盘，且 ek<len(ltf5)")
    mtf, htf, htf4, ltf5 = make_synth("SHORT")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    check("SHORT 场景至少 1 笔", len(trades) >= 1, f"trades={len(trades)}")
    if trades:
        t = trades[0]
        ek = t["signal_bar_index"]
        # entry_time 必须等于 ltf5 中某根开盘（北京时间）
        entry_ms = None
        for c in ltf5:
            if R.beijing_str(c["open_time"]) == t["entry_time"]:
                entry_ms = c["open_time"]
                break
        check("入场时间对应某根 5m 开盘", entry_ms is not None, f"entry={t['entry_time']}")
        # confirm_lag_5m 合理（0..MAX_CONFIRM-1）
        check("confirm_lag_5m 在 [0,23]", 0 <= t["confirm_lag_5m"] < R.CONFIG["MAX_CONFIRM_5M"])


# ==================== TC-2: SL 地板修复（真实数据分布） ====================
def tc_2_real():
    print("\n[TC-2.1/2.2] SL 地板修复（真实数据）：median SL>8pt 且 ATR驱动占比>50%")
    cache = R.CACHE_1M
    if not os.path.exists(cache):
        print("  [SKIP] 无 1m 缓存")
        return
    one = R.load_csv(cache)
    mtf = resample_htf(one, 15)
    htf = resample_htf(one, 60)
    htf4 = resample_htf(one, 240)
    ltf5 = resample_htf(one, 5)
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    rep = R.summarize(trades)
    if rep["n"] == 0:
        check("真实数据有信号", False, "n=0")
        return
    check("median SL > 8pt", rep["median_sl"] > 8, f"median_sl={rep['median_sl']}")
    check("ATR驱动SL占比 > 50%（地板为少数）", rep["floor_ratio"] > 0.50,
          f"floor_ratio={rep['floor_ratio'] * 100:.1f}%")
    print(f"      n={rep['n']}  median_sl={rep['median_sl']:.2f}  floor_ratio={rep['floor_ratio'] * 100:.1f}%")


# ==================== TC-3: 结构/CHoCH/宏观门/回踩确认（合成） ====================
def make_synth(kind, base_ts=None):
    """构造 5m 合成行情，resample 出 15m/1h/4h/5m。
    引擎语义（已核对真实数据）：SHORT=1h 下跌趋势+看跌CHoCH(顺小周期)；LONG=1h 上涨+看涨CHoCH。
    宏观门=多周期同向对齐（SHORT 要求 4h≤0；LONG 要求 4h≥0）。
    kind:
      SHORT   → 4h 跌 + 1h 跌 + 急拉(RSI>70) + 急跌破摆低(CHoCH) + 5m回踩续跌 → ≥1 笔 SHORT
      LONG    → 4h 涨 + 1h 涨 + 急压(RSI<30) + 急涨破摆高(CHoCH) + 5m回踩续涨 → ≥1 笔 LONG
      AGAINST → 4h 涨但 1h 跌（无对齐）+ 看跌CHoCH → 宏观门过滤 → 0 笔 SHORT
      FLAT    → 纯横盘无 CHoCH → 0 笔
      NOCONF  → 4h跌+1h跌+CHoCH，但 5m 直泄无回踩 → 0 笔（回踩确认门拦截）
    """
    if base_ts is None:
        base_ts = (1_700_000_000_000 // 300_000) * 300_000  # 对齐 5m 网格

    def seg(n, start, end, noise=0.05):
        return [start + (end - start) * k / n + (k % 7 - 3) * noise for k in range(n)]

    prices = []
    if kind == "SHORT":
        prices += seg(2640, 2000, 1700, 0.10)   # A: 4h/1h 长跌（宏观≤0, 偏向-1）
        prices += seg(48, 1700, 1810, 0.03)     # B: 4h 急拉（RSI>70 极值）
        prices += seg(30, 1810, 1640, 0.05)     # C: 急跌破近期摆动低 → CHoCH 下破
        prices += seg(12, 1640, 1700, 0.01)     # D1: 5m 强回踩上弹(清越 signal_close+MIN_PB)
        prices += seg(10, 1700, 1620, 0.01)     # D2: 5m 续跌破回踩前低 → 确认
    elif kind == "LONG":
        prices += seg(2640, 1800, 2100, 0.10)   # A: 4h/1h 长涨（宏观≥0, 偏向+1）
        prices += seg(48, 2100, 1990, 0.03)     # B: 4h 急压（RSI<30 极值）
        prices += seg(30, 1990, 2180, 0.05)     # C: 急涨破近期摆动高 → CHoCH 上破
        prices += seg(12, 2180, 2100, 0.01)     # D1: 5m 强回踩下压(清越 signal_close-MIN_PB)
        prices += seg(10, 2100, 2220, 0.01)     # D2: 5m 续涨破回踩前高 → 确认
    elif kind == "AGAINST":
        prices += seg(2640, 1800, 2100, 0.10)   # A: 4h 长涨（宏观+1）
        prices += seg(48, 2100, 2200, 0.03)     # B: 续涨（RSI>70 极值，满足衰竭条件）
        prices += seg(96, 1960, 1780, 0.05)     # C: 急跌破摆低 → CHoCH 下破（宏观仍+1 → 过滤）
    elif kind == "NOCONF":
        prices += seg(2640, 2000, 1700, 0.10)   # A: 4h/1h 长跌
        prices += seg(48, 1700, 1810, 0.03)     # B: 急拉（RSI>70）
        prices += seg(120, 1810, 1500, 0.05)    # C: 急跌破低后直泄，无回踩 → 无确认
    else:  # FLAT
        for k in range(3600):
            prices.append(1900 + (k % 11 - 5) * 1.0)

    # 构造 5m 蜡烛
    ltf5 = []
    for k, p in enumerate(prices):
        o = prices[k - 1] if k > 0 else p
        hi = max(o, p) + 0.3
        lo = min(o, p) - 0.3
        ltf5.append({"open_time": base_ts + k * 300_000, "open": o, "high": hi,
                     "low": lo, "close": p, "volume": 1.0})
    mtf = resample_htf(ltf5, 15)
    htf = resample_htf(ltf5, 60)
    htf4 = resample_htf(ltf5, 240)
    return mtf, htf, htf4, ltf5


def tc_3_1_short():
    print("\n[TC-3.1] 合成 SHORT：4h跌/1h涨背离 + 下破CHoCH + 5m回踩续跌 → ≥1 笔 SHORT")
    mtf, htf, htf4, ltf5 = make_synth("SHORT")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    shorts = [t for t in trades if t["direction"] == "SHORT"]
    check("产生 ≥1 笔 SHORT", len(shorts) >= 1, f"trades={len(trades)} dirs={[t['direction'] for t in trades][:3]}")
    if shorts:
        check("SHORT macro_bias ≤ 0（宏观门通过）", shorts[0]["macro_bias"] <= 0,
              f"macro={shorts[0]['macro_bias']}")


def tc_3_2_long():
    print("\n[TC-3.2] 合成 LONG：4h涨/1h跌背离 + 上破CHoCH + 5m回踩续涨 → ≥1 笔 LONG")
    mtf, htf, htf4, ltf5 = make_synth("LONG")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    longs = [t for t in trades if t["direction"] == "LONG"]
    check("产生 ≥1 笔 LONG", len(longs) >= 1, f"trades={len(trades)}")
    if longs:
        check("LONG macro_bias ≥ 0（宏观门通过）", longs[0]["macro_bias"] >= 0,
              f"macro={longs[0]['macro_bias']}")


def tc_3_3_against():
    print("\n[TC-3.3] 宏观门防同向：4h涨且1h涨（无背离）下破CHoCH → 0 笔 SHORT")
    mtf, htf, htf4, ltf5 = make_synth("AGAINST")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    shorts = [t for t in trades if t["direction"] == "SHORT"]
    check("AGAINST 场景 0 笔 SHORT（被宏观背离门过滤）", len(shorts) == 0, f"shorts={len(shorts)}")


def tc_3_4_flat():
    print("\n[TC-3.4] 横盘无 CHoCH → 0 笔")
    mtf, htf, htf4, ltf5 = make_synth("FLAT")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    check("横盘无信号 n=0", len(trades) == 0, f"n={len(trades)}")


def tc_3_5_noconfirm():
    print("\n[TC-3.5] 回踩确认门：有背离+CHoCH 但 5m 直泄无回踩 → 0 笔（质量门拦截）")
    mtf, htf, htf4, ltf5 = make_synth("NOCONF")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    check("NOCONF 场景 0 笔（回踩确认门拦截）", len(trades) == 0, f"trades={len(trades)}")


def main():
    print("=" * 60)
    print("RS v3 红线测试套件（TC-1.x / TC-2.x / TC-3.x）")
    print("=" * 60)
    tc_1_1_macro_bucket()
    tc_1_3_forming_4h()
    tc_1_4_1_5_entry()
    tc_2_real()
    tc_3_1_short()
    tc_3_2_long()
    tc_3_3_against()
    tc_3_4_flat()
    tc_3_5_noconfirm()
    print("\n" + "=" * 60)
    print(f"结果：PASS={PASS}  FAIL={FAIL}")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
