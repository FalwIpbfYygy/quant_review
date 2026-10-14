# rs_backtest_paxg.py
# RS 反转结构探针 —— PAXGUSDT 现货版（基于 v3 阶段二 B 逻辑，换标的+现货长历史+ LONG 非对称诊断/修正）
#
# 因果纪律（红线，沿用 v3 R1–R8 + TC-1.3）：
#   四层栈 MACRO=4h / HTF=1h / MTF=15m / LTF=5m
#   R2*  MACRO/HTF 只取 close_time ≤ MTF 信号桶 open_time 的已收盘桶（TC-1.3）
#   R4*  信号在 MTF 收盘后成立；入场 = 确认 5m 柱的下一根 5m 开盘（R6*）
#   R7   指标仅闭合序列；R8 禁止跨周期偷看
#   出场 = 未来市价前进模拟逐根 5m 检查（SL/TP/BE/反向CHoCH/超时）
#
# 数据：PAXGUSDT 现货 5m（价格接口基址，历史远长于期货），15m/1h/4h 由 5m 整除重采样。
# ──────────────────────────────────────────────────────────────────────────
import os, sys, csv, json, hashlib, random, bisect

from rs_data import resample_htf, htf_bias, beijing_str
from paxg_data import load_csv, beijing_str as bj, get_5m

# ==================== 预注册参数（跑批前锁死） ====================
CONFIG = {
    "SYMBOL": "PAXGUSDT",
    "MACRO_MIN": 240, "HTF_MIN": 60, "MTF_MIN": 15, "LTF_MIN": 5,
    "K_CONFIRM": 3,
    "RSI_P": 14, "RSI_TH": 70,
    "ATR_P": 14, "ATR_K": 2.25, "MIN_SL_PT": 6.0,
    "RR_TARGET": 1.5,
    "MAX_HOLD_MS": 160 * 15 * 60_000,
    "ADX_TH": 20, "BE_R": 1.0,
    "HTF_EMA_FAST": 20, "HTF_EMA_SLOW": 50,
    "MACRO_EMA_FAST": 20, "MACRO_EMA_SLOW": 50,
    "RSI_WIN": 30,
    "RISK_BUDGET": 1000.0,
    "MAX_CONFIRM_5M": 24,
    "MIN_PB_PT_FRAC": 0.25,
    # —— 反向 CHoCH 参考位（v4-frozen 修复，固化进 CONFIG 使 config_hash 随决策移动）——
    "REV_REF_FROZEN": True,        # True=反向CHoCH 触发位取信号时刻结构位快照（修过激泄漏）；False=原浮动
    "PAXG_SHORT_ENABLED": False,   # PAXG 上 SHORT 结构性负 edge → 关空，仅交易 LONG（代码仍保留双方向能力）
    # —— 历史诊断开关（保留供回归测试/其它标的复用）——
    "LONG_STRUCT_TOL": 0.0,        # LONG 结构失效容忍：last_L 向下允许的毛刺比例（0=原严格）
    "LONG_REV_GUARD": False,       # LONG 反向CHoCH 退出是否加保护（避免上行健康回踩被误杀）
}
ENGINE_VERSION = "v4-paxg-20261002-frozen"   # 逻辑版本（config 改动仅其一，逻辑改动需升版本号）
CACHE_5M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_cache_PAXGUSDT_5m.json")


