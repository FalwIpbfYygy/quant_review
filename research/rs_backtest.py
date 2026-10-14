# rs_backtest.py
# 反转结构探针 RS —— 完整回测（严格零未来函数）
#
# ───────────────────────────── 因果纪律（红线） ─────────────────────────────
# 1) 信号在 1m 柱 i 仅消费 timestamp ≤ candles[i] 的数据：指标取 rsi[i]/atr[i]，
#    摆点只认 confirm_i ≤ i 的已确认摆点，HTF 偏向只用「已收盘」桶（htf[:bidx]）。
# 2) 入场价 = opens[i+1]（下一根开盘），信号生成时并不知道 i+1 的高低收，故无偷看。
# 3) 出场用「未来市价前进模拟」（从 entry_idx 起逐根检查 SL/TP 是否被触碰）——
#    这是回测对真实成交的复现，不是用未来结构去构造信号，不违反零未来函数。
# 4) 明确禁止：任何在柱 i 读取 candles[j]（j>i）来「反推形态/结构」的逻辑。
# ──────────────────────────────────────────────────────────────────────────
import os, sys, csv, random, bisect
from rs_data import get_1m, resample_htf, htf_bias, beijing_str

# ---------------- 预注册参数（跑批前锁死，禁止中途调参） ----------------
SYMBOL = ""
HTF_MIN = 60            # HTF 偏向周期（1h）
K_CONFIRM = 3           # 摆点 K 柱确认
RSI_P = 14
RSI_TH = 70             # 超买阈值（对应多头超卖 = 30）
ATR_P = 14
ATR_K = 2.0            # SL = max(2×ATR, 3pt)
MIN_SL_PT = 3.0
RR_TARGET = 1.5         # 目标盈亏比（摸顶反抽打法）
MAX_HOLD_BARS = 300     # 最大持仓（1m 柱 ≈ 5h），超时市价强平
ADX_TH = 20             # HTF 趋势门槛（ADX>20 才视为可交易趋势环境）
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_cache__1m.csv")


# ---------------- 指标（纯 Python，全因果） ----------------
def rsi_series(closes, p=14):
    n = len(closes)
    out = [None] * n
    if n < p + 1:
        return out
    g = l = 0.0
    for i in range(1, p + 1):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            g += ch
        else:
            l -= ch
    g /= p; l /= p
    out[p] = 100 - 100 / (1 + (g / l if l else 999))
    for i in range(p + 1, n):
        ch = closes[i] - closes[i - 1]
        gain = max(ch, 0); loss = max(-ch, 0)
        g = (g * (p - 1) + gain) / p
        l = (l * (p - 1) + loss) / p
        rs = g / l if l else 999
        out[i] = 100 - 100 / (1 + rs)
    return out


def atr_series(highs, lows, closes, p=14):
    n = len(highs)
    tr = [0.0] * n
    out = [None] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    if n < p + 1:
        return out
    s = sum(tr[1:p + 1]) / p
    out[p] = s
    for i in range(p + 1, n):
        s = (s * (p - 1) + tr[i]) / p
        out[i] = s
    return out


def detect_pivots(highs, lows, K=3):
    """交替 H/L 摆点；confirm_i = 右侧 K 根都未突破极值时才确认（只用 ≤ confirm_i 的数据）。"""
    piv = []
    n = len(highs)
    for i in range(2 * K, n):
        c = i - K
        hc = highs[c]; lc = lows[c]
        is_h = is_l = True
        for j in range(i - 2 * K, i + 1):
            if highs[j] > hc:
                is_h = False
            if lows[j] < lc:
                is_l = False
        kind = 'H' if is_h else ('L' if is_l else None)
        if kind is None:
            continue
        if piv and piv[-1][2] == kind:
            if (kind == 'H' and hc > piv[-1][1]) or (kind == 'L' and lc < piv[-1][1]):
                piv[-1] = (c, hc if kind == 'H' else lc, kind, i)
            continue
        piv.append((c, hc if kind == 'H' else lc, kind, i))
    return piv


def trailing_extreme(arr, i, w, kind):
    """近期极值（全因果）：返回 arr[i-w+1..i] 中（非 None）的最大/最小。用于判"涨腿内出现过超买"。"""
    lo = max(0, i - w + 1)
    seg = [x for x in arr[lo:i + 1] if x is not None]
    if not seg:
        return None
    return max(seg) if kind == 'max' else min(seg)


