# rs_v3_extended.py
# 扩展区间补充分析（非正式 PRD 区间）：把 1m 缓存向前延伸到 2024-01-01，跑 v3，
# 用更大样本回答「4h宏观+5m回踩的质量提升是否稳健」（功效补充，待用户确认是否纳入预注册）。
import os, sys, csv, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rs_data as D
import rs_backtest_v3 as R
from rs_backtest_v3 import resample_htf, load_csv

OFFICIAL = R.CACHE_1M
EXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_cache__1m_ext.csv")
EXT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "rs_backtest_v3_extended_result.csv")

START_EXT = (2024, 1, 1)
END = (2026, 10, 2)


def _dt_ms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp() * 1000)


def extend_cache():
    if os.path.exists(EXT):
        rows = load_csv(EXT)
        if rows and rows[0]["open_time"] <= _dt_ms(*START_EXT) and \
           rows[-1]["open_time"] >= _dt_ms(*END) - 60_000:
            print(f"[EXT] 扩展缓存已存在且覆盖区间，复用（{len(rows)} 根）")
            return rows
    exist = load_csv(OFFICIAL)
    exist_start = exist[0]["open_time"]
    print(f"[EXT] 现有缓存起点 {dt.datetime.fromtimestamp(exist_start/1000, dt.timezone.utc)}；"
          f"向前补 {START_EXT} ~ {dt.datetime.fromtimestamp(exist_start/1000, dt.timezone.utc)}")
    s_ms = _dt_ms(*START_EXT)
    e_ms = exist_start
    fresh = D.fetch_klines(R.CONFIG["SYMBOL"], "1m", s_ms, e_ms)
    print(f"[EXT] 新拉取 {len(fresh)} 根")
    combined = fresh + [[c["open_time"], c["open"], c["high"], c["low"], c["close"], c["volume"]] for c in exist]
    combined.sort(key=lambda r: r[0])
    # 去重（按 open_time）
    uniq = {}
    for r in combined:
        uniq[r[0]] = r
    out = [uniq[k] for k in sorted(uniq)]
    with open(EXT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for r in out:
            w.writerow(r)
    print(f"[EXT] 扩展缓存写出 {len(out)} 根 → {EXT}")
    return load_csv(EXT)


def main():
    one = extend_cache()
    print(f"[EXT] 载入 1m: {len(one)} 根")
    mtf = resample_htf(one, 15)
    htf = resample_htf(one, 60)
    htf4 = resample_htf(one, 240)
    ltf5 = resample_htf(one, 5)
    print(f"[EXT] 15m={len(mtf)} 1h={len(htf)} 4h={len(htf4)} 5m={len(ltf5)}")
    trades = R.run_backtest(mtf, htf, htf4, ltf5)
    rep = R.summarize(trades)
    print(f"[EXT] 信号数 n={rep.get('n')}")
    if rep.get('n'):
        print(f"     胜率={rep['win_rate']*100:.1f}%  PF={rep['pf']:.2f}  期望={rep['expectancy']:.2f}pt  "
              f"均RR={rep['avg_rr']:.2f}  CI下界={rep['ci_low']:.2f}")
        print(f"     median SL={rep['median_sl']:.2f}pt  地板占比={rep['floor_ratio']*100:.1f}%  方向={rep['dirs']}")
        print("     二次裁决闸:")
        for c in R.gates(rep):
            print("       " + c)
        cut = int(len(trades) * 0.7)
        isr = R.summarize(trades[:cut]); osr = R.summarize(trades[cut:])
        print(f"     IS(前70%) n={isr.get('n')} PF={isr.get('pf')}  OOS(后30%) n={osr.get('n')} PF={osr.get('pf')}")
    with open(EXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_time", "direction", "entry_time", "entry_price", "sl_price",
                    "tp_price", "sl_dist", "exit_time", "exit_price", "exit_reason",
                    "pnl_points", "rr", "htf_bias", "macro_bias", "adx", "rsi", "atr15m",
                    "position_size", "signal_bar_index", "confirm_lag_5m"])
        for t in trades:
            w.writerow([t["signal_time"], t["direction"], t["entry_time"], t["entry_price"],
                        t["sl_price"], t["tp_price"], t["sl_dist"], t["exit_time"],
                        t["exit_price"], t["exit_reason"], t["pnl_points"], t["rr"],
                        t["htf_bias"], t["macro_bias"], t["adx"], t["rsi"], t["atr15m"],
                        t["position_size"], t["signal_bar_index"], t["confirm_lag_5m"]])
    print(f"[EXT] 逐笔 CSV 已写出: {EXT_OUT}")


if __name__ == "__main__":
    main()
