# -*- coding: utf-8 -*-
"""乌圆狩猎区 · 档位引擎（网页版）

口径（已确证；证据链见 PRD 第 1 节）
------------------------------------
    0.0 → 19.1 → 38.2 → 50.0 → 61.8 → 80.9 → 100.0 → 161.8 → 261.8 → 423.6
    比例  0   0.191  0.382   0.5   0.618   0.809    1.0     1.618    2.618    4.236

- **100.0 档 = 当日开盘价**（9/9 样本命中，平均偏差 0.22 点）
- 狩猎区 = [0.382, 0.618]，宽 = 0.236 × S；**止损 = 0.191 档**
- 第一目标 = **前一交易日收盘价**（独立规则，不落在斐波档上）
- 衰竭目标 = 1.618 / 2.618 档
- 0.0 档 = 腿端 / 结构失效线

腿从哪来（★ 本版已完全自给）
------------------------------
**唯一入口 = `auto_leg()`**：系统自己取日线、自己算腿端、自己判方向。
他未公开的算法层不再需要，**人工粘贴四线 / 单档 / 反推 S 的路径已全部移除**。

⚠ 但自研腿**不是已验证策略**（六门槛 5 FAIL；样本外实证过拟合）。
   它输出的是**结构**，不是**信号**。返回体必带 verdict / tag / tradable，
   调用方必须原样展示，不得隐去。

因果纪律
--------
档位由「开盘价 + S + 方向」唯一确定，在布防那一刻锁定，盘中不重算。
取数失败时**明确报错，绝不猜一个 S 出来**。

依赖
----
纯计算：**无网络、无第三方库、无文件 IO**。可直接被 FastAPI 路由调用。
"""

ENGINE_VERSION = "wuyuan-web-20260923b"

# ------------------------------------------------------------------ 常量
# (比例, 标签) —— 0.0 与 1.0 是腿的两个端点，1.0 = 当日开盘价
LADDER = (
    (0.000, "0.0"),
    (0.191, "19.1"),
    (0.382, "38.2"),
    (0.500, "50.0"),
    (0.618, "61.8"),
    (0.809, "80.9"),
    (1.000, "100.0"),
    (1.618, "161.8"),
    (2.618, "261.8"),
    (4.236, "423.6"),
)

R_STOP = 0.191        # 止损档
R_ZONE_A = 0.382      # 狩猎区一沿
R_ZONE_B = 0.618      # 狩猎区另一沿
R_ZONE_MID = 0.500    # 狩猎区中值（第二档挂单）
R_EXH1 = 1.618        # 衰竭①
R_EXH2 = 2.618        # 衰竭②

# 档位角色文案（网页展示用；空串=该档不标角色）
ROLES = {
    0.000: "腿端 · 结构失效线",
    0.191: "★ 止损",
    0.382: "★ 狩猎区外沿 · 第1档挂单",
    0.500: "★ 区中 · 第2档挂单",
    0.618: "★ 狩猎区内沿 · 第3档挂单",
    0.809: "",
    1.000: "100.0 档 · 当日开盘价",
    1.618: "★ 衰竭① · 离场",
    2.618: "★ 衰竭② · 离场",
    4.236: "",
}

SHORT_ALIASES = ("short", "空", "做空", "s", "sell")
LONG_ALIASES = ("long", "多", "做多", "l", "buy")

# 合法比例集合（用于档位写法的规范化）
RATIOS = tuple(r for r, _ in LADDER)


def norm_ratio(x):
    """把档位写法统一成比例：'38.2' / '38.2%' / 0.382 都 → 0.382。

    为什么必须做这一步：档位标签是**百分数**（19.1 = 0.191），
    若直接把 '38.2' 当比例参与 `S = (X − 开盘价) / (1 − ratio)`，
    分母会变成 1−38.2 = −37.2，算出**方向相反、量级差 60 倍**的 S。
    """
    if isinstance(x, str):
        try:
            v = float(x.strip().rstrip("%"))
        except ValueError:
            raise ValueError("无法识别的档位写法: %r" % (x,))
    else:
        v = float(x)

    if v > 5.0:            # 明显是百分数标签（比例最大才 4.236，标签最小 19.1）
        v = v / 100.0

    best, bd = None, 1e9   # 就近匹配（容忍 1.62 → 1.618 这类两位小数写法）
    for r in RATIOS:
        d = abs(v - r)
        if d < bd:
            best, bd = r, d
    if best is not None and bd <= 0.005:
        return best
    raise ValueError("无法识别的档位: %r（合法：%s，或比例 %s）"
                     % (x, "/".join(n for _, n in LADDER),
                        "/".join("%.3f" % r for r in RATIOS)))

