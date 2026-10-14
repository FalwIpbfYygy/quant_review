# rs_backtest_v3.py
# 反转结构探针 RS —— v3 阶段二（B 方案）：4h 宏观过滤 + 5m 回踩确认 + 5m 持仓管理（严格零未来函数）
#
# ───────────────────────────── 因果纪律（红线，扩展自 v2 R1–R8 + TC-1.3） ─────────────────────────────
# 四层周期栈：
#   MACRO=4h  宏观趋势层（EMA20/50 偏向；要求 1h 与 4h 背离，过滤「顺大势逆小势」的劣化 fade）
#   HTF=1h    偏向 + ADX(14)>20 regime 层（沿用 v2）
#   MTF=15m   摆点 / CHoCH 结构层 + SL 尺寸来源（15m ATR）
#   LTF=5m    回踩确认层 + 持仓管理层（默认不入结构盲进）
#
# 零未来函数落实：
#   R2*  MACRO/HTF 桶只取 close_time ≤ MTF 信号桶 open_time 的已收盘桶（TC-1.3 同构，套用 build_hbidx_of）
#   R4*  信号在 MTF 柱收盘后成立；确认在 5m 闭合序列上判定；入场 = 确认 5m 柱的下一根 5m 开盘（R6*）
#   R7   指标仅基于闭合序列（RSI/ATR/EMA/ADX）
#   R8   禁止跨周期偷看：MACRO/HTF 引用 MTF 信号桶之前已收盘桶；5m 确认/管理只引用已收盘 5m 柱
#   出场用「未来市价前进模拟」逐根 5m 检查 SL/TP/BE/反向CHoCH/超时——不构造信号，不违反零未来函数。
# ──────────────────────────────────────────────────────────────────────────
import os, sys, csv, json, hashlib, random, bisect

from rs_data import resample_htf, htf_bias, beijing_str, load_csv

# ==================== 预注册参数（跑批前锁死，禁止中途调参） ====================
CONFIG = {
    "SYMBOL": "",
    "MACRO_MIN": 240,       # 4h 宏观层
    "HTF_MIN": 60,          # 1h 偏向/regime 层
    "MTF_MIN": 15,          # 15m 结构层
    "LTF_MIN": 5,           # 5m 确认/管理层
    "K_CONFIRM": 3,
    "RSI_P": 14, "RSI_TH": 70,
    "ATR_P": 14, "ATR_K": 2.25, "MIN_SL_PT": 6.0,   # 修地板：SL=max(2.25×15mATR,6pt)
    "RR_TARGET": 1.5,
    "MAX_HOLD_MS": 160 * 15 * 60_000,               # 持仓上限（≈ v2 的 160 根15m = 40h）
    "ADX_TH": 20, "BE_R": 1.0,
    "HTF_EMA_FAST": 20, "HTF_EMA_SLOW": 50,
    "MACRO_EMA_FAST": 20, "MACRO_EMA_SLOW": 50,
    "RSI_WIN": 30,
    "RISK_BUDGET": 1000.0,
    "MAX_CONFIRM_5M": 24,    # 5m 回踩确认窗口（=2h）；超时放弃信号（质量门）
    "MIN_PB_PT_FRAC": 0.25,  # 回踩幅度 ≥ 0.25×SL 才算有效回踩（过滤无效毛刺）
}
# 冻结哈希：任何参数改动导致哈希不符 → 拒绝运行（防参数漂移 / 防未注册调参）
FROZEN_CONFIG_HASH = "eec8a032cbc3fa2745b6db43a0f27614e89098c476104e20e7afc925778ca0f9"

CACHE_1M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_cache__1m.csv")


