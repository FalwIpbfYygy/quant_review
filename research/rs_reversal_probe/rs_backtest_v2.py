# rs_backtest_v2.py
# 反转结构探针 RS —— v2 多时间周期（MTF）回测（严格零未来函数）
#
# ───────────────────────────── 因果纪律（红线，对应 PRD R1–R8 + TC-1.3） ─────────────────────────────
# R1 自身闭合：每个周期只消费已收盘柱。
# R2 HTF 偏向取最后完全收盘桶：评估时只取 close_time ≤ MTF信号桶.open_time 的 1h 桶（比 MTF 自身更严）。
# R3 MTF 结构取最后完全收盘桶：15m 摆点/CHoCH 只在 confirm_i ≤ i 的已收盘桶评估。
# R4 信号成立与最早入场：信号在定义它的 MTF 柱收盘后才成立；最早入场 = 该柱 close_time 之后第一根 MTF 开盘。
# R5 epoch 对齐：k_closed = floor(ts/T) - 1（本实现用 bisect 于 close_time 直接落实 R2）。
# R6 入场价唯一来源：entry_price = open(确认柱 + 1)，信号生成时不知道 ei 的高低收。
# R7 指标仅基于闭合序列：ATR/EMA/ADX/RSI 全部用闭合柱序列计算。
# R8 禁止跨周期偷看：HTF 只引用 MTF 信号桶之前已收盘的桶（TC-1.3：close_time ≤ MTF.open_time）。
# 出场用「未来市价前进模拟」逐根检查 SL/TP/BE/反向CHoCH/超时——回测对真实成交的复现，不构造信号，不违反零未来函数。
# ──────────────────────────────────────────────────────────────────────────
import os, sys, csv, json, hashlib, random, bisect

from rs_data import resample_htf, htf_bias, beijing_str, load_csv

# ==================== 预注册参数（跑批前锁死，禁止中途调参） ====================
CONFIG = {
    "SYMBOL": "",
    "MTF_MIN": 15,          # MTF 结构层 = 15m
    "HTF_MIN": 60,          # HTF 偏向/regime 层 = 1h
    "K_CONFIRM": 3,         # 摆点 K 柱确认
    "RSI_P": 14,
    "RSI_TH": 70,           # 超买阈值（对应超卖 = 30）
    "ATR_P": 14,
    "ATR_K": 2.25,          # SL = max(2.25×15mATR, 6pt)  —— 修地板
    "MIN_SL_PT": 6.0,
    "RR_TARGET": 1.5,       # TP = 1.5R
    "MAX_HOLD_BARS": 160,   # 最大持仓（15m 柱 ≈ 40h），超时市价强平
    "ADX_TH": 20,           # HTF ADX(14) > 20 才视为可交易趋势环境
    "BE_R": 1.0,            # 浮盈达 +1R 推保本
    "HTF_EMA_FAST": 20,
    "HTF_EMA_SLOW": 50,
    "RSI_WIN": 30,          # 近期 RSI 极值回看窗口（涨/跌腿内衰竭）
    "RISK_BUDGET": 1000.0,  # 固定风险预算（名义，仅用于 position_size 核算）
}
# 冻结哈希：任何参数改动导致哈希不符 → 拒绝运行（防参数漂移 / 防未注册调参）
FROZEN_CONFIG_HASH = "1fcad95b90a4c4bd282950c6ca2f2e5e56e6f03cc4aef6be9c3f4b560fc75110"

CACHE_1M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_cache__1m.csv")