def run_backtest(candles):
    n = len(candles)
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    rsi = rsi_series(closes, RSI_P)
    atr = atr_series(highs, lows, closes, ATR_P)
    htf = resample_htf(candles, HTF_MIN)
    hopens = [h["open_time"] for h in htf]
    bi = [bisect.bisect_right(hopens, candles[i]["open_time"]) - 1 for i in range(n)]
    piv = detect_pivots(highs, lows, K_CONFIRM)

    pi = 0
    trades = []
    next_allowed = 0  # 一笔持仓结束后才允许下一笔（避免重叠，纯仓位管理规则）

    # —— 结构状态机（零未来函数）：只消费 confirm_i ≤ i 的摆点 ——
    # 跟踪「最近确认的摆动高 / 摆动低」；CHoCH = 价格收盘跌破最近摆动低(空)/突破最近摆动高(多)。
    last_H = last_H_ci = None
    last_L = last_L_ci = None
    RSI_WIN = 30            # 近期 RSI 极值回看窗口（涨腿内超买/超卖）

    for i in range(n - 1):
        while pi < len(piv) and piv[pi][3] <= i:
            c, price, kind, ci = piv[pi]
            if kind == 'H':
                last_H, last_H_ci = price, ci
            else:
                last_L, last_L_ci = price, ci
            pi += 1

        if i < next_allowed:
            continue

        # CHoCH（结构破位）：收盘跌破「最近确认的摆动低」→ 空；突破「最近确认的摆动高」→ 多。
        # 与 HTF 偏向 + ADX + 近期 RSI 衰竭组合，天然只在「回撤后破位」时触发，不会在纯趋势中滥发。
        choch_d = bool(last_L is not None and last_L_ci <= i and closes[i] < last_L)
        choch_u = bool(last_H is not None and last_H_ci <= i and closes[i] > last_H)
        if not (choch_d or choch_u):
            continue

        bidx = bi[i]
        if bidx < 50:   # 需要足够 HTF 历史
            continue
        bias, adx = htf_bias(htf, bidx)
        if adx < ADX_TH:
            continue

        direction = -1 if choch_d else 1   # -1 空, +1 多
        if direction == -1 and bias != -1:
            continue
        if direction == 1 and bias != 1:
            continue

        # 超买/超卖衰竭：要求「近 RSI_WIN 根内」涨腿出现过超买（顶部），而非当根仍在超买。
        rsi_hi = trailing_extreme(rsi, i, RSI_WIN, 'max')
        rsi_lo = trailing_extreme(rsi, i, RSI_WIN, 'min')
        if direction == -1 and (rsi_hi is None or rsi_hi < RSI_TH):
            continue
        if direction == 1 and (rsi_lo is None or rsi_lo > (100 - RSI_TH)):
            continue
        r = rsi[i]   # 当前 RSI（已通过衰竭门，非 None）

        a = atr[i]
        if a is None or a <= 0:
            continue
        sl_dist = max(ATR_K * a, MIN_SL_PT)
        ei = i + 1                      # 下一根开盘入场（因果：信号时不看 ei 的高低收）
        if ei >= n:
            break
        entry = opens[ei]
        if direction == -1:
            sl = entry + sl_dist
            tp = entry - sl_dist * RR_TARGET
        else:
            sl = entry - sl_dist
            tp = entry + sl_dist * RR_TARGET

        # 出场：从 ei 起逐根前进模拟（真实成交复现，非偷看结构）
        exit_i = None; exit_px = None; reason = None
        for j in range(ei, min(n, ei + MAX_HOLD_BARS)):
            if direction == -1:
                if lows[j] <= tp:
                    exit_i, exit_px, reason = j, tp, "TP"; break
                if highs[j] >= sl:
                    exit_i, exit_px, reason = j, sl, "SL"; break
            else:
                if highs[j] >= tp:
                    exit_i, exit_px, reason = j, tp, "TP"; break
                if lows[j] <= sl:
                    exit_i, exit_px, reason = j, sl, "SL"; break
        if exit_i is None:
            exit_i = min(n - 1, ei + MAX_HOLD_BARS - 1)
            exit_px = closes[exit_i]; reason = "MAX"

        pnl = (entry - exit_px) if direction == -1 else (exit_px - entry)
        rr = pnl / sl_dist
        trades.append({
            "signal_time": beijing_str(candles[i]["open_time"]),
            "direction": "SHORT" if direction == -1 else "LONG",
            "entry_time": beijing_str(candles[ei]["open_time"]),
            "entry_price": round(entry, 2), "sl_price": round(sl, 2), "tp_price": round(tp, 2),
            "sl_dist": round(sl_dist, 2),
            "exit_time": beijing_str(candles[exit_i]["open_time"]),
            "exit_price": round(exit_px, 2), "exit_reason": reason,
            "pnl_points": round(pnl, 2), "rr": round(rr, 2),
            "htf_bias": bias, "rsi": round(r, 1), "atr": round(a, 3),
        })
        next_allowed = exit_i + 1
    return trades