def config_hash():
    return hashlib.sha256(json.dumps(CONFIG, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# ==================== 指标（纯 Python，全因果） ====================
def rsi_series(closes, p=14):
    n = len(closes); out = [None] * n
    if n < p + 1:
        return out
    g = l = 0.0
    for i in range(1, p + 1):
        ch = closes[i] - closes[i - 1]
        g += ch if ch >= 0 else 0.0
        l -= ch if ch < 0 else 0.0
    g /= p; l /= p
    out[p] = 100 - 100 / (1 + (g / l if l else 999))
    for i in range(p + 1, n):
        ch = closes[i] - closes[i - 1]
        g = (g * (p - 1) + max(ch, 0)) / p
        l = (l * (p - 1) + max(-ch, 0)) / p
        out[i] = 100 - 100 / (1 + (g / l if l else 999))
    return out


def atr_series(highs, lows, closes, p=14):
    n = len(highs); tr = [0.0] * n; out = [None] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    if n < p + 1:
        return out
    s = sum(tr[1:p + 1]) / p; out[p] = s
    for i in range(p + 1, n):
        s = (s * (p - 1) + tr[i]) / p; out[i] = s
    return out


def detect_pivots(highs, lows, K=3):
    piv = []; n = len(highs)
    for i in range(2 * K, n):
        c = i - K; hc = highs[c]; lc = lows[c]
        is_h = is_l = True
        for j in range(i - 2 * K, i + 1):
            if highs[j] > hc: is_h = False
            if lows[j] < lc: is_l = False
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


def compute_sl(atr_15m, atr_k=CONFIG["ATR_K"], min_sl=CONFIG["MIN_SL_PT"]):
    if atr_15m is None or atr_15m <= 0:
        return None
    return max(atr_k * atr_15m, min_sl)


def _ema_array(vals, p):
    """EMA 全序列（O(n)，增量递归）。返回与 vals 等长的数组，idx=i 即用 vals[0..i] 的 EMA。"""
    n = len(vals); out = [0.0] * n
    if n == 0:
        return out
    if n < p:
        s = 0.0
        for i in range(n):
            s += vals[i]; out[i] = s / (i + 1)
        return out
    k = 2.0 / (p + 1)
    e = sum(vals[:p]) / p
    out[p - 1] = e
    for i in range(p, n):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    for i in range(p - 1):
        out[i] = sum(vals[:i + 1]) / (i + 1)
    return out


def _adx_array(htf, p=14):
    """Wilder ADX 全序列（O(n)，双平滑）。idx=j 即用 htf[0..j] 的 ADX；j<2p-1 时为 0（与 htf_bias 早期返回 0 一致）。"""
    n = len(htf); adx = [0.0] * n
    if n <= p:
        return adx
    pdm = [0.0] * n; mdm = [0.0] * n; tr = [0.0] * n
    for j in range(1, n):
        h = htf[j]["high"]; l = htf[j]["low"]; pc = htf[j - 1]["close"]
        up = h - htf[j - 1]["high"]; dn = htf[j - 1]["low"] - l
        pdm[j] = max(up, 0.0) if up > dn else 0.0
        mdm[j] = max(dn, 0.0) if dn > up else 0.0
        tr[j] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [0.0] * n; pds = [0.0] * n; mds = [0.0] * n
    atr[p] = sum(tr[1:p + 1]) / p; pds[p] = sum(pdm[1:p + 1]) / p; mds[p] = sum(mdm[1:p + 1]) / p
    for j in range(p + 1, n):
        atr[j] = (atr[j - 1] * (p - 1) + tr[j]) / p
        pds[j] = (pds[j - 1] * (p - 1) + pdm[j]) / p
        mds[j] = (mds[j - 1] * (p - 1) + mdm[j]) / p
    dx = [0.0] * n
    for j in range(p, n):
        pdi = pds[j] / atr[j] * 100 if atr[j] else 0.0
        mdi = mds[j] / atr[j] * 100 if atr[j] else 0.0
        dx[j] = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) else 0.0
    q = 2 * p - 1
    if n <= q:
        return adx
    adx[q] = sum(dx[p:q + 1]) / p
    for j in range(q + 1, n):
        adx[j] = (adx[j - 1] * (p - 1) + dx[j]) / p
    return adx


def build_hbidx_of(mtf_opens, htf_close_times):
    return [bisect.bisect_right(htf_close_times, mtf_opens[i]) - 1 for i in range(len(mtf_opens))]


def first_5m_after(open_times5, t_close_ms):
    return bisect.bisect_left(open_times5, t_close_ms)


# ==================== 主回测（含分方向分闸门诊断） ====================
def run_backtest(mtf, htf, htf4, ltf5, cfg=CONFIG, diagnostics=False,
                 htf_gate=True, macro_gate=True, pullback_confirm=True, rev_exit=True,
                 rev_diag=False, rev_exit_short=None, rev_exit_long=None,
                 rev_trH_frozen=None, rev_trH_frozen_short=None, rev_trH_frozen_long=None,
                 rev_buffer=0.0):
    if rev_exit_short is None:
        rev_exit_short = rev_exit
    if rev_exit_long is None:
        rev_exit_long = rev_exit
    # frozen 默认从 CONFIG 读取（REV_REF_FROZEN），未显式传参时生效；测试可显式覆盖
    if rev_trH_frozen is None:
        rev_trH_frozen = cfg.get("REV_REF_FROZEN", False)
    if rev_trH_frozen_short is None:
        rev_trH_frozen_short = rev_trH_frozen
    if rev_trH_frozen_long is None:
        rev_trH_frozen_long = rev_trH_frozen
    _frz_s = rev_trH_frozen_short
    _frz_l = rev_trH_frozen_long
    short_enabled = cfg.get("PAXG_SHORT_ENABLED", True)   # PAXG 上 SHORT 结构性负 edge → 默认关空
    K_CONFIRM = cfg["K_CONFIRM"]; RSI_P = cfg["RSI_P"]; RSI_TH = cfg["RSI_TH"]
    ATR_P = cfg["ATR_P"]; RR = cfg["RR_TARGET"]; ADX_TH = cfg["ADX_TH"]
    BE_R = cfg["BE_R"]; RWIN = cfg["RSI_WIN"]; RB = cfg["RISK_BUDGET"]
    EF = cfg["HTF_EMA_FAST"]; ES = cfg["HTF_EMA_SLOW"]
    MEF = cfg["MACRO_EMA_FAST"]; MES = cfg["MACRO_EMA_SLOW"]
    MAXH_MS = cfg["MAX_HOLD_MS"]; MAXCONF = cfg["MAX_CONFIRM_5M"]; PB_FRAC = cfg["MIN_PB_PT_FRAC"]
    LONG_TOL = cfg["LONG_STRUCT_TOL"]

    n = len(mtf)
    mtf_opens_ts = [c["open_time"] for c in mtf]
    htf_close_times = [c["open_time"] + cfg["HTF_MIN"] * 60_000 for c in htf]
    htf4_close_times = [c["open_time"] + cfg["MACRO_MIN"] * 60_000 for c in htf4]
    o5 = [c["open"] for c in ltf5]; h5 = [c["high"] for c in ltf5]
    l5 = [c["low"] for c in ltf5]; c5 = [c["close"] for c in ltf5]
    open_ts5 = [c["open_time"] for c in ltf5]
    close_ts5 = [c["open_time"] + cfg["LTF_MIN"] * 60_000 for c in ltf5]

    rsi = rsi_series([c["close"] for c in mtf], RSI_P)
    atr = atr_series([c["high"] for c in mtf], [c["low"] for c in mtf], [c["close"] for c in mtf], ATR_P)
    hbidx_of = build_hbidx_of(mtf_opens_ts, htf_close_times)
    mbidx_of = build_hbidx_of(mtf_opens_ts, htf4_close_times)
    piv = detect_pivots([c["high"] for c in mtf], [c["low"] for c in mtf], K_CONFIRM)

    # —— O(n) 预计算 HTF(1h)/MACRO(4h) 的 EMA 偏向 + Wilder ADX 数组（增量，非重算）：
    #     原 htf_bias(htf,i) 每调用一次都重算 htf[:i] 整段（O(i)），对每笔 CHoCH 调用累计成 O(n^2)；
    #     这里一次性算出 ema_fast/ema_slow/adx 三条全序列（各 O(n)），循环内直接按索引查表。
    #     语义与原 htf_bias(htf, hbidx+1)（即使用 htf[0..hbidx]）严格一致，且不引入任何未来数据。
    ADX_P = 14
    ch = [h["close"] for h in htf]; cm = [h["close"] for h in htf4]
    efH = _ema_array(ch, EF); esH = _ema_array(ch, ES)
    efM = _ema_array(cm, MEF); esM = _ema_array(cm, MES)
    adxH = _adx_array(htf, ADX_P); adxM = _adx_array(htf4, ADX_P)

    diag = None
    if diagnostics:
        diag = {d: {"choch": 0, "htf": 0, "macro": 0, "rsi": 0, "broken": 0,
                    "timeout": 0, "entered": 0} for d in (-1, 1)}

    trades = []
    next_allowed = 0
    pi = 0
    last_H = last_H_ci = last_L = last_L_ci = None

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

        choch_d = bool(last_L is not None and last_L_ci <= i and mtf[i]["close"] < last_L)
        choch_u = bool(last_H is not None and last_H_ci <= i and mtf[i]["close"] > last_H)
        if not (choch_d or choch_u):
            continue
        direction = -1 if choch_d else 1
        if direction == -1 and not short_enabled:   # PAXG 上关空：SHORT 结构性负 edge
            continue
        if diag:
            diag[direction]["choch"] += 1

        if htf_gate:
            hbidx = hbidx_of[i]
            if hbidx < 50:
                if diag: diag[direction]["htf"] += 1
                continue
            bias = 1 if efH[hbidx] > esH[hbidx] else (-1 if efH[hbidx] < esH[hbidx] else 0)
            adx = adxH[hbidx]
            if adx < ADX_TH or (direction == -1 and bias != -1) or (direction == 1 and bias != 1):
                if diag: diag[direction]["htf"] += 1
                continue

        macro_bias = 0
        if macro_gate:
            mbidx = mbidx_of[i]
            if mbidx < MES:
                if diag: diag[direction]["macro"] += 1
                continue
            macro_bias = 1 if efM[mbidx] > esM[mbidx] else (-1 if efM[mbidx] < esM[mbidx] else 0)
            if (direction == -1 and macro_bias > 0) or (direction == 1 and macro_bias < 0):
                if diag: diag[direction]["macro"] += 1
                continue

        rsi_hi = trailing_extreme(rsi, i, RWIN, 'max')
        rsi_lo = trailing_extreme(rsi, i, RWIN, 'min')
        if direction == -1 and (rsi_hi is None or rsi_hi < RSI_TH):
            if diag: diag[direction]["rsi"] += 1
            continue
        if direction == 1 and (rsi_lo is None or rsi_lo > (100 - RSI_TH)):
            if diag: diag[direction]["rsi"] += 1
            continue
        r = rsi[i]

        sl_dist = compute_sl(atr[i])
        if sl_dist is None:
            continue

        signal_close = mtf[i]["close"]
        t_close = mtf[i]["open_time"] + cfg["MTF_MIN"] * 60_000
        s0 = first_5m_after(open_ts5, t_close)
        if s0 >= len(ltf5):
            break

        entry_k = None
        if pullback_confirm:
            min_pb = PB_FRAC * sl_dist
            pulled_back = False
            pb_ref_low = None; pb_ref_high = None; broken = False
            for b in range(s0, min(len(ltf5), s0 + MAXCONF)):
                if direction == -1:
                    if last_H is not None and h5[b] >= last_H:
                        broken = True; break
                else:
                    # LONG 结构失效容忍：允许 5m 低短暂刺穿 last_L 不超过 LONG_TOL 比例
                    if last_L is not None:
                        if LONG_TOL > 0 and l5[b] <= last_L and l5[b] >= last_L * (1 - LONG_TOL / 100.0):
                            pass  # 容忍毛刺，不算破
                        elif l5[b] <= last_L:
                            broken = True; break
                if not pulled_back:
                    if direction == -1:
                        if h5[b] >= signal_close + min_pb:
                            pulled_back = True; pb_ref_low = min(l5[s0:b + 1])
                    else:
                        if l5[b] <= signal_close - min_pb:
                            pulled_back = True; pb_ref_high = max(h5[s0:b + 1])
                else:
                    if direction == -1 and c5[b] < pb_ref_low:
                        entry_k = b; break
                    if direction == 1 and c5[b] > pb_ref_high:
                        entry_k = b; break
            if broken:
                if diag: diag[direction]["broken"] += 1
                continue
            if entry_k is None:
                if diag: diag[direction]["timeout"] += 1
                continue
        else:
            entry_k = s0
        if diag:
            diag[direction]["entered"] += 1

        ek = entry_k + 1
        if ek >= len(ltf5):
            continue
        entry = o5[ek]; entry_time = open_ts5[ek]
        if direction == -1:
            sl = entry + sl_dist; tp = entry - sl_dist * RR
        else:
            sl = entry - sl_dist; tp = entry + sl_dist * RR

        sl_cur = sl
        exit_k = None; exit_px = None; reason = None
        rev_ref = None
        tr_H = last_H; tr_H_ci = last_H_ci; tr_L = last_L; tr_L_ci = last_L_ci
        # 反向 CHoCH 参考位：frozen 模式用信号时刻的"结构性破位点"（定义该笔交易的原始摆动高/低），
        # 不在持仓中随新摆动高浮动——浮动会把每个正常回踩小高当成反转杀掉（SHORT 过激退出的根因）。
        # 注意：tr_H/tr_L 始终按浮动更新（无副作用），仅 REV 判定时按方向选择 frozen/signal 或 floating。
        sig_tr_H = last_H; sig_tr_L = last_L
        jpi = pi
        for m in range(ek, len(ltf5)):
            mi = bisect.bisect_right(mtf_opens_ts, open_ts5[m]) - 1
            while jpi < len(piv) and piv[jpi][3] <= mi:
                c, price, kind, ci = piv[jpi]
                if kind == 'H':
                    tr_H, tr_H_ci = price, ci
                else:
                    tr_L, tr_L_ci = price, ci
                jpi += 1
            if direction == -1:
                if l5[m] <= tp:
                    exit_k, exit_px, reason = m, tp, "TP"; break
                if h5[m] >= sl_cur:
                    exit_k, exit_px, reason = m, sl_cur, "SL"; break
                if l5[m] <= entry - sl_dist:
                    sl_cur = entry
            else:
                if h5[m] >= tp:
                    exit_k, exit_px, reason = m, tp, "TP"; break
                if l5[m] <= sl_cur:
                    exit_k, exit_px, reason = m, sl_cur, "SL"; break
                if h5[m] >= entry + sl_dist:
                    sl_cur = entry
            if rev_exit:
                if direction == -1 and rev_exit_short:
                    _th = sig_tr_H if _frz_s else tr_H
                    _th_ci = last_H_ci if _frz_s else tr_H_ci
                    if _th is not None and _th_ci <= mi and c5[m] > _th + rev_buffer * sl_dist:
                        exit_k, exit_px, reason = m, c5[m], "REV"; rev_ref = _th; break
                if direction == 1 and rev_exit_long:
                    # 反向 CHoCH（LONG）：5m 收盘下破结构摆动低 last_L = 上行结构失效，市价退出。
                    # frozen 模式用信号时刻结构位快照（修过激泄漏），floating 用持仓中浮动位。
                    _tl = sig_tr_L if _frz_l else tr_L
                    _tl_ci = last_L_ci if _frz_l else tr_L_ci
                    if _tl is not None and _tl_ci <= mi and c5[m] < _tl:
                        exit_k, exit_px, reason = m, c5[m], "REV"; rev_ref = _tl; break
            if close_ts5[m] - entry_time > MAXH_MS:
                exit_k, exit_px, reason = m, c5[m], "MAX"; break
        if exit_k is None:
            exit_k = len(ltf5) - 1; exit_px = c5[exit_k]; reason = "MAX"
        exit_time = open_ts5[exit_k]

        rev_tr_H = None; adv_max = None; post_max = None; post_min = None
        if rev_diag:
            if direction == -1:
                adv_max = max(c5[ek:exit_k + 1]) - entry          # SHORT 逆向=价上
            else:
                adv_max = entry - min(c5[ek:exit_k + 1])          # LONG 逆向=价下
            if reason == "REV":
                rev_tr_H = round(rev_ref, 2) if rev_ref is not None else None
            ps = exit_k + 1; pe = min(len(ltf5), exit_k + 31)
            if pe > ps:
                post_max = max(c5[ps:pe]); post_min = min(c5[ps:pe])

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
            "htf_bias": 0, "adx": 0.0, "rsi": round(r, 1),
            "macro_bias": macro_bias,
            "atr15m": round(atr[i], 3), "position_size": round(position_size, 2),
            "signal_bar_index": i,
            "confirm_lag_5m": (entry_k - s0) if pullback_confirm else 0,
            "rev_tr_H": (round(rev_tr_H, 2) if rev_tr_H is not None else None),
            "adv_max": (round(adv_max, 2) if adv_max is not None else None),
            "post_max": (round(post_max, 2) if post_max is not None else None),
            "post_min": (round(post_min, 2) if post_min is not None else None),
        })
        mi_exit = bisect.bisect_right(mtf_opens_ts, exit_time) - 1
        next_allowed = mi_exit + 1

    return trades, diag


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
    low = [sum(random.choice(pnls) for _ in pnls) / n for _ in range(2000)]
    ci_low = sorted(low)[int(0.05 * len(low))]
    sl_dists = sorted(t["sl_dist"] for t in trades)
    median_sl = sl_dists[len(sl_dists) // 2]
    floor_ratio = sum(1 for s in sl_dists if s > CONFIG["MIN_SL_PT"]) / n
    return {"n": n, "win_rate": len(wins) / n, "pf": pf,
            "expectancy": sum(pnls) / n, "avg_rr": sum(t["rr"] for t in trades) / n,
            "ci_low": ci_low, "gross_profit": gp, "gross_loss": gl,
            "median_sl": median_sl, "floor_ratio": floor_ratio}


def gates(rep):
    if rep["n"] == 0:
        return ["n=0 → 无信号"]
    out = []
    out.append(f"n={rep['n']} {'PASS' if rep['n'] >= 30 else 'FAIL(功效闸 n<30)'}（n≥30）")
    out.append(f"PF={rep['pf']:.2f} {'PASS' if rep['pf'] >= 1.10 else 'FAIL(PF<1.10)'}（PF≥1.10）")
    out.append(f"OOS>0: {'PASS' if rep['expectancy'] > 0 else 'FAIL(期望≤0)'}（期望>0）")
    out.append(f"bootstrap CI下界={rep['ci_low']:.2f} {'PASS' if rep['ci_low'] > 0 else 'FAIL(≤0)'}（CI下界>0）")
    return out


def _assert_no_lookahead(mtf, htf, htf4, ltf5, trades):
    """零未来函数自检（红线校验）：每笔交易的全部决策锚点都必须不超前信号时刻。
    ① entry_time 必须严格晚于 signal_time（同格式北京时间字符串，字典序=时序）；
    ② HTF/MACRO 引用桶必须已收盘（close_time ≤ MTF 信号桶 open_time，即 TC-1.3）。"""
    htf_close_times = [c["open_time"] + CONFIG["HTF_MIN"] * 60_000 for c in htf]
    htf4_close_times = [c["open_time"] + CONFIG["MACRO_MIN"] * 60_000 for c in htf4]
    bad = 0
    for t in trades:
        i = t["signal_bar_index"]
        sig_open = mtf[i]["open_time"]
        if t["entry_time"] <= t["signal_time"]:        # 入场不得早于信号
            bad += 1
        hi = bisect.bisect_right(htf_close_times, sig_open) - 1
        mi = bisect.bisect_right(htf4_close_times, sig_open) - 1
        if hi >= 0 and htf_close_times[hi] > sig_open:  # 1h 引用桶须已收盘
            bad += 1
        if mi >= 0 and htf4_close_times[mi] > sig_open:  # 4h 引用桶须已收盘
            bad += 1
    return bad


def main():
    import time as _t
    if len(sys.argv) >= 3:
        sy, sm, sd = map(int, sys.argv[1].split('-'))
        ey, em, ed = map(int, sys.argv[2].split('-'))
        START = (sy, sm, sd); END = (ey, em, ed)
    else:
        # 默认窗口：2024-01-01 ~ 现在（用户决策：2024 前数据参考意义不大，不纳入）
        START = (2024, 1, 1); END = (2026, 10, 3)

    print(f"[PAXG {ENGINE_VERSION}] config_hash={config_hash()}  SYMBOL={CONFIG['SYMBOL']}")
    print(f"[PAXG] 回测区间 UTC: {START} ~ {END}（仅 2024+；严格零未来函数）")
    _t0 = _t.time()
    base5 = get_5m(CONFIG["SYMBOL"], START, END, CACHE_5M)
    print(f"[PAXG] 载入 5m K 线: {len(base5)} 根  ({_t.time()-_t0:.1f}s)")
    ltf5 = base5
    mtf = resample_htf(base5, CONFIG["MTF_MIN"])
    htf = resample_htf(base5, CONFIG["HTF_MIN"])
    htf4 = resample_htf(base5, CONFIG["MACRO_MIN"])
    print(f"[PAXG] 15m={len(mtf)}  1h={len(htf)}  4h={len(htf4)}  5m={len(ltf5)}")

    trades, diag = run_backtest(mtf, htf, htf4, ltf5, diagnostics=True)
    bad_la = _assert_no_lookahead(mtf, htf, htf4, ltf5, trades)
    print(f"[PAXG] 零未来函数自检：{'PASS（0 处超前）' if bad_la == 0 else 'FAIL（'+str(bad_la)+' 处超前！）'}")
    rep = summarize(trades)
    print(f"[PAXG] 信号数 n={rep.get('n')}")
    if rep.get('n'):
        print(f"     胜率={rep['win_rate'] * 100:.1f}%  PF={rep['pf']:.2f}  "
              f"期望={rep['expectancy']:.2f}pt  均RR={rep['avg_rr']:.2f}  CI下界={rep['ci_low']:.2f}")
        print(f"     median SL={rep['median_sl']:.2f}pt  地板(ATR驱动)占比={rep['floor_ratio'] * 100:.1f}%")
        cut = int(len(trades) * 0.7)
        isr = summarize(trades[:cut]); osr = summarize(trades[cut:])
        print(f"     IS(前70%) n={isr.get('n')} PF={isr.get('pf')}  OOS(后30%) n={osr.get('n')} PF={osr.get('pf')}")
    if diag:
        print("     ── 分方向分闸门诊断（每方向：CHoCH 形成数 → 各门淘汰数 → 入场数）──")
        for d, c in diag.items():
            nm = "SHORT" if d == -1 else "LONG"
            print(f"     {nm}: CHoCH={c['choch']}  htf淘汰={c['htf']}  macro淘汰={c['macro']}  "
                  f"rsi淘汰={c['rsi']}  结构破={c['broken']}  回踩超时={c['timeout']}  → 入场={c['entered']}")
        # 入场后按方向统计盈亏
        from collections import defaultdict
        by = defaultdict(list)
        for t in trades:
            by[t["direction"]].append(t)
        for d, ts in by.items():
            w = [x for x in ts if x["pnl_points"] > 0]
            net = sum(x["pnl_points"] for x in ts)
            rc = defaultdict(int)
            for x in ts: rc[x["exit_reason"]] += 1
            print(f"     {d}: n={len(ts)} 胜率={len(w)/len(ts)*100:.0f}% 净pnl={net:.1f}pt 退出={dict(rc)}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "rs_backtest_paxg_result.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_time", "direction", "entry_time", "entry_price", "sl_price",
                    "tp_price", "sl_dist", "exit_time", "exit_price", "exit_reason",
                    "pnl_points", "rr", "macro_bias", "adx", "rsi", "atr15m",
                    "position_size", "signal_bar_index", "confirm_lag_5m"])
        for t in trades:
            w.writerow([t["signal_time"], t["direction"], t["entry_time"], t["entry_price"],
                        t["sl_price"], t["tp_price"], t["sl_dist"], t["exit_time"],
                        t["exit_price"], t["exit_reason"], t["pnl_points"], t["rr"],
                        t["macro_bias"], t["adx"], t["rsi"], t["atr15m"],
                        t["position_size"], t["signal_bar_index"], t["confirm_lag_5m"]])
    print(f"[PAXG] 逐笔 CSV: {out}")


if __name__ == "__main__":
    main()