# 纪律文案（页面常驻提示，来源=讲解视频逐字稿）
DISCIPLINE = (
    "单日最多 2 笔；连续两次止损当日收手",
    "狩猎区内三档各挂 1/3 仓位",
    "到昨收减半仓，止损同步移至保本",
    "衰竭位须等小时级收线 + 缓冲再反手",
    "系统不自动下单，只做档位计算与纪律提醒",
)

# 自研腿专属警示（仅 auto 模式展示；实证结论，不得隐去）
AUTO_LEG_WARNINGS = (
    "自研腿 = 我们自己的结构生成器，**不是已验证策略**（六门槛 5 FAIL）。",
    "样本外实证：IS 最优规则 +70.4R(t=3.30) → 同规则 OOS −14.1R(t=−0.84)，"
    "10 个规则仅 1 个 OOS 为正 ⇒ 典型过拟合。",
    "实测成本地板 100bp；止损距离低于该值者无法覆盖 taker 往返 10bp，勿实盘。",
    "唯一未经检验就成立的部分是**几何**（档位比例、猎区、衰竭位），"
    "能信的只有几何，不是选腿规则。",
)


# ------------------------------------------------------------------ 基础
def norm_dir(direction):
    """规范方向写法 → 'short' / 'long'。"""
    s = str(direction).strip().lower()
    if s in SHORT_ALIASES:
        return "short"
    if s in LONG_ALIASES:
        return "long"
    raise ValueError("无法识别的方向: %r（应为 空/多 或 short/long）" % (direction,))


def role_of(ratio):
    """档位比例 → 角色文案。"""
    return ROLES.get(round(float(ratio), 3), "")


def price_at(ratio, open_px, S, direction):
    """第 ratio 档的价格（做空 0.0 在上；做多镜像）。"""
    if norm_dir(direction) == "short":
        return float(open_px) + (1.0 - float(ratio)) * float(S)
    return float(open_px) + (float(ratio) - 1.0) * float(S)


# ------------------------------------------------------------------ 正解
def build(open_px, S, direction, prev_close=None, source="", note=""):
    """正解：生成当天完整档位表（dict，可直接 JSON 序列化）。

    open_px    : 当日开盘价（= 100.0 档，官方口径）
    S          : 跨度（腿长）
    direction  : 'short'/'long' 或 空/多
    prev_close : 前一交易日收盘价（目标①，可空）
    """
    if S is None or float(S) <= 0:
        raise ValueError("跨度 S 必须为正数，收到 %r" % (S,))
    open_px = float(open_px)
    S = float(S)
    d = norm_dir(direction)
    sh = (d == "short")

    def f(r):
        return price_at(r, open_px, S, d)

    zone_a, zone_b = f(R_ZONE_A), f(R_ZONE_B)
    exh1, exh2 = f(R_EXH1), f(R_EXH2)
    # 0.0 档 = 腿端（做空在开盘价上方 / 做多在下方）；1.0 档 = 100.0 档 = 当日开盘价。
    # 注意：**不能**按"数值上/下"取名来接 0.0 档 —— 做多时 0.0 档在下方，
    # 曾经的 `leg_top if short else leg_bottom` 写法会让做多的腿失效线错成开盘价（已修）。
    p_ratio0 = f(0.0)
    p_ratio1 = f(1.0)

    # 跳空特殊日（逐字稿原话）：做空时衰竭①高于昨收 ⇒ 不减仓博弈，直接到衰竭位
    special = None
    if prev_close is not None:
        prev_close = float(prev_close)
        special = (exh1 > prev_close) if sh else (exh1 < prev_close)

    targets = []
    if prev_close is not None and not special:
        targets.append({"id": "T1", "name": "第一目标位 = 昨收", "price": prev_close})
    targets.append({"id": "EXH1", "name": "衰竭① (1.618)", "price": exh1})
    targets.append({"id": "EXH2", "name": "衰竭② (2.618)", "price": exh2})

    return {
        "schema": 1,
        "engine": ENGINE_VERSION,
        "direction": d,
        "direction_cn": "做空" if sh else "做多",
        "open_px": open_px,
        "S": S,
        "R": R_STOP * S,                      # 止损距离 = 0.191 × S
        "leg_top": max(p_ratio0, p_ratio1),      # 数值较大的一端
        "leg_bottom": min(p_ratio0, p_ratio1),   # 数值较小的一端
        "leg_start": p_ratio0,                   # 0.0 档（腿端）
        "open_end": p_ratio1,                    # 1.0 档 = 当日开盘价
        "stop": f(R_STOP),
        "zone_hi": max(zone_a, zone_b),
        "zone_lo": min(zone_a, zone_b),
        "zone_mid": f(R_ZONE_MID),
        "exh1": exh1,
        "exh2": exh2,
        "invalid_line": p_ratio0,                # 腿失效线 = 0.0 档
        "prev_close": prev_close,
        "t1": (prev_close if (prev_close is not None and not special) else None),
        "special_gap": special,
        "targets": targets,
        "zone_width": abs(zone_a - zone_b),
        "entry_levels": sorted([zone_a, zone_b, f(R_ZONE_MID)]),
        "levels": [{"ratio": r, "name": n, "price": f(r), "role": role_of(r)}
                   for r, n in LADDER],
        "source": source,
        "note": note,
    }



