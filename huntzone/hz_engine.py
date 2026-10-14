# -*- coding: utf-8 -*-
"""狩猎区战法 —— 核心引擎（对齐 wuyuan 正确「档位」结构，废弃 σ-波动率假设）。

档位口径（已确证，来源 PRD）：
    0.0 → 19.1 → 38.2 → 50.0 → 61.8 → 100.0 → 161.8 → 261.8 → 423.6
    比例  0   0.191  0.382  0.5   0.618   1.0    1.618   2.618   4.236

- 100.0 档 = 当日开盘价（锚）
- 0.0 档 = 腿端 / 中枢（= 开盘价 ± S；出自官方未公开的「中枢回归」层，本引擎不猜测 S）
- S = 跨度 = |0.0 档 − 开盘价|（回测时用官方卡反解作真值，实盘人工给定）
- 狩猎区 = [0.382, 0.618]（宽 0.236 × S）；止损 = 0.191 档；衰竭①=1.618、衰竭②=2.618
- 目标① = 昨收（独立规则，不落在斐波档上）

方向：顺势 = sign(昨收 − SMA/EMA(收盘, N))，N 可配。
"""
import statistics
from dataclasses import dataclass


# --------------------------------------------------------------------------
# 比例档位（铁律）
# --------------------------------------------------------------------------
LADDER = (
    (0.0, "0.0"), (0.191, "19.1"), (0.382, "38.2"), (0.500, "50.0"),
    (0.618, "61.8"), (0.809, "80.9"), (1.000, "100.0"),
    (1.618, "161.8"), (2.618, "261.8"), (4.236, "423.6"),
)
R_STOP = 0.191
R_ZONE_A = 0.382
R_ZONE_MID = 0.500
R_ZONE_B = 0.618
R_EXH1 = 1.618
R_EXH2 = 2.618

RESID_TOL_ABS = 1.0
RESID_TOL_REL = 0.02


@dataclass
class Config:
    """可配置参数。比例档位为铁律（模块常量），不在此放开。"""
    trend_period: int = 10
    trend_mode: str = "sma"      # "sma" | "ema"
    risk_pct: float = 1.0        # 单笔风险%（仅用于权益曲线口径）
    trend_filter: str = "ma3"    # 趋势过滤：None/""=关；"ma3"=SMA5/20/40 同向对齐才出信号
    vol_filter: float = 1.5      # 波动过滤：>0=前一日振幅>该倍数×近 vol_look 日均振幅则空仓；0=关
    vol_look: int = 10           # 波动过滤参考的日均振幅窗口
    cost_points: float = 0.0     # 交易成本(点/oz，点差+滑点)，在回测统计中按 |entry−stop| 扣减


SHORT_ALIASES = ("short", "空", "做空", "s", "sell")
LONG_ALIASES = ("long", "多", "做多", "l", "buy")


def norm_dir(direction):
    s = str(direction).strip().lower()
    if s in SHORT_ALIASES:
        return "short"
    if s in LONG_ALIASES:
        return "long"
    raise ValueError("无法识别的方向: %r" % (direction,))


# --------------------------------------------------------------------------
# 档位正解
# --------------------------------------------------------------------------
def price_at(ratio, open_px, S, direction):
    """第 ratio 档的价格（做空时 0.0 档在开盘价上方；做多时在下方）。"""
    if norm_dir(direction) == "short":
        return open_px + (1.0 - ratio) * S
    return open_px + (ratio - 1.0) * S