def summarize(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = [t for t in trades if t["pnl_points"] > 0]
    losses = [t for t in trades if t["pnl_points"] <= 0]
    gp = sum(t["pnl_points"] for t in wins)
    gl = sum(-t["pnl_points"] for t in losses)
    pf = gp / gl if gl > 0 else float('inf')
    pnls = [t["pnl_points"] for t in trades]
    random.seed(42)
    low = []
    for _ in range(1000):
        low.append(sum(random.choice(pnls) for _ in pnls) / n)
    ci_low = sorted(low)[int(0.05 * len(low))]
    return {"n": n, "win_rate": len(wins) / n, "pf": pf,
            "expectancy": sum(pnls) / n, "avg_rr": sum(t["rr"] for t in trades) / n,
            "ci_low": ci_low, "gross_profit": gp, "gross_loss": gl}


def gates(rep):
    if rep["n"] == 0:
        return ["n=0 → 无信号，闸门不适用"]
    out = []
    out.append(f"n={rep['n']} {'PASS' if rep['n'] >= 30 else 'FAIL(功效闸 n<30)'}（n≥30）")
    out.append(f"PF={rep['pf']:.2f} {'PASS' if rep['pf'] >= 1.10 else 'FAIL(PF<1.10)'}（PF≥1.10）")
    out.append(f"bootstrap CI下界={rep['ci_low']:.2f} {'PASS' if rep['ci_low'] > 0 else 'FAIL(≤0)'}（CI下界>0）")
    return out


def main():
    # 回测区间：命令行可覆盖 `python rs_backtest.py 2025-09-01 2026-10-02`
    if len(sys.argv) >= 3:
        sy, sm, sd = map(int, sys.argv[1].split('-'))
        ey, em, ed = map(int, sys.argv[2].split('-'))
        START = (sy, sm, sd); END = (ey, em, ed)
    else:
        START = (2025, 9, 1); END = (2026, 10, 2)   # 默认覆盖加息/降息两 regime
    print(f"[RS] 回测区间 UTC: {START} ~ {END}  标的 {SYMBOL}")
    candles = get_1m(SYMBOL, START, END, CACHE)
    print(f"[RS] 载入 1m K 线: {len(candles)} 根")
    trades = run_backtest(candles)
    rep = summarize(trades)
    print(f"[RS] 信号数 n={rep.get('n')}")
    if rep.get('n'):
        print(f"     胜率={rep['win_rate'] * 100:.1f}%  PF={rep['pf']:.2f}  "
              f"期望={rep['expectancy']:.2f}pt  均RR={rep['avg_rr']:.2f}  CI下界={rep['ci_low']:.2f}")
        print("     二次裁决闸:")
        for c in gates(rep):
            print("       " + c)
        cut = int(len(trades) * 0.7)
        isr = summarize(trades[:cut]); osr = summarize(trades[cut:])
        print(f"     IS(前70%) n={isr.get('n')} PF={isr.get('pf')}  "
              f"OOS(后30%) n={osr.get('n')} PF={osr.get('pf')}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_backtest_result.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_time", "direction", "entry_time", "entry_price", "sl_price",
                    "tp_price", "sl_dist", "exit_time", "exit_price", "exit_reason",
                    "pnl_points", "rr", "htf_bias", "rsi", "atr"])
        for t in trades:
            w.writerow([t["signal_time"], t["direction"], t["entry_time"], t["entry_price"],
                        t["sl_price"], t["tp_price"], t["sl_dist"], t["exit_time"],
                        t["exit_price"], t["exit_reason"], t["pnl_points"], t["rr"],
                        t["htf_bias"], t["rsi"], t["atr"]])
    print(f"[RS] 逐笔 CSV 已写出: {out}  （信号/入场/平仓时间均为北京时间）")
    print("[RS] 样本（前 5 笔）:")
    for t in trades[:5]:
        print("      ", t["signal_time"], t["direction"], "入", t["entry_price"],
              "SL", t["sl_price"], "TP", t["tp_price"], "出", t["exit_time"],
              t["exit_reason"], "pnl", t["pnl_points"])


if __name__ == "__main__":
    main()