# ------------------------------------------------------------------ 自研腿（AUTO-LEG）
# ⚠ 定位说明：他的 S 出自未公开算法层、不可预测（约 150 种定义 × 2 源全部排除）。
#   这一段是**我们自己的**可算规则，用来让页面「零输入也能出图」。
#   但它在 142 天 × 15m  上未通过显著性检验（t=0.8~1.5 / bootstrap 下界为负 /
#   前后半样本分裂 / 去最好 3 笔归零 / 日界换 1 小时由 +88.8R 变 +3.7R）
#   ⇒ 只当"结构生成器 + 信号记录"，**不得当作已验证策略**。任何输出必须带上 verdict。
AUTO_LEG_LOOKBACK = 5          # 腿端 = 近 N 个已收盘日的方向性极值
AUTO_LEG_MIN_R_BP = 15.0       # 「结构宽度」闸门：0.191·S 低于该 bp 数 ⇒ 当日无结构
# ⚠ 两个 bp 数不是一回事，别混：
#   MIN_R_BP = 15.0  → 结构可用性下限（腿太窄则档位挤成一团、无参考价值）
#   COST_FLOOR_BP    → 可交易性下限（实测 taker 往返 10.0bp；此处留 10× 安全垫取 100）
#   2R 结构 ⇒ 需 R ≥ 成本 × 安全倍数。实测：taker 往返 10.00bp、ATR(14)4h=95.0bp
#   ⇒ **taker 口径下仅 4H 及以上周期可行**。15m/1h 结构在成本面前必亏，与规则好坏无关。
COST_FLOOR_BP = 100.0          # 实测成本地板（taker 往返 10bp × 10 倍安全垫）
AUTO_LEG_TAG = "自研腿·未验证"
AUTO_LEG_VERDICT = ("未通过显著性检验：六门槛 5 FAIL / 1 PASS（t<2.0、bootstrap90 下界为负、"
                    "前后半分裂、日界不同号、去最好 3 笔转负）；"
                    "★ 样本外实证过拟合——IS 最优 ext5/trend 达 +70.4R(t=3.30)，"
                    "同规则 OOS 变 −14.1R(t=-0.84)；10 个规则仅 1 个 OOS 为正")


