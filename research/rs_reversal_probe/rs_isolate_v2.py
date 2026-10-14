# rs_isolate_v2.py
# 按 PRD 步骤 5 做隔离分析：先跑「15m 单周期地板修复」(R1)，再叠「HTF 偏向门 + 反向CHoCH」(R2)。
# 目的：把「SL 来源从 1m 切到 15m ATR」的修复效果，与「多周期门控」的附加效果分离，
#       回答用户原质疑「为什么只用 1m」以及 v2 是否真的改善。
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rs_backtest_v2 as R
from rs_backtest_v2 import resample_htf, load_csv

CACHE = R.CACHE_1M


def run_variant(label, htf_gate, rev_exit):
    one = load_csv(CACHE)
    mtf = resample_htf(one, R.CONFIG["MTF_MIN"])
    htf = resample_htf(one, R.CONFIG["HTF_MIN"])
    trades = R.run_backtest(mtf, htf, htf_gate=htf_gate, rev_exit=rev_exit)
    rep = R.summarize(trades)
    return trades, rep


def report(label, trades, rep):
    print(f"\n=== {label} ===")
    if rep["n"] == 0:
        print("  n=0 无信号")
        return
    print(f"  n={rep['n']}  胜率={rep['win_rate'] * 100:.1f}%  PF={rep['pf']:.2f}  "
          f"期望={rep['expectancy']:.2f}pt  均RR={rep['avg_rr']:.2f}  CI下界={rep['ci_low']:.2f}")
    print(f"  median SL={rep['median_sl']:.2f}pt  ATR驱动占比={rep['floor_ratio'] * 100:.1f}%")
    print("  二次裁决闸:")
    for c in R.gates(rep):
        print("    " + c)
    cut = int(len(trades) * 0.7)
    isr = R.summarize(trades[:cut]); osr = R.summarize(trades[cut:])
    print(f"  IS(前70%) n={isr.get('n')} PF={isr.get('pf')}  OOS(后30%) n={osr.get('n')} PF={osr.get('pf')}")


def verdict(rep):
    if rep["n"] == 0:
        return "n=0（闸门不适用）"
    ok = (rep["n"] >= 30 and rep["pf"] >= 1.10 and rep["ci_low"] > 0)
    return "PASS 二次裁决" if ok else "FAIL 二次裁决"


def main():
    print("RS v2 隔离分析（PRD 步骤 5）：R1=15m地板修复(无HTF门/无REV) | R2=完整MTF(HTF门+REV)")
    print("基准 v1：n=1598 PF=1.04 CI=-0.19（未过闸，SL恒撞3pt地板）")
    t1, r1 = run_variant("R1: 15m 地板修复（仅 MTF=15m 结构 + 15mATR止损，无 HTF 门、无反向CHoCH）", False, False)
    t2, r2 = run_variant("R2: 完整 MTF（MTF=15m + HTF=1h 偏向/ADX 门 + 反向CHoCH 退出）", True, True)
    report("R1", t1, r1)
    report("R2", t2, r2)
    print("\n--- 裁决 ---")
    print(f"  R1 二次裁决：{verdict(r1)}")
    print(f"  R2 二次裁决：{verdict(r2)}")
    print("\n--- 增量归因（R2 − R1）---")
    if r1["n"] and r2["n"]:
        print(f"  信号数：{r1['n']} → {r2['n']}（HTF门+REV 使信号更稀疏）")
        print(f"  PF：{r1['pf']:.2f} → {r2['pf']:.2f}")
        print(f"  CI下界：{r1['ci_low']:.2f} → {r2['ci_low']:.2f}")
        print(f"  median SL：{r1['median_sl']:.2f} → {r2['median_sl']:.2f}（SL 来源一致，故相近）")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    for name, trades in [("rs_v2_iso_R1_15m_only.csv", t1), ("rs_v2_iso_R2_full_mtf.csv", t2)]:
        with open(os.path.join(out_dir, name), "w", newline="", encoding="utf-8") as f:
            import csv
            w = csv.writer(f)
            w.writerow(["signal_time", "direction", "entry_time", "entry_price", "sl_price",
                        "tp_price", "sl_dist", "exit_time", "exit_price", "exit_reason",
                        "pnl_points", "rr", "htf_bias", "adx", "rsi", "atr15m", "position_size"])
            for t in trades:
                w.writerow([t["signal_time"], t["direction"], t["entry_time"], t["entry_price"],
                            t["sl_price"], t["tp_price"], t["sl_dist"], t["exit_time"],
                            t["exit_price"], t["exit_reason"], t["pnl_points"], t["rr"],
                            t["htf_bias"], t["adx"], t["rsi"], t["atr15m"], t["position_size"]])
        print(f"  写出 {name}")


if __name__ == "__main__":
    main()