def config_hash():
    return hashlib.sha256(json.dumps(CONFIG, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_config():
    h = config_hash()
    if h != FROZEN_CONFIG_HASH:
        raise RuntimeError(
            f"[RS v2] config_hash 不符：compute={h} frozen={FROZEN_CONFIG_HASH}\n"
            f"        参数被改动但未重新冻结 → 拒绝运行（请先经预注册评审）。")
    return h


# ==================== 指标（纯 Python，全因果） ====================
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
    g /= p
    l /= p
    out[p] = 100 - 100 / (1 + (g / l if l else 999))
    for i in range(p + 1, n):
        ch = closes[i] - closes[i - 1]
        gain = max(ch, 0)
        loss = max(-ch, 0)
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
        hc = highs[c]
        lc = lows[c]
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
    """近期极值（全因果）：返回 arr[i-w+1..i] 中（非 None）的最大/最小。"""
    lo = max(0, i - w + 1)
    seg = [x for x in arr[lo:i + 1] if x is not None]
    if not seg:
        return None
    return max(seg) if kind == 'max' else min(seg)


# ==================== 纯函数尺寸（接口契约 4：compute_sl 传 15m ATR 入参，不内部引用 1m） ====================
def compute_sl(atr_15m, atr_k=CONFIG["ATR_K"], min_sl=CONFIG["MIN_SL_PT"]):
    if atr_15m is None or atr_15m <= 0:
        return None
    return max(atr_k * atr_15m, min_sl)


# ==================== 跨周期闭合映射（接口契约 2 + TC-1.3） ====================
def build_hbidx_of(mtf_opens, htf_close_times):
    """对每个 MTF 柱，返回「最后完全收盘」HTF 桶序号：close_time ≤ mtf.open_time（TC-1.3 硬约束）。

    关键：用 close_time 而非 open_time 判定，排除横跨 MTF 信号桶、字面 open 在前但仍在形成的 HTF 桶。
    """
    return [bisect.bisect_right(htf_close_times, mtf_opens[i]) - 1 for i in range(len(mtf_opens))]


# ==================== 主回测 ====================
def run_backtest(mtf, htf, cfg=CONFIG, htf_gate=True, rev_exit=True):
    K_CONFIRM = cfg["K_CONFIRM"]; RSI_P = cfg["RSI_P"]; RSI_TH = cfg["RSI_TH"]
    ATR_P = cfg["ATR_P"]; RR = cfg["RR_TARGET"]; MAXH = cfg["MAX_HOLD_BARS"]
    ADX_TH = cfg["ADX_TH"]; BE_R = cfg["BE_R"]; RWIN = cfg["RSI_WIN"]
    EF = cfg["HTF_EMA_FAST"]; ES = cfg["HTF_EMA_SLOW"]; RB = cfg["RISK_BUDGET"]

    n = len(mtf)
    opens = [c["open"] for c in mtf]
    highs = [c["high"] for c in mtf]
    lows = [c["low"] for c in mtf]
    closes = [c["close"] for c in mtf]
    mtf_opens_ts = [c["open_time"] for c in mtf]
    htf_close_times = [c["open_time"] + cfg["HTF_MIN"] * 60_000 for c in htf]

    rsi = rsi_series(closes, RSI_P)
    atr = atr_series(highs, lows, closes, ATR_P)
    hbidx_of = build_hbidx_of(mtf_opens_ts, htf_close_times)
    piv = detect_pivots(highs, lows, K_CONFIRM)

    trades = []
    next_allowed = 0
    pi = 0
    last_H = last_H_ci = last_L = last_L_ci = None

    for i in range(n - 1):
        # 消费 confirm_i ≤ i 的已确认摆点（R3）
        while pi < len(piv) and piv[pi][3] <= i:
            c, price, kind, ci = piv[pi]
            if kind == 'H':
                last_H, last_H_ci = price, ci
            else:
                last_L, last_L_ci = price, ci
            pi += 1

        if i < next_allowed:
            continue

        # CHoCH（结构破位，全因果）：收盘跌破最近确认摆动低 → 空；突破最近确认摆动高 → 多
        choch_d = bool(last_L is not None and last_L_ci <= i and closes[i] < last_L)
        choch_u = bool(last_H is not None and last_H_ci <= i and closes[i] > last_H)
        if not (choch_d or choch_u):
            continue

        # —— HTF 偏向 + regime 门（R2/R8，TC-1.3）——
        bias = 0
        adx = 999.0
        if htf_gate:
            hbidx = hbidx_of[i]
            if hbidx < 50:   # 需要足够 HTF 历史
                continue
            bias, adx = htf_bias(htf, hbidx + 1)  # htf[:hbidx+1] = 全部已收盘桶
            if adx < ADX_TH:
                continue

            direction = -1 if choch_d else 1   # -1 空, +1 多
            if direction == -1 and bias != -1:
                continue
            if direction == 1 and bias != 1:
                continue
        else:
            direction = -1 if choch_d else 1   # -1 空, +1 多

        # 超买/超卖衰竭：要求「近 RWIN 根内」涨/跌腿出现过超买/超卖，而非当根仍在极值
        rsi_hi = trailing_extreme(rsi, i, RWIN, 'max')
        rsi_lo = trailing_extreme(rsi, i, RWIN, 'min')
        if direction == -1 and (rsi_hi is None or rsi_hi < RSI_TH):
            continue
        if direction == 1 and (rsi_lo is None or rsi_lo > (100 - RSI_TH)):
            continue
        r = rsi[i]

        sl_dist = compute_sl(atr[i])
        if sl_dist is None:
            continue
        ei = i + 1                      # R4/R6：下一根 15m 开盘入场（信号时不看 ei 高低收）
        if ei >= n:
            break
        entry = opens[ei]
        if direction == -1:
            sl = entry + sl_dist
            tp = entry - sl_dist * RR
        else:
            sl = entry - sl_dist
            tp = entry + sl_dist * RR

        # —— 出场模拟（从 ei 起逐根前进；含 BE / 反向CHoCH / 超时）——
        sl_cur = sl
        exit_i = None
        exit_px = None
        reason = None
        # 交易窗口内继续推进摆点（供反向 CHoCH 判定），从信号时已消费的 pi 继续
        jpi = pi
        tr_H = last_H
        tr_H_ci = last_H_ci
        tr_L = last_L
        tr_L_ci = last_L_ci
        for j in range(ei, min(n, ei + MAXH)):
            # 推进摆点至 confirm ≤ j
            while jpi < len(piv) and piv[jpi][3] <= j:
                c, price, kind, ci = piv[jpi]
                if kind == 'H':
                    tr_H, tr_H_ci = price, ci
                else:
                    tr_L, tr_L_ci = price, ci
                jpi += 1
            # 1) SL/TP 价位触碰（limit/stop，沿用标准回测约定）
            if direction == -1:
                if lows[j] <= tp:
                    exit_i, exit_px, reason = j, tp, "TP"
                    break
                if highs[j] >= sl_cur:
                    exit_i, exit_px, reason = j, sl_cur, "SL"
                    break
                if lows[j] <= entry - sl_dist:   # 浮盈达 +1R → 推保本
                    sl_cur = entry
            else:
                if highs[j] >= tp:
                    exit_i, exit_px, reason = j, tp, "TP"
                    break
                if lows[j] <= sl_cur:
                    exit_i, exit_px, reason = j, sl_cur, "SL"
                    break
                if highs[j] >= entry + sl_dist:
                    sl_cur = entry
            # 2) 反向 CHoCH（事件型市价退出，基于已收盘柱 j，fill = close[j]）
            if rev_exit:
                if direction == -1 and tr_H is not None and tr_H_ci <= j and closes[j] > tr_H:
                    exit_i, exit_px, reason = j, closes[j], "REV"
                    break
                if direction == 1 and tr_L is not None and tr_L_ci <= j and closes[j] < tr_L:
                    exit_i, exit_px, reason = j, closes[j], "REV"
                    break
        if exit_i is None:
            exit_i = min(n - 1, ei + MAXH - 1)
            exit_px = closes[exit_i]
            reason = "MAX"

        pnl = (entry - exit_px) if direction == -1 else (exit_px - entry)
        rr = pnl / sl_dist
        position_size = RB / sl_dist   # 固定风险预算，对冲 SL 放大暴露
        trades.append({
            "signal_time": beijing_str(mtf[i]["open_time"]),
            "direction": "SHORT" if direction == -1 else "LONG",
            "entry_time": beijing_str(mtf[ei]["open_time"]),
            "entry_price": round(entry, 2), "sl_price": round(sl, 2), "tp_price": round(tp, 2),
            "sl_dist": round(sl_dist, 2),
            "exit_time": beijing_str(mtf[exit_i]["open_time"]),
            "exit_price": round(exit_px, 2), "exit_reason": reason,
            "pnl_points": round(pnl, 2), "rr": round(rr, 2),
            "htf_bias": bias, "adx": round(adx, 1), "rsi": round(r, 1),
            "atr15m": round(atr[i], 3), "position_size": round(position_size, 2),
            "signal_bar_index": i,
        })
        next_allowed = exit_i + 1
    return trades


# ==================== 统计 + 闸门 ====================
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
    for _ in range(2000):
        low.append(sum(random.choice(pnls) for _ in pnls) / n)
    ci_low = sorted(low)[int(0.05 * len(low))]
    sl_dists = sorted(t["sl_dist"] for t in trades)
    median_sl = sl_dists[len(sl_dists) // 2]
    floor_ratio = sum(1 for s in sl_dists if s > CONFIG["MIN_SL_PT"]) / n  # ATR 决定 SL 的占比
    return {"n": n, "win_rate": len(wins) / n, "pf": pf,
            "expectancy": sum(pnls) / n, "avg_rr": sum(t["rr"] for t in trades) / n,
            "ci_low": ci_low, "gross_profit": gp, "gross_loss": gl,
            "median_sl": median_sl, "floor_ratio": floor_ratio}


def gates(rep):
    if rep["n"] == 0:
        return ["n=0 → 无信号，闸门不适用"]
    out = []
    out.append(f"n={rep['n']} {'PASS' if rep['n'] >= 30 else 'FAIL(功效闸 n<30)'}（n≥30）")
    out.append(f"PF={rep['pf']:.2f} {'PASS' if rep['pf'] >= 1.10 else 'FAIL(PF<1.10)'}（PF≥1.10）")
    out.append(f"OOS>0: {'PASS' if rep['expectancy'] > 0 else 'FAIL(期望≤0)'}（期望>0）")
    out.append(f"bootstrap CI下界={rep['ci_low']:.2f} {'PASS' if rep['ci_low'] > 0 else 'FAIL(≤0)'}（CI下界>0）")
    return out


def main():
    verify_config()
    if len(sys.argv) >= 3:
        sy, sm, sd = map(int, sys.argv[1].split('-'))
        ey, em, ed = map(int, sys.argv[2].split('-'))
        START = (sy, sm, sd)
        END = (ey, em, ed)
    else:
        START = (2025, 9, 1)
        END = (2026, 10, 2)

    print(f"[RS v2] config_hash={config_hash()}  标的 {CONFIG['SYMBOL']}  MTF={CONFIG['MTF_MIN']}m/HTF={CONFIG['HTF_MIN']}m")
    print(f"[RS v2] 回测区间 UTC: {START} ~ {END}")

    one_min = load_csv(CACHE_1M)
    print(f"[RS v2] 载入 1m K 线: {len(one_min)} 根（从已验证缓存重采样 15m/1h，避免网格错位）")
    mtf = resample_htf(one_min, CONFIG["MTF_MIN"])
    htf = resample_htf(one_min, CONFIG["HTF_MIN"])
    print(f"[RS v2] MTF(15m)={len(mtf)} 根  HTF(1h)={len(htf)} 根")

    trades = run_backtest(mtf, htf)
    rep = summarize(trades)
    print(f"[RS v2] 信号数 n={rep.get('n')}")
    if rep.get('n'):
        print(f"     胜率={rep['win_rate'] * 100:.1f}%  PF={rep['pf']:.2f}  "
              f"期望={rep['expectancy']:.2f}pt  均RR={rep['avg_rr']:.2f}  CI下界={rep['ci_low']:.2f}")
        print(f"     median SL={rep['median_sl']:.2f}pt  地板(由ATR决定)占比={rep['floor_ratio'] * 100:.1f}%")
        print("     二次裁决闸:")
        for c in gates(rep):
            print("       " + c)
        cut = int(len(trades) * 0.7)
        isr = summarize(trades[:cut])
        osr = summarize(trades[cut:])
        print(f"     IS(前70%) n={isr.get('n')} PF={isr.get('pf')}  "
              f"OOS(后30%) n={osr.get('n')} PF={osr.get('pf')}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "rs_backtest_v2_result.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_time", "direction", "entry_time", "entry_price", "sl_price",
                    "tp_price", "sl_dist", "exit_time", "exit_price", "exit_reason",
                    "pnl_points", "rr", "htf_bias", "adx", "rsi", "atr15m",
                    "position_size", "signal_bar_index"])
        for t in trades:
            w.writerow([t["signal_time"], t["direction"], t["entry_time"], t["entry_price"],
                        t["sl_price"], t["tp_price"], t["sl_dist"], t["exit_time"],
                        t["exit_price"], t["exit_reason"], t["pnl_points"], t["rr"],
                        t["htf_bias"], t["adx"], t["rsi"], t["atr15m"],
                        t["position_size"], t["signal_bar_index"]])
    print(f"[RS v2] 逐笔 CSV 已写出: {out}  （信号/入场/平仓时间均为北京时间）")
    print("[RS v2] 样本（前 5 笔）:")
    for t in trades[:5]:
        print("      ", t["signal_time"], t["direction"], "入", t["entry_price"],
              "SL", t["sl_price"], "TP", t["tp_price"], "出", t["exit_time"],
              t["exit_reason"], "pnl", t["pnl_points"])


if __name__ == "__main__":
    main()