def auto_leg(open_px, daily_bars, lookback=None, min_r_bp=None, offset=0.0,
             prev_close=None, source=""):
    """自研选腿：不用他公布的任何数值。

    open_px     : 当日开盘价（官方口径 = 100.0 档）
    daily_bars  : 已收盘日线，升序，每项含 high/low/close（**监控源原始价**）
    offset      : 官方口径 = 原始价 + offset（把日线极值换算到官方口径）
    prev_close  : 前一交易日收盘（**官方口径**）；缺省用最后一根日线 close + offset

    规则（预注册）：方向 = 跳空方向（今开 ≤ 昨收 ⇒ 空）；腿端 = 近 N 日方向性极值；
                    S = |腿端 − 今开|；成本闸门 0.191·S ≥ min_r_bp。
    返回 dict，含 ok / direction / S / P0 / ladder / verdict / tag。
    """
    lookback = lookback or AUTO_LEG_LOOKBACK
    min_r_bp = AUTO_LEG_MIN_R_BP if min_r_bp is None else min_r_bp
    open_px = float(open_px)
    off = float(offset or 0.0)
    bars = [b for b in (daily_bars or []) if b.get("high") is not None and b.get("low") is not None]
    if len(bars) < lookback:
        raise ValueError("已收盘日线不足：需要 %d 根，只拿到 %d 根" % (lookback, len(bars)))
    win = bars[-lookback:]
    prev_close_official = (float(prev_close) if prev_close is not None
                           else float(bars[-1]["close"]) + off)

    d = "short" if open_px <= prev_close_official else "long"
    if d == "short":
        P0 = max(float(b["high"]) for b in win) + off
        S = P0 - open_px
    else:
        P0 = min(float(b["low"]) for b in win) + off
        S = open_px - P0

    base = {"rule": "autoleg-v1-20260923", "lookback": lookback,
            "direction": d, "direction_cn": "做空" if d == "short" else "做多",
            "open_px": open_px, "P0": P0, "S": S, "offset": off,
            "prev_close": prev_close_official, "min_r_bp": min_r_bp,
            "tag": AUTO_LEG_TAG, "verdict": AUTO_LEG_VERDICT}
    if S <= 0:
        base.update({"ok": False, "reason": "跳空越过了近 %d 日的%s ⇒ 该方向没有腿"
                     % (lookback, "最高点" if d == "short" else "最低点")})
        return base
    R = R_STOP * S
    r_bp = R / open_px * 10000.0
    base.update({"R": R, "r_bp": r_bp, "cost_floor_bp": COST_FLOOR_BP})
    # 闸门比较用相对容差：r_bp 由浮点除法得出，恰好等于闸门时可能落在 14.9999999
    # ⇒ 裸 `<` 会把"正好达标"误判为不达标（边界抖动）。容差 1e-9 相对值足够。
    _tol = 1e-9
    if r_bp < min_r_bp * (1.0 - _tol):
        base.update({"ok": False, "reason": "止损距离 %.2f 点 = %.1fbp < 结构宽度闸门 %.0fbp "
                                            "⇒ 当日结构太窄，不值得做" % (R, r_bp, min_r_bp)})
        return base
    # 第二道闸门：可交易性。结构宽度够了 ≠ 能覆盖成本。
    # 不过这道闸门不拒绝出图（有结构就是有结构），只降级为「仅结构参考」并告警。
    tradable = r_bp >= COST_FLOOR_BP * (1.0 - _tol)
    base.update({
        "ok": True, "reason": "",
        "tradable": tradable,
        "trade_note": "" if tradable else
        ("止损 %.1fbp < 成本地板 %.0fbp（taker 往返 10bp × 10 倍安全垫）"
         "⇒ 该结构**不足以覆盖交易成本**，仅作结构参考，勿实盘。" % (r_bp, COST_FLOOR_BP)),
        "ladder": build(open_px, S, d, prev_close=prev_close_official,
                        source=source or ("autoleg/lookback=%d" % lookback),
                        note=AUTO_LEG_TAG)})
    return base


# ------------------------------------------------------------------ 标注
def annotate(lad, live_px=None):
    """给档位表补"距基准多少点 / 多少 bp"，并给出当前位置判定。

    基准 = 现价（有则用）否则狩猎区中值。距离带符号：正数在基准上方。
    """
    base = float(live_px) if live_px is not None else float(lad["zone_mid"])
    levels = []
    for lv in lad["levels"]:
        d = float(lv["price"]) - base
        levels.append({
            "ratio": lv["ratio"], "name": lv["name"], "price": lv["price"],
            "role": lv["role"],
            "dist_pt": d,
            "dist_bp": (d / base * 10000.0) if base else None,
        })

    out = dict(lad)
    out["levels"] = levels
    out["base"] = base
    out["base_kind"] = "live" if live_px is not None else "zone_mid"
    out["position"] = position_of(lad, live_px)
    return out