def build(open_px, S, direction, prev_close=None):
    """正解：由「开盘价 + 跨度 S + 方向」生成完整档位表（dict）。

    prev_close：昨收（目标①，可空）。做空时衰竭①高于昨收 / 做多时衰竭①低于昨收
    ⇒ 跳空特殊情况，跳过目标①直接走衰竭位。
    """
    if S is None or float(S) <= 0:
        raise ValueError("跨度 S 必须为正，收到 %r" % (S,))
    open_px = float(open_px)
    S = float(S)
    d = norm_dir(direction)
    sh = (d == "short")

    def f(r):
        return price_at(r, open_px, S, d)

    zone_a = f(R_ZONE_A)
    zone_b = f(R_ZONE_B)
    leg_start = f(0.0)
    open_end = f(1.0)
    stop = f(R_STOP)
    exh1 = f(R_EXH1)
    exh2 = f(R_EXH2)

    special = False
    if prev_close is not None:
        prev_close = float(prev_close)
        special = (exh1 > prev_close) if sh else (exh1 < prev_close)

    return {
        "direction": d,
        "direction_cn": "做空" if sh else "做多",
        "open_px": open_px,
        "S": S,
        "R": R_STOP * S,
        "leg_start": leg_start,                  # 0.0 档（腿端/中枢）
        "open_end": open_end,                    # 100.0 档 = 当日开盘价
        "stop": stop,
        "zone_hi": max(zone_a, zone_b),
        "zone_lo": min(zone_a, zone_b),
        "zone_mid": f(R_ZONE_MID),
        "exh1": exh1,
        "exh2": exh2,
        "t1": None if special else prev_close,   # 目标① = 昨收
        "prev_close": prev_close,
        "special_gap": special,
        "invalid_line": leg_start,               # 腿失效线 = 0.0 档
        "zone_width": abs(zone_a - zone_b),
        "entry_levels": sorted([zone_a, zone_b, f(R_ZONE_MID)]),
        "levels": [{"ratio": r, "name": n, "price": f(r)} for r, n in LADDER],
    }


# --------------------------------------------------------------------------
# 档位反解（官方公布值 → 跨度 S / 方向 / 完整档位）
# --------------------------------------------------------------------------
def _lsq(pairs):
    """最小二乘 price = a + b*ratio。"""
    if len(pairs) < 2:
        raise ValueError("至少需要两个档位")
    n = len(pairs)
    sx = sum(r for r, _ in pairs)
    sy = sum(v for _, v in pairs)
    sxx = sum(r * r for r, _ in pairs)
    sxy = sum(r * v for r, v in pairs)
    den = n * sxx - sx * sx
    if abs(den) < 1e-12:
        raise ValueError("档位退化")
    b = (n * sxy - sx * sy) / den
    return (sy - b * sx) / n, b


def _maxres(pairs, a, b):
    return max(abs(v - (a + b * r)) for r, v in pairs)