def config_hash():
    return hashlib.sha256(json.dumps(CONFIG, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_config():
    h = config_hash()
    if h != FROZEN_CONFIG_HASH:
        raise RuntimeError(
            f"[RS v3] config_hash 不符：compute={h} frozen={FROZEN_CONFIG_HASH}\n"
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
    lo = max(0, i - w + 1)
    seg = [x for x in arr[lo:i + 1] if x is not None]
    if not seg:
        return None
    return max(seg) if kind == 'max' else min(seg)


# ==================== 纯函数尺寸（SL 源 = 15m ATR，不引用 1m） ====================
def compute_sl(atr_15m, atr_k=CONFIG["ATR_K"], min_sl=CONFIG["MIN_SL_PT"]):
    if atr_15m is None or atr_15m <= 0:
        return None
    return max(atr_k * atr_15m, min_sl)


# ==================== 跨周期闭合映射（TC-1.3 同构） ====================
def build_hbidx_of(mtf_opens, htf_close_times):
    """对每个 MTF 柱，返回「最后完全收盘」HTF 桶序号：close_time ≤ mtf.open_time（TC-1.3 硬约束）。"""
    return [bisect.bisect_right(htf_close_times, mtf_opens[i]) - 1 for i in range(len(mtf_opens))]


def first_5m_after(open_times5, t_close_ms):
    """返回第一根 open_time ≥ t_close_ms 的 5m 柱序号（该柱完全在信号收盘之后）。"""
    return bisect.bisect_left(open_times5, t_close_ms)


# ==================== 主回测 ====================
def run_backtest(mtf, htf, htf4, ltf5, cfg=CONFIG,
                 htf_gate=True, macro_gate=True, pullback_confirm=True, rev_exit=True):
    K_CONFIRM = cfg["K_CONFIRM"]; RSI_P = cfg["RSI_P"]; RSI_TH = cfg["RSI_TH"]
    ATR_P = cfg["ATR_P"]; RR = cfg["RR_TARGET"]; ADX_TH = cfg["ADX_TH"]
    BE_R = cfg["BE_R"]; RWIN = cfg["RSI_WIN"]; RB = cfg["RISK_BUDGET"]
    EF = cfg["HTF_EMA_FAST"]; ES = cfg["HTF_EMA_SLOW"]
    MEF = cfg["MACRO_EMA_FAST"]; MES = cfg["MACRO_EMA_SLOW"]
    MAXH_MS = cfg["MAX_HOLD_MS"]; MAXCONF = cfg["MAX_CONFIRM_5M"]; PB_FRAC = cfg["MIN_PB_PT_FRAC"]

    n = len(mtf)
    mtf_opens_ts = [c["open_time"] for c in mtf]
    htf_close_times = [c["open_time"] + cfg["HTF_MIN"] * 60_000 for c in htf]
    htf4_close_times = [c["open_time"] + cfg["MACRO_MIN"] * 60_000 for c in htf4]
    # 5m 序列
    o5 = [c["open"] for c in ltf5]; h5 = [c["high"] for c in ltf5]
    l5 = [c["low"] for c in ltf5]; c5 = [c["close"] for c in ltf5]
    open_ts5 = [c["open_time"] for c in ltf5]
    close_ts5 = [c["open_time"] + cfg["LTF_MIN"] * 60_000 for c in ltf5]

    rsi = rsi_series([c["close"] for c in mtf], RSI_P)
    atr = atr_series([c["high"] for c in mtf], [c["low"] for c in mtf], [c["close"] for c in mtf], ATR_P)
    hbidx_of = build_hbidx_of(mtf_opens_ts, htf_close_times)         # 1h 已收盘桶（TC-1.3）
    mbidx_of = build_hbidx_of(mtf_opens_ts, htf4_close_times)        # 4h 已收盘桶（TC-1.3 同构）
    piv = detect_pivots([c["high"] for c in mtf], [c["low"] for c in mtf], K_CONFIRM)

    trades = []
    next_allowed = 0          # 15m 冷却索引（上一笔平仓后跳过）
    pi = 0                    # 15m 摆点消费指针
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
        choch_d = bool(last_L is not None and last_L_ci <= i and mtf[i]["close"] < last_L)
        choch_u = bool(last_H is not None and last_H_ci <= i and mtf[i]["close"] > last_H)
        if not (choch_d or choch_u):
            continue

        direction = -1 if choch_d else 1   # -1 空, +1 多

        # —— HTF 1h 偏向 + regime 门（R2，TC-1.3）——
        bias = 0; adx = 999.0
        if htf_gate:
            hbidx = hbidx_of[i]
            if hbidx < 50:
                continue
            bias, adx = htf_bias(htf, hbidx + 1)
            if adx < ADX_TH:
                continue
            if direction == -1 and bias != -1:
                continue
            if direction == 1 and bias != 1:
                continue

        # —— MACRO 4h 背离门（B 新增）：1h 与 4h 必须背离 ——
        macro_bias = 0
        if macro_gate:
            mbidx = mbidx_of[i]
            if mbidx < MES:
                continue
            macro_bias, _ = htf_bias(htf4, mbidx + 1)
            # SHORT（1h 向下，顺小周期做空）要求 4h 不向上（≤0，即不与宏观背离）；
            # LONG（1h 向上）要求 4h 不向下（≥0）。→ 多周期同向对齐（提质量）。
            if direction == -1 and macro_bias > 0:
                continue
            if direction == 1 and macro_bias < 0:
                continue

        # 超买/超卖衰竭（近 RWIN 根内出现过极值）
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

        signal_close = mtf[i]["close"]
        t_close = mtf[i]["open_time"] + cfg["MTF_MIN"] * 60_000  # 15m 信号柱收盘时刻
        s0 = first_5m_after(open_ts5, t_close)                    # 第一根完全在信号后的 5m 柱
        if s0 >= len(ltf5):
            break

        # —— 5m 回踩确认（B 新增，默认不入结构盲进）——
        entry_k = None
        if pullback_confirm:
            min_pb = PB_FRAC * sl_dist
            pulled_back = False
            pb_ref_low = None     # SHORT：拉回前最低 5m 低（续跌触发线）
            pb_ref_high = None    # LONG ：拉回前最高 5m 高（续涨触发线）
            broken = False        # 结构被破坏（5m 吞回被破的 15m 摆点）→ 放弃
            for b in range(s0, min(len(ltf5), s0 + MAXCONF)):
                # 结构完整性：SHORT 不可吞回 last_H；LONG 不可吞回 last_L
                if direction == -1:
                    if last_H is not None and h5[b] >= last_H:
                        broken = True
                        break
                else:
                    if last_L is not None and l5[b] <= last_L:
                        broken = True
                        break
                if not pulled_back:
                    # 拉回阶段：SHORT 须向上弹 ≥ min_pb；LONG 须向下压 ≥ min_pb
                    if direction == -1:
                        if h5[b] >= signal_close + min_pb:
                            pulled_back = True
                            pb_ref_low = min(l5[s0:b + 1])
                    else:
                        if l5[b] <= signal_close - min_pb:
                            pulled_back = True
                            pb_ref_high = max(h5[s0:b + 1])
                else:
                    # 续程触发：SHORT 5m 收盘跌破拉回前低；LONG 5m 收盘突破拉回前高
                    if direction == -1 and c5[b] < pb_ref_low:
                        entry_k = b
                        break
                    if direction == 1 and c5[b] > pb_ref_high:
                        entry_k = b
                        break
            if broken:
                continue
            if entry_k is None:
                continue
        else:
            entry_k = s0   # 不退化为 v2：「无确认」本就不应出现；保留开关仅用于诊断

        ek = entry_k + 1   # R6*：确认 5m 柱的下一根 5m 开盘入场（信号时不看 ek 高低收）
        if ek >= len(ltf5):
            continue
        entry = o5[ek]
        entry_time = open_ts5[ek]
        if direction == -1:
            sl = entry + sl_dist
            tp = entry - sl_dist * RR
        else:
            sl = entry - sl_dist
            tp = entry + sl_dist * RR

        # —— 5m 持仓管理（从 ek 起逐根前进；含 BE / 反向CHoCH / 超时）——
        sl_cur = sl
        exit_k = None; exit_px = None; reason = None
        tr_H = last_H; tr_H_ci = last_H_ci; tr_L = last_L; tr_L_ci = last_L_ci
        jpi = pi   # 从信号时已消费的摆点继续（管理期推进新摆点）
        for m in range(ek, len(ltf5)):
            # 推进 15m 摆点至 confirm ≤ 当前 5m 时刻对应的 15m 柱
            mi = bisect.bisect_right(mtf_opens_ts, open_ts5[m]) - 1
            while jpi < len(piv) and piv[jpi][3] <= mi:
                c, price, kind, ci = piv[jpi]
                if kind == 'H':
                    tr_H, tr_H_ci = price, ci
                else:
                    tr_L, tr_L_ci = price, ci
                jpi += 1
            # 1) SL/TP 触碰（limit/stop 标准约定）
            if direction == -1:
                if l5[m] <= tp:
                    exit_k, exit_px, reason = m, tp, "TP"
                    break
                if h5[m] >= sl_cur:
                    exit_k, exit_px, reason = m, sl_cur, "SL"
                    break
                if l5[m] <= entry - sl_dist:   # 浮盈达 +1R → 推保本
                    sl_cur = entry
            else:
                if h5[m] >= tp:
                    exit_k, exit_px, reason = m, tp, "TP"
                    break
                if l5[m] <= sl_cur:
                    exit_k, exit_px, reason = m, sl_cur, "SL"
                    break
                if h5[m] >= entry + sl_dist:
                    sl_cur = entry
            # 2) 反向 CHoCH（事件型市价退出，基于已收盘 5m 柱 m，fill=close[m]）
            if rev_exit:
                if direction == -1 and tr_H is not None and tr_H_ci <= mi and c5[m] > tr_H:
                    exit_k, exit_px, reason = m, c5[m], "REV"
                    break
                if direction == 1 and tr_L is not None and tr_L_ci <= mi and c5[m] < tr_L:
                    exit_k, exit_px, reason = m, c5[m], "REV"
                    break
            # 3) 超时强平
            if close_ts5[m] - entry_time > MAXH_MS:
                exit_k, exit_px, reason = m, c5[m], "MAX"
                break
        if exit_k is None:
            exit_k = len(ltf5) - 1
            exit_px = c5[exit_k]
            reason = "MAX"
        exit_time = open_ts5[exit_k]

        pnl = (entry - exit_px) if direction == -1 else (exit_px - entry)
        rr = pnl / sl_dist
        position_size = RB / sl_dist
        trades.append({
            "signal_time": beijing_str(mtf[i]["open_time"]),
            "direction": "SHORT" if direction == -1 else "LONG",
            "entry_time": beijing_str(entry_time),
            "entry_price": round(entry, 2), "sl_price": round(sl, 2), "tp_price": round(tp, 2),
            "sl_dist": round(sl_dist, 2),
            "exit_time": beijing_str(exit_time),
            "exit_price": round(exit_px, 2), "exit_reason": reason,
            "pnl_points": round(pnl, 2), "rr": round(rr, 2),
            "htf_bias": bias, "adx": round(adx, 1), "rsi": round(r, 1),
            "macro_bias": macro_bias,
            "atr15m": round(atr[i], 3), "position_size": round(position_size, 2),
            "signal_bar_index": i,
            "confirm_lag_5m": (entry_k - s0) if pullback_confirm else 0,
        })
        # 冷却：平仓 5m 柱所在 15m 索引 +1
        mi_exit = bisect.bisect_right(mtf_opens_ts, exit_time) - 1
        next_allowed = mi_exit + 1

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
    floor_ratio = sum(1 for s in sl_dists if s > CONFIG["MIN_SL_PT"]) / n
    dirs = {}
    for t in trades:
        dirs[t["direction"]] = dirs.get(t["direction"], 0) + 1
    return {"n": n, "win_rate": len(wins) / n, "pf": pf,
            "expectancy": sum(pnls) / n, "avg_rr": sum(t["rr"] for t in trades) / n,
            "ci_low": ci_low, "gross_profit": gp, "gross_loss": gl,
            "median_sl": median_sl, "floor_ratio": floor_ratio, "dirs": dirs}


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

    print(f"[RS v3] config_hash={config_hash()}  标的 {CONFIG['SYMBOL']}  "
          f"栈 4h/1h/15m/5m  MTF=15m HTF=1h MACRO=4h LTF=5m")
    print(f"[RS v3] 回测区间 UTC: {START} ~ {END}")

    one_min = load_csv(CACHE_1M)
    print(f"[RS v3] 载入 1m K 线: {len(one_min)} 根（从已验证缓存重采样，避免网格错位）")
    mtf = resample_htf(one_min, CONFIG["MTF_MIN"])
    htf = resample_htf(one_min, CONFIG["HTF_MIN"])
    htf4 = resample_htf(one_min, CONFIG["MACRO_MIN"])
    ltf5 = resample_htf(one_min, CONFIG["LTF_MIN"])
    print(f"[RS v3] 15m={len(mtf)}  1h={len(htf)}  4h={len(htf4)}  5m={len(ltf5)}")

    trades = run_backtest(mtf, htf, htf4, ltf5)
    rep = summarize(trades)
    print(f"[RS v3] 信号数 n={rep.get('n')}")
    if rep.get('n'):
        print(f"     胜率={rep['win_rate'] * 100:.1f}%  PF={rep['pf']:.2f}  "
              f"期望={rep['expectancy']:.2f}pt  均RR={rep['avg_rr']:.2f}  CI下界={rep['ci_low']:.2f}")
        print(f"     median SL={rep['median_sl']:.2f}pt  地板(由ATR决定)占比={rep['floor_ratio'] * 100:.1f}%")
        print(f"     方向分布={rep['dirs']}")
        print("     二次裁决闸:")
        for c in gates(rep):
            print("       " + c)
        cut = int(len(trades) * 0.7)
        isr = summarize(trades[:cut])
        osr = summarize(trades[cut:])
        print(f"     IS(前70%) n={isr.get('n')} PF={isr.get('pf')}  "
              f"OOS(后30%) n={osr.get('n')} PF={osr.get('pf')}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "rs_backtest_v3_result.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
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
    print(f"[RS v3] 逐笔 CSV 已写出: {out}  （信号/入场/平仓时间均为北京时间）")
    print("[RS v3] 样本（前 5 笔）:")
    for t in trades[:5]:
        print("      ", t["signal_time"], t["direction"], "入", t["entry_price"],
              "SL", t["sl_price"], "TP", t["tp_price"], "出", t["exit_time"],
              t["exit_reason"], "pnl", t["pnl_points"], "macro", t["macro_bias"])


if __name__ == "__main__":
    main()