def position_of(lad, px):
    """现价相对结构的位置判定（纯描述，不构成交易建议）。

    分段（做空，px 自下而上）：
        衰竭② < 衰竭① < 100.0档 < 区下沿 < 区上沿 < 止损 < 腿失效线
    """
    if px is None:
        return {"ok": False, "text": "无现价（未取到行情），距离列以狩猎区中值为基准"}
    px = float(px)
    inv = lad["invalid_line"]
    st = lad["stop"]
    zhi, zlo = lad["zone_hi"], lad["zone_lo"]
    e1, e2 = lad["exh1"], lad["exh2"]

    if lad["direction"] == "short":
        if px > inv:
            return {"ok": True, "state": "void",
                    "text": "已越过腿失效线 %.2f ⇒ 本腿作废" % inv}
        if px > st:
            return {"ok": True, "state": "above_stop",
                    "text": "在止损 %.2f 上方、未越过失效线 %.2f（腿仍有效）" % (st, inv)}
        if px > zhi:
            return {"ok": True, "state": "above_zone",
                    "text": "已进猎区之上（%.2f 之上），未到止损 %.2f" % (zhi, st)}
        if px >= zlo:
            return {"ok": True, "state": "in_zone",
                    "text": "在狩猎区 %.2f ~ %.2f 内" % (zlo, zhi)}
        if px >= e1:
            return {"ok": True, "state": "below_zone",
                    "text": "已进猎区之下（%.2f 之下），未到衰竭① %.2f" % (zlo, e1)}
        if px >= e2:
            return {"ok": True, "state": "past_exh1",
                    "text": "已过衰竭① %.2f，下一档衰竭② %.2f" % (e1, e2)}
        return {"ok": True, "state": "past_exh2",
                "text": "已过衰竭② %.2f（目标全达）" % e2}

    # 做多镜像（px 自下而上：腿失效线 < 止损 < 区下沿 < 区上沿 < 100.0档 < 衰竭① < 衰竭②）
    if px < inv:
        return {"ok": True, "state": "void",
                "text": "已跌破腿失效线 %.2f ⇒ 本腿作废" % inv}
    if px < st:
        return {"ok": True, "state": "below_stop",
                "text": "在止损 %.2f 下方、未跌破失效线 %.2f（腿仍有效）" % (st, inv)}
    if px < zlo:
        return {"ok": True, "state": "below_zone",
                "text": "已进猎区之下（%.2f 之下），未到止损 %.2f" % (zlo, st)}
    if px <= zhi:
        return {"ok": True, "state": "in_zone",
                "text": "在狩猎区 %.2f ~ %.2f 内" % (zlo, zhi)}
    if px <= e1:
        return {"ok": True, "state": "above_zone",
                "text": "已进猎区之上（%.2f 之上），未到衰竭① %.2f" % (zhi, e1)}
    if px <= e2:
        return {"ok": True, "state": "past_exh1",
                "text": "已过衰竭① %.2f，下一档衰竭② %.2f" % (e1, e2)}
    return {"ok": True, "state": "past_exh2",
            "text": "已过衰竭② %.2f（目标全达）" % e2}


# ------------------------------------------------------------------ 文本
def fmt_table(lad):
    """档位表纯文本（控制台 / 排查用）。"""
    L = ["方向 %s ｜ 开盘价(=100.0档) %.2f ｜ 跨度 S %.2f ｜ R(止损距离) %.2f"
         % (lad["direction_cn"], lad["open_px"], lad["S"], lad["R"]),
         "  档位       价格        角色"]
    for lv in lad["levels"]:
        L.append("  %-8s %10.2f    %s" % (lv["name"], lv["price"], lv["role"]))
    L.append("  狩猎区 %.2f ~ %.2f（宽 %.2f）"
             % (lad["zone_lo"], lad["zone_hi"], lad["zone_width"]))
    L.append("  止损 %.2f（距区外沿 %.2f）" % (lad["stop"], lad["R"]))
    if lad["t1"] is not None:
        L.append("  第一目标位 = 昨收 %.2f" % lad["t1"])
    elif lad["special_gap"]:
        L.append("  [特殊] 衰竭① %.2f 与昨收 %.2f 错侧 ⇒ 直接到衰竭位"
                 % (lad["exh1"], lad["prev_close"]))
    L.append("  衰竭① %.2f ｜ 衰竭② %.2f" % (lad["exh1"], lad["exh2"]))
    L.append("  腿失效线 %.2f（越过即当日作废）" % lad["invalid_line"])
    return "\n".join(L)