def invert(values, prev_close=None):
    """反解：官方公布的 3–5 个数值 → 跨度 S / 方向 / 完整档位。

    values 顺序：止损(0.191) / 区沿A(0.382) / 区沿B(0.618) / 衰竭①(1.618)[ / 衰竭②(2.618)]。
    官方卡存在「区沿上下互换」「衰竭①/② 印刷互换」等口径错位，故对 zone、衰竭各做
    swap 交叉尝试（2×2 组合），取残差最小者。
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n < 3 or n > 5:
        raise ValueError("反解需要 3–5 个数值，收到 %d 个" % n)

    if n == 3:
        base = [(R_ZONE_A, vals[0]), (R_ZONE_B, vals[1]), (R_EXH1, vals[2])]
        stop_v = None
    elif n == 4:
        base = [(R_STOP, vals[0]), (R_ZONE_A, vals[1]),
                (R_ZONE_B, vals[2]), (R_EXH1, vals[3])]
        stop_v = vals[0]
    else:
        base = [(R_STOP, vals[0]), (R_ZONE_A, vals[1]), (R_ZONE_B, vals[2]),
                (R_EXH1, vals[3]), (R_EXH2, vals[4])]
        stop_v = vals[0]

    best = None
    for zone_swap in (False, True):
        for exh_swap in (False, True):
            pairs = []
            for r, v in base:
                if r == R_ZONE_A and zone_swap:
                    r = R_ZONE_B
                elif r == R_ZONE_B and zone_swap:
                    r = R_ZONE_A
                if r == R_EXH1 and exh_swap:
                    r = R_EXH2
                elif r == R_EXH2 and exh_swap:
                    r = R_EXH1
                pairs.append((r, v))
            try:
                a, b = _lsq(pairs)
            except ValueError:
                continue
            err = _maxres(pairs, a, b)
            if best is None or err < best["err"]:
                best = {"err": err, "a": a, "b": b,
                        "zone_swap": zone_swap, "exh_swap": exh_swap}
    if best is None:
        return {"ok": False, "reason": "拟合失败：档位退化", "values": vals}

    a, b = best["a"], best["b"]
    S = abs(b)
    leg_start = a
    open_end = a + b
    d = "short" if b < 0 else "long"
    resid = best["err"]
    tol = max(RESID_TOL_ABS, RESID_TOL_REL * S)
    ok = resid <= tol

    return {
        "ok": ok,
        "reason": "" if ok else ("残差 %.2f 超容差 %.2f（占 S %.2f%%）"
                                 % (resid, tol, 100.0 * (resid / S if S else 0))),
        "values": vals,
        "S": S,
        "direction": d,
        "direction_cn": "做空" if d == "short" else "做多",
        "leg_start": leg_start,
        "open_end": open_end,
        "resid": resid,
        "resid_rel": (resid / S if S else float("inf")),
        "tol": tol,
        "zone_swap": best["zone_swap"],
        "exh_swap": best["exh_swap"],
        "ladder": build(open_end, S, d, prev_close=prev_close),
    }


# --------------------------------------------------------------------------
# 方向（顺势）
# --------------------------------------------------------------------------
def closes(bars):
    return [c for (_d, o, h, l, c) in bars]


def sma(vals, n):
    out = [None] * len(vals)
    if n <= 0:
        return out
    for i in range(n - 1, len(vals)):
        out[i] = sum(vals[i - n + 1:i + 1]) / n
    return out


def ema(vals, n):
    out = [None] * len(vals)
    if n <= 0 or len(vals) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(vals[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(vals)):
        prev = vals[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _ma(vals, n, mode):
    return ema(vals, n) if mode == "ema" else sma(vals, n)


def trend_series(bars, n, mode="sma"):
    """返回逐日均线序列（对收盘价）。"""
    return _ma(closes(bars), n, mode)


def trend_direction(prev_close, ma_value):
    """顺势方向：昨收 vs N 日均线。>0 多 / <0 空 / 0 无。"""
    if prev_close is None or ma_value is None:
        return 0
    if prev_close > ma_value:
        return 1
    if prev_close < ma_value:
        return -1
    return 0


def trend_confirm(bars, direction, periods=(5, 20, 40)):
    """趋势过滤（方案 A：救连亏）——各周期 SMA 必须与方向同向且依次排列。

    做多要求 SMA5 > SMA20 > SMA40；做空要求 SMA5 < SMA20 < SMA40。
    返回 False 表示趋势未成立（震荡/多空缠绕），应空仓。
    """
    if direction == 0:
        return False
    c = closes(bars)
    last = [sma(c, p)[-1] for p in periods]
    if any(v is None for v in last):
        return False
    for a, b in zip(last, last[1:]):
        if (a - b) * direction <= 0:
            return False
    return True


def vol_spike_filter(bars, mult=1.5, look=10):
    """波动率过滤器（方案 A2）：前一日振幅异常放大 → 今日空仓。

    前一日 (高−低) 振幅 > mult × 近 look 个交易日的平均振幅，视为冲顶/放量极端日，
    次日常现反转或剧烈震荡，跳过以规避不可测的方向跳空。bars 末尾即「昨日」。
    返回 True = 应空仓。
    """
    n = len(bars)
    if mult is None or mult <= 0 or n < look + 1:
        return False
    rng = [b[2] - b[3] for b in bars]
    avg = sum(rng[n - 1 - look:n - 1]) / look
    return rng[-1] > mult * avg


# --------------------------------------------------------------------------
# 展示
# --------------------------------------------------------------------------
def print_card(lad):
    """打印档位表（对齐官方格式）。"""
    d = lad["direction_cn"]
    print("=" * 60)
    print(f"黄金狩猎区 · 档位表  方向：{d} ｜ 开盘价(=100.0档) {lad['open_px']:.2f}")
    print("-" * 60)
    print(f"  跨度 S      : {lad['S']:.2f}   止损距离 R = 0.191·S = {lad['R']:.2f}")
    print(f"  腿端/中枢   : {lad['leg_start']:.2f}   (结构失效线)")
    print(f"  狩猎区      : {lad['zone_lo']:.2f} ~ {lad['zone_hi']:.2f}"
          f"  (宽 {lad['zone_width']:.2f})")
    print(f"  区中挂单    : {lad['zone_mid']:.2f}")
    print(f"  止损        : {lad['stop']:.2f}")
    if lad["t1"] is not None:
        print(f"  目标① 昨收  : {lad['t1']:.2f}")
    elif lad["special_gap"]:
        print(f"  [特殊跳空] 衰竭①与昨收错侧 → 直接走衰竭位")
    print(f"  衰竭①      : {lad['exh1']:.2f}")
    print(f"  衰竭②      : {lad['exh2']:.2f}")
    print("=" * 60)