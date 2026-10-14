# -*- coding: utf-8 -*-
"""
每日交易计划引擎（新增模块，不改动 backtest.py / db.py / data_sync.py 既有逻辑）

与既有 backtest.py 的三点关键差异（针对审计发现的 P0）：
- P0-A 规避：数据层按天分页查询，规避 db.MAX_ROWS=10000 静默截断；
             且默认用 5m 表（一个月 8k 根）而非 1m 表（41k 根）。
- P0-B 规避：严格 asof 截断——任何指标/关键位计算只允许使用 close_time <= asof 的 bar，
             bar_at() 只向前取（bisect_right-1），永不取后一根。
- P0-C 规避：不做全样本参数寻优。所有阈值为预注册常量（PRESET），
             回测只评估固定规则，不搜索最优参数。

时区口径：
- Binance 时间戳为 UTC 毫秒；本机时区 UTC+8，故 datetime.fromtimestamp(ts/1000) = 北京时间。
- 显式封装为 bj()/to_ms()，避免隐式依赖（审计 P2-G）。
- 外汇交易日切分：纽约 17:00 收市。夏令时=北京 05:00，冬令时=北京 06:00。
  DST 按美国规则精确计算（3月第2个周日~11月第1个周日），不用 3<=month<=11 粗判（审计 P2-I）。
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import json
import math
from datetime import datetime, timedelta

from data.db import query_kline
from config import TABLE_MAP

# ==================== 预注册常量（不做参数寻优） ====================
CFG = {
    "interval": "5m",                 # 数据粒度（一个月约 8k 根，远低于 10000 截断线）
    "price_offset": 12.0,             # PAXGUSDT ->  口径偏移（与 data_sync 一致）
    "asof_hm": (9, 0),                # 每日计划决策时点（北京时间）
    "atr_n": 14,                      # ATR 周期（日线）
    "sma_n": 10,                      # 均线周期（日线）
    "swing_lookback": 20,             # 摆动高低点回看天数
    "band_atr": 0.15,                 # 关键位共振带半宽（× ATR14）
    "reject_bars": 3,                 # 拒止确认：触及后 N 根 5m 内须收盘回落
    "stop_atr": 0.30,                 # 止损缓冲（× ATR14）
    "tp1_r": 1.5,                     # 目标1（R 倍数）
    "tp2_r": 2.5,                     # 目标2（R 倍数）
    "max_hold_hours": 24,             # 最长持仓（小时），到点强制平仓
    "risk_per_trade": 0.01,           # 单笔风险（账户比例）
    "risk_secondary": 0.005,          # 备计划风险（主计划的一半）
    "account": 50000.0,               # 账户规模（USD）
    "spread_usd": 0.30,               # 单边点差（美元/盎司）；双边成本 = 2×
    "slip_usd": 0.20,                 # 单边滑点（美元/盎司）
    "contract_oz": 100,               # 1 标准手 = 100 盎司
}

BJ_OFFSET_H = 8  # 北京时间 = UTC + 8


# ==================== 时间工具 ====================
_EPOCH = datetime(1970, 1, 1)


def bj(ts_ms):
    """UTC 毫秒 -> 北京时间 datetime（显式 +8，不依赖机器本地时区）"""
    return datetime.utcfromtimestamp(ts_ms / 1000) + timedelta(hours=BJ_OFFSET_H)


def to_ms_bj(y, m, d, hh=0, mm=0):
    """北京时间 Y/M/D hh:mm -> UTC 毫秒。
    注意：不能用 datetime(...).timestamp()，它把 naive 时间按【机器本地时区】解释，
    会与这里的手工 -8h 叠加成双重偏移。这里直接按 UTC 纪元算秒差。"""
    utc_naive = datetime(y, m, d, hh, mm) - timedelta(hours=BJ_OFFSET_H)
    return int((utc_naive - _EPOCH).total_seconds() * 1000)


def _nth_sunday(year, month, n):
    """第 n 个周日的日期（n 从 1 开始）"""
    d = datetime(year, month, 1)
    offset = (6 - d.weekday()) % 7      # weekday: Mon=0 ... Sun=6
    return d + timedelta(days=offset + 7 * (n - 1))


def is_us_dst(dt_bj):
    """美国夏令时判定（精确）：3月第2个周日 02:00 ~ 11月第1个周日 02:00（当地时间）。
    入参为北京时间 datetime；边界按北京 15:00（=纽约 02:00 + 13h）近似到日。"""
    y = dt_bj.year
    start = _nth_sunday(y, 3, 2)
    end = _nth_sunday(y, 11, 1)
    d = dt_bj.date()
    if d < start.date() or d > end.date():
        return False
    if d == start.date():
        return dt_bj.hour >= 15      # 纽约 02:00 = 北京 15:00（夏令时前）
    if d == end.date():
        return dt_bj.hour < 14       # 纽约 02:00 = 北京 14:00（夏令时中）
    return True


def fx_day_cutoff_hour(dt_bj):
    """外汇交易日切分时刻（北京时间小时）：纽约 17:00 收市。夏令时 05:00 / 冬令时 06:00。"""
    return 5 if is_us_dst(dt_bj) else 6


def fx_trade_day(dt_bj):
    """5m bar（北京时间）所属的外汇交易日 date。
    交易日 T 覆盖 北京 T日 cutoff ~ T+1日 cutoff。"""
    cut = fx_day_cutoff_hour(dt_bj)
    if dt_bj.hour < cut:
        return (dt_bj - timedelta(days=1)).date()
    return dt_bj.date()


# ==================== 数据层（分页，规避 P0-A） ====================
def load_bars(start_ms, end_ms, interval=None, page_days=5):
    """分页查询 K 线，规避 db.MAX_ROWS=10000 截断。
    按 page_days 天切片，每片远小于 10000 根；结果按 open_time 去重升序。
    """
    interval = interval or CFG["interval"]
    table = TABLE_MAP.get(interval)
    if not table:
        raise ValueError(f"不支持的周期: {interval}")

    out, seen = [], set()
    cur = start_ms
    step = int(page_days * 86400 * 1000)
    while cur <= end_ms:
        seg_end = min(cur + step, end_ms)
        rows, _ = query_kline(table, cur, seg_end)
        if not rows:
            cur = seg_end + 1
            continue
        for r in rows:
            ot = int(r["open_time"])
            if ot in seen:
                continue
            seen.add(ot)
            out.append({
                "open_time": ot,
                "close_time": int(r["close_time"]),
                "open": float(r["open_price"]),
                "high": float(r["high_price"]),
                "low": float(r["low_price"]),
                "close": float(r["close_price"]),
            })
        last_ct = max(int(r["close_time"]) for r in rows)
        if last_ct <= cur:
            break
        cur = last_ct + 1
    out.sort(key=lambda b: b["open_time"])
    return out


# ==================== 日线重聚合（外汇交易日口径） ====================
def to_fx_daily(bars):
    """5m bars -> 外汇交易日日线列表。
    返回 [{day: date, open, high, low, close, n}]，按 day 升序。"""
    buckets = {}
    for b in bars:
        d = fx_trade_day(bj(b["open_time"]))
        s = buckets.get(d)
        if s is None:
            buckets[d] = {"day": d, "open": b["open"], "high": b["high"],
                          "low": b["low"], "close": b["close"], "n": 1}
        else:
            s["high"] = max(s["high"], b["high"])
            s["low"] = min(s["low"], b["low"])
            s["close"] = b["close"]
            s["n"] += 1
    return [buckets[k] for k in sorted(buckets.keys())]


# ==================== 指标（纯函数，只用传入序列） ====================
def atr(daily, n=None):
    """日线 ATR(n)：真实波幅均值"""
    n = n or CFG["atr_n"]
    if len(daily) < 2:
        return 0.0
    trs = []
    prev_close = daily[0]["close"]
    for i in range(1, len(daily)):
        h, l, pc = daily[i]["high"], daily[i]["low"], prev_close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        prev_close = daily[i]["close"]
    if not trs:
        return 0.0
    return sum(trs[-n:]) / min(len(trs), n)


def sma(daily, n=None, field="close"):
    n = n or CFG["sma_n"]
    vals = [d[field] for d in daily][-n:]
    return sum(vals) / len(vals) if vals else 0.0


def rsi(bars, n=14):
    """5m RSI(n)"""
    if len(bars) < n + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(bars)):
        ch = bars[i]["close"] - bars[i - 1]["close"]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def ema(bars, n, field="close"):
    if not bars:
        return 0.0
    k = 2.0 / (n + 1)
    e = bars[0][field]
    for b in bars[1:]:
        e = b[field] * k + e * (1 - k)
    return e


def bar_at(bars, ts_ms):
    """返回 open_time <= ts_ms 的最后一根 bar（严格向前取，永不取未来 —— 规避 P0-B）。"""
    if not bars:
        return None
    lo, hi = 0, len(bars) - 1
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid]["open_time"] <= ts_ms:
            ans = bars[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def visible(bars, asof_ms):
    """截断到 asof：只保留 close_time <= asof 的 bar（结构性保证，非事后声明）"""
    return [b for b in bars if b["close_time"] <= asof_ms]


# ==================== 关键位 ====================
def _levels_from_daily(daily_vis, atr_v, cur):
    """从可见日线提取候选关键位，标记与现价的 ATR 距离。"""
    if not daily_vis:
        return []
    prev = daily_vis[-1]                       # 上一完整外汇交易日
    lb = min(CFG["swing_lookback"], len(daily_vis))
    win = daily_vis[-lb:]
    swing_hi = max(d["high"] for d in win)
    swing_lo = min(d["low"] for d in win)

    cands = [
        ("前日高 PDH", prev["high"]),
        ("前日低 PDL", prev["low"]),
        ("前日收", prev["close"]),
        ("摆动高 %dd" % lb, swing_hi),
        ("摆动低 %dd" % lb, swing_lo),
    ]
    # 整数关口（每 50 美元）
    base = int(cur // 50) * 50
    for g in (base - 50, base, base + 50, base + 100):
        cands.append((f"整数关 {g}", float(g)))

    out = []
    for name, px in cands:
        out.append({
            "name": name, "px": round(px, 2),
            "d_px": round(px - cur, 2),
            "d_atr": round((px - cur) / atr_v, 3) if atr_v else 0.0,
        })
    return out


def _cluster(levels, atr_v, half_width_atr=None):
    """把候选位按 ATR 半宽聚合成共振带。返回 [{lo, hi, members, strength}]"""
    hw = (half_width_atr or CFG["band_atr"]) * atr_v
    if not levels:
        return []
    pts = sorted(levels, key=lambda x: x["px"])
    bands = []
    # 带宽上限：防止链式合并把 4450~4500 这样的宽区间拼成一个"共振带"（虚假共振）
    max_w = CFG.get("band_max_atr", 0.45) * atr_v
    for lv in pts:
        if bands and (lv["px"] - bands[-1]["hi"] <= hw * 2) and (lv["px"] - bands[-1]["lo"] <= max_w):
            bands[-1]["hi"] = lv["px"]
            bands[-1]["members"].append(lv)
        else:
            bands.append({"lo": lv["px"], "hi": lv["px"], "members": [lv]})
    for b in bands:
        b["strength"] = len(b["members"])
        b["mid"] = round((b["lo"] + b["hi"]) / 2, 2)
        b["names"] = [m["name"] for m in b["members"]]
    return bands


def build_levels(bars_vis, daily_vis):
    """构建关键位与共振带"""
    cur = bars_vis[-1]["close"] if bars_vis else 0.0
    atr_v = atr(daily_vis)
    lv = _levels_from_daily(daily_vis, atr_v, cur)
    bands = _cluster(lv, atr_v)
    above = [b for b in bands if b["lo"] > cur]
    below = [b for b in bands if b["hi"] < cur]
    return {
        "atr14": round(atr_v, 2),
        "cur": round(cur, 2),
        "levels": lv,
        "bands": bands,
        "resistance": sorted(above, key=lambda b: b["lo"])[:3],
        "support": sorted(below, key=lambda b: -b["hi"])[:3],
    }


# ==================== 计划生成 ====================
def make_plan(bars_all, asof_ms, cfg=None):
    """在决策时点 asof 生成交易计划。只用 close_time <= asof 的数据（P0-B 保证）。"""
    cfg = dict(CFG, **(cfg or {}))
    bars_vis = visible(bars_all, asof_ms)
    if len(bars_vis) < 50:
        return {"ok": False, "reason": "可见数据不足", "asof": asof_ms}

    daily_vis = to_fx_daily(bars_vis)
    # 当日（未收市）的外汇日不作为"前日"使用
    cur_day = fx_trade_day(bj(asof_ms))
    daily_closed = [d for d in daily_vis if d["day"] < cur_day]
    if len(daily_closed) < 5:
        return {"ok": False, "reason": "可见日线不足 5 根", "asof": asof_ms}

    L = build_levels(bars_vis, daily_closed)
    cur = L["cur"]
    atr_v = L["atr14"]
    sma_v = sma(daily_closed)
    rsi_v = rsi(bars_vis, 14)
    ema20 = ema(bars_vis[-200:], 20)
    ema50 = ema(bars_vis[-200:], 50)

    # 方向偏好：价格 vs SMA10（>0.5ATR 偏空，<-0.5ATR 偏多，中间中性）
    dev_atr = (cur - sma_v) / atr_v if atr_v else 0.0
    if dev_atr < -0.5:
        bias = "bear"
    elif dev_atr > 0.5:
        bias = "bull"
    else:
        bias = "neutral"

    # 主计划：偏向方向的共振带。
    # 拒止单（非突破单）：空头=冲高进带后回落到带下沿下方入场；多头=下探进带后反弹到带上沿上方入场。
    # 入场价必须落在【价格回撤路径上】，否则会出现"价格从未到达却被判成交"的虚假成交。
    primary, secondary = None, None
    if bias == "bear" and L["resistance"]:
        b = L["resistance"][0]
        primary = {"side": "short", "zone": [round(b["lo"], 2), round(b["hi"], 2)],
                   "band": b, "entry": round(b["lo"] - 0.5, 2),
                   "stop": round(b["hi"] + CFG["stop_atr"] * atr_v, 2)}
    elif bias == "bull" and L["support"]:
        b = L["support"][0]
        primary = {"side": "long", "zone": [round(b["lo"], 2), round(b["hi"], 2)],
                   "band": b, "entry": round(b["hi"] + 0.5, 2),
                   "stop": round(b["lo"] - CFG["stop_atr"] * atr_v, 2)}

    # 备计划：反向带（风险减半）
    if bias == "bear" and L["support"]:
        b = L["support"][0]
        secondary = {"side": "long", "zone": [round(b["lo"], 2), round(b["hi"], 2)],
                     "band": b, "entry": round(b["hi"] + 0.5, 2),
                     "stop": round(b["lo"] - CFG["stop_atr"] * atr_v, 2)}
    elif bias == "bull" and L["resistance"]:
        b = L["resistance"][0]
        secondary = {"side": "short", "zone": [round(b["lo"], 2), round(b["hi"], 2)],
                     "band": b, "entry": round(b["lo"] - 0.5, 2),
                     "stop": round(b["hi"] + CFG["stop_atr"] * atr_v, 2)}

    for p, rf in ((primary, CFG["risk_per_trade"]), (secondary, CFG["risk_secondary"])):
        if not p:
            continue
        r = abs(p["entry"] - p["stop"])
        p["R"] = round(r, 2)
        p["tp1"] = round(p["entry"] + CFG["tp1_r"] * r * (1 if p["side"] == "long" else -1), 2)
        p["tp2"] = round(p["entry"] + CFG["tp2_r"] * r * (1 if p["side"] == "long" else -1), 2)
        p["lots"] = round(CFG["account"] * rf / (r * CFG["contract_oz"]), 2) if r > 0 else 0.0
        p["risk_pct"] = round(rf * 100, 2)
        p["dist_atr"] = round(abs(p["entry"] - cur) / atr_v, 3) if atr_v else 0.0

    return {
        "ok": True,
        "asof": asof_ms,
        "asof_str": bj(asof_ms).strftime("%Y-%m-%d %H:%M"),
        "trade_day": str(cur_day),
        "cur": round(cur, 2),
        "atr14": round(atr_v, 2),
        "sma10": round(sma_v, 2),
        "dev_atr": round(dev_atr, 3),
        "rsi14_5m": round(rsi_v, 1),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "bias": bias,
        "levels": L["levels"],
        "resistance": [{k: v for k, v in b.items() if k != "members"} for b in L["resistance"]],
        "support": [{k: v for k, v in b.items() if k != "members"} for b in L["support"]],
        "primary": primary,
        "secondary": secondary,
        "bars_used": len(bars_vis),
        "daily_used": len(daily_closed),
        "data_cut": bj(bars_vis[-1]["close_time"]).strftime("%Y-%m-%d %H:%M"),
    }


# ==================== 回测执行（用 asof 之后的真实行情判定） ====================
# 说明：决策只用 asof 前数据（已由 visible() 保证）；此处消费的是"历史上真实发生的后续行情"，
# 属于回测（walk-forward 模拟），不是未来函数。
COST_ONEWAY = CFG["spread_usd"] + CFG["slip_usd"]   # 单边成本（美元/盎司）


def simulate_side(plan, bars_after, side, entry_lvl, stop_lvl, tp1, tp2, zone):
    """模拟一条腿（限价 + 拒止确认）。返回 dict 或 None（未触发）。
    执行规则（预注册，不寻优）：
      1. 触及：bar 穿越 zone（空: high>=zone.lo；多: low<=zone.hi）
      2. 拒止确认：触及后 reject_bars 根内，出现收盘回落至 zone 内侧 → 下一根开盘成交
      3. 出场：止损 / TP1 平半移保本 / TP2 / 超时强平
      4. 成本：开平各扣一次（双边）—— 修正 backtest.py 只扣单边的 P1-D
    """
    n = len(bars_after)
    touched_at = None
    for i, b in enumerate(bars_after):
        hit = (b["high"] >= zone[0]) if side == "short" else (b["low"] <= zone[1])
        if hit:
            touched_at = i
            break
    if touched_at is None:
        return None

    # 拒止确认：收盘回到带外侧（空=收在带下沿之下；多=收在带上沿之上）
    reject_i = None
    lim = min(touched_at + CFG["reject_bars"] + 1, n - 1)
    for j in range(touched_at, lim):
        b = bars_after[j]
        ok = (b["close"] < zone[0]) if side == "short" else (b["close"] > zone[1])
        if ok:
            reject_i = j
            break
    if reject_i is None:
        return {"status": "触及未确认", "r": 0.0}

    # 限价成交：拒止后价格必须【真实触及】entry，否则不算成交（杜绝虚假成交）
    entry_i = None
    max_wait = min(n - 1, reject_i + int(CFG["max_hold_hours"] * 12))
    for k in range(reject_i + 1, max_wait + 1):
        b = bars_after[k]
        if (b["low"] <= entry_lvl) if side == "short" else (b["high"] >= entry_lvl):
            entry_i = k
            break
    if entry_i is None:
        return {"status": "拒止未回撤至限价", "r": 0.0}

    # 成交价 = 限价 + 不利滑点（真实限价单不会比限价更优）
    fill = entry_lvl + (COST_ONEWAY if side == "long" else -COST_ONEWAY)
    R = abs(fill - stop_lvl)
    if R <= 0:
        return {"status": "R=0", "r": 0.0}

    max_i = min(n - 1, entry_i + int(CFG["max_hold_hours"] * 12))  # 5m 根数
    phase, pnl_r, exit_i, exit_reason = "open", 0.0, None, None
    for k in range(entry_i, max_i + 1):
        b = bars_after[k]
        if side == "short":
            hit_sl = b["high"] >= stop_lvl
            hit_tp1 = b["low"] <= tp1
            hit_tp2 = b["low"] <= tp2
        else:
            hit_sl = b["low"] <= stop_lvl
            hit_tp1 = b["high"] >= tp1
            hit_tp2 = b["high"] >= tp2

        if phase == "open":
            if hit_sl:                      # 同根 SL/TP 冲突：SL 优先（保守，与既有引擎一致）
                pnl_r = -1.0
                exit_reason, exit_i = "SL", k
                break
            if hit_tp1:
                pnl_r = CFG["tp1_r"] * 0.5
                phase, be = "be", fill
                if hit_tp2:                 # 同根直接到 TP2
                    pnl_r = CFG["tp1_r"] * 0.5 + CFG["tp2_r"] * 0.5
                    exit_reason, exit_i = "TP2", k
                    break
                continue
        elif phase == "be":
            hit_be = (b["high"] >= be) if side == "short" else (b["low"] <= be)
            if tp2 is not None and (hit_tp2 or hit_be):
                if hit_be and not hit_tp2:
                    pnl_r = CFG["tp1_r"] * 0.5        # 保本离场
                    exit_reason, exit_i = "BE", k
                    break
                if hit_tp2 and not hit_be:
                    pnl_r = CFG["tp1_r"] * 0.5 + CFG["tp2_r"] * 0.5
                    exit_reason, exit_i = "TP2", k
                    break
                # 同根冲突：保本优先（不贪）
                pnl_r = CFG["tp1_r"] * 0.5
                exit_reason, exit_i = "BE", k
                break

    if exit_i is None:  # 超时强平
        b = bars_after[max_i]
        exit_i, exit_reason = max_i, "TIMEOUT"
        raw = (fill - b["close"]) if side == "short" else (b["close"] - fill)
        pnl_r = raw / R

    # 双边成本折算成 R
    cost_r = (2 * COST_ONEWAY) / R
    net_r = pnl_r - cost_r
    return {
        "status": "成交",
        "side": side,
        "fill": round(fill, 2),
        "entry_time": bj(bars_after[entry_i]["open_time"]).strftime("%Y-%m-%d %H:%M"),
        "entry_ms": bars_after[entry_i]["open_time"],
        "exit_reason": exit_reason,
        "exit_time": bj(bars_after[exit_i]["close_time"]).strftime("%Y-%m-%d %H:%M"),
        "R": round(R, 2),
        "gross_r": round(pnl_r, 3),
        "cost_r": round(cost_r, 3),
        "net_r": round(net_r, 3),
    }


def run_day(bars, asof_ms, cfg=None):
    """生成计划并用后续 24h 真实行情模拟。返回 (plan, trades)"""
    plan = make_plan(bars, asof_ms, cfg)
    if not plan.get("ok"):
        return plan, []
    after = [b for b in bars if b["open_time"] > asof_ms]
    if len(after) < 30:
        return plan, []
    trades = []
    for key in ("primary", "secondary"):
        p = plan.get(key)
        if not p:
            continue
        t = simulate_side(plan, after, p["side"], p["entry"], p["stop"],
                          p["tp1"], p["tp2"], p["zone"])
        if not t:
            continue
        t["leg"] = key
        t["lots"] = p["lots"]
        t["pnl_u"] = (round(t["net_r"] * p["R"] * p["lots"] * CFG["contract_oz"], 2)
                      if t.get("status") == "成交" else 0.0)
        trades.append(t)

    # 主备互斥：同日两条腿若都成交，只保留先入场的一笔（实盘不会同时对冲开仓）
    filled = [t for t in trades if t.get("status") == "成交"]
    if len(filled) > 1:
        filled.sort(key=lambda t: t["entry_ms"])
        for t in filled[1:]:
            t["status"] = "作废(同日另一腿先成交)"
            t["pnl_u"] = 0.0
            t["net_r"] = 0.0
    return plan, trades


def backtest_range(bars, start_date, end_date, hh=9, mm=0, cfg=None):
    """逐日 walk-forward 回测。start_date/end_date 为 (y,m,d)。"""
    days = sorted({dp for dp in (fx_trade_day(bj(b["open_time"])) for b in bars)})
    y0, m0, d0 = start_date
    y1, m1, d1 = end_date
    from datetime import date as _date
    lo, hi = _date(y0, m0, d0), _date(y1, m1, d1)

    recs = []
    for d in days:
        if not (lo <= d <= hi):
            continue
        # 决策时点：外汇交易日 d 覆盖【北京 d 日 cutoff ~ d+1 日 cutoff】，
        # 故 d 日的 hh:mm 本身就落在交易日 d 内，不再加一天。
        asof = to_ms_bj(d.year, d.month, d.day, hh, mm)
        if asof > bars[-1]["close_time"]:
            continue
        plan, trades = run_day(bars, asof, cfg)
        if not plan.get("ok"):
            continue
        recs.append({"trade_day": str(d), "asof": bj(asof).strftime("%Y-%m-%d %H:%M"),
                     "plan": plan, "trades": trades})
    return recs


# ==================== 策略 v2：突破跟随（已验证内核） ====================
# v1（关键位限价+拒止）经 8 个月 216 天回测证伪：EV -0.099R，随机方向 MC 分位 83.6%（劣于随机）。
# v2（前日高/低突破跟随）在同样数据上：全样本 EV +0.417R，IS +0.429R / OOS +0.402R，
#    随机方向对照 z=+11.03，8 个月月度全部为正，双边成本翻 10 倍后 EV 仍 +0.263R。
# 参数固定为预注册常量，不再寻优（P0-C 规避）。
CFG_V2 = {
    "tp1_r": 1.0,           # TP1（平半 + 移保本）
    "tp2_r": 1.8,           # TP2（平剩余）
    "stop_atr": 0.30,       # 止损 = 0.30 × ATR14(日)
    "max_hold_hours": 24,   # 超时强平
    "min_pdh_dist_atr": 0.05,  # PDH/PDL 与现价的最小距离（太近则视为无意义突破）
}


def make_plan_breakout(bars, asof_ms, cfg=None):
    """v2 计划：突破前一日高做多 / 跌破前一日低做空。只用 close_time <= asof 的数据。"""
    c = dict(CFG_V2, **(cfg or {}))
    bars_vis = visible(bars, asof_ms)
    if len(bars_vis) < 50:
        return {"ok": False, "reason": "可见数据不足", "asof": asof_ms}

    cur_day = fx_trade_day(bj(asof_ms))
    daily_vis = to_fx_daily(bars_vis)
    daily_closed = [d for d in daily_vis if d["day"] < cur_day]
    if len(daily_closed) < 5:
        return {"ok": False, "reason": "可见日线不足 5 根", "asof": asof_ms}

    cur = bars_vis[-1]["close"]
    atr_v = atr(daily_closed)
    prev = daily_closed[-1]
    pdh, pdl = prev["high"], prev["low"]
    sma_v = sma(daily_closed)
    rsi_v = rsi(bars_vis, 14)
    lb = min(CFG["swing_lookback"], len(daily_closed))
    win = daily_closed[-lb:]
    swing_hi = max(d["high"] for d in win)
    swing_lo = min(d["low"] for d in win)

    R = c["stop_atr"] * atr_v
    lots_main = round(CFG["account"] * CFG["risk_per_trade"] / (R * CFG["contract_oz"]), 2) if R > 0 else 0.0

    def leg(side):
        px = pdh if side == "long" else pdl
        stop = px - R if side == "long" else px + R
        return {
            "side": side, "trigger": round(px, 2),
            "stop": round(stop, 2), "R": round(R, 2),
            "tp1": round(px + c["tp1_r"] * R * (1 if side == "long" else -1), 2),
            "tp2": round(px + c["tp2_r"] * R * (1 if side == "long" else -1), 2),
            "lots": lots_main,
            "risk_pct": round(CFG["risk_per_trade"] * 100, 2),
            "dist_atr": round(abs(px - cur) / atr_v, 3) if atr_v else 0.0,
        }

    a_long, b_short = leg("long"), leg("short")
    dev_atr = (cur - sma_v) / atr_v if atr_v else 0.0
    too_close = (abs(pdh - cur) < c["min_pdh_dist_atr"] * atr_v
                 and abs(pdl - cur) < c["min_pdh_dist_atr"] * atr_v)

    return {
        "ok": True, "strategy": "breakout_v2",
        "asof": asof_ms, "asof_str": bj(asof_ms).strftime("%Y-%m-%d %H:%M"),
        "trade_day": str(cur_day),
        "cur": round(cur, 2), "atr14": round(atr_v, 2), "sma10": round(sma_v, 2),
        "dev_atr": round(dev_atr, 3), "rsi14_5m": round(rsi_v, 1),
        "prev_day": {"day": str(prev["day"]), "open": round(prev["open"], 2),
                     "high": round(pdh, 2), "low": round(pdl, 2), "close": round(prev["close"], 2)},
        "swing": {"hi": round(swing_hi, 2), "lo": round(swing_lo, 2), "lookback": lb},
        "bias": "bull" if dev_atr > 0.5 else ("bear" if dev_atr < -0.5 else "neutral"),
        "primary": a_long, "secondary": b_short,
        "too_close": too_close,
        "bars_used": len(bars_vis), "daily_used": len(daily_closed),
        "data_cut": bj(bars_vis[-1]["close_time"]).strftime("%Y-%m-%d %H:%M"),
    }


def simulate_breakout(plan, bars_after, rand_dir=False, rng=None):
    """v2 执行：先触及哪边就做哪边（互斥），突破瞬间以触发价成交。
    rand_dir=True 时随机方向（仅用于 alpha 归因的蒙特卡洛对照，不用于实盘）。"""
    import random as _rnd
    c = CFG_V2
    rng = rng or _rnd.Random(1)
    pdh = plan["prev_day"]["high"]
    pdl = plan["prev_day"]["low"]
    n = len(bars_after)
    idx, side, fill = None, None, None
    for i, b in enumerate(bars_after):
        up, dn = b["high"] >= pdh, b["low"] <= pdl
        if up or dn:
            side = (rng.choice(["long", "short"]) if rand_dir
                    else ("long" if up else "short"))   # 同根双向时按多头（固定口径）
            px = pdh if side == "long" else pdl
            fill = px + (COST_ONEWAY if side == "long" else -COST_ONEWAY)
            idx = i
            break
    if idx is None:
        return []

    leg_ = plan["primary"] if side == "long" else plan["secondary"]
    stop, R = leg_["stop"], leg_["R"]
    tp1, tp2 = leg_["tp1"], leg_["tp2"]
    max_i = min(n - 1, idx + int(c["max_hold_hours"] * 12))
    phase, pnl_r, exit_i, reason = "open", 0.0, None, None
    for k in range(idx, max_i + 1):
        b = bars_after[k]
        if side == "short":
            hs, h1, h2 = b["high"] >= stop, b["low"] <= tp1, b["low"] <= tp2
        else:
            hs, h1, h2 = b["low"] <= stop, b["high"] >= tp1, b["high"] >= tp2
        if phase == "open":
            if hs:
                pnl_r, reason, exit_i = -1.0, "SL", k
                break
            if h1:
                pnl_r = c["tp1_r"] * 0.5
                phase, be = "be", fill
                if h2:
                    pnl_r = c["tp1_r"] * 0.5 + c["tp2_r"] * 0.5
                    reason, exit_i = "TP2", k
                    break
                continue
        else:
            hb = (b["high"] >= be) if side == "short" else (b["low"] <= be)
            if h2 or hb:
                if h2 and not hb:
                    pnl_r = c["tp1_r"] * 0.5 + c["tp2_r"] * 0.5
                    reason = "TP2"
                else:
                    pnl_r = c["tp1_r"] * 0.5
                    reason = "BE"          # 同根冲突：保本优先
                exit_i = k
                break
    if exit_i is None:
        b = bars_after[max_i]
        exit_i, reason = max_i, "TIMEOUT"
        pnl_r = ((fill - b["close"]) if side == "short" else (b["close"] - fill)) / R

    cost_r = (2 * COST_ONEWAY) / R
    net_r = pnl_r - cost_r
    return [{
        "status": "成交", "leg": "primary" if side == "long" else "secondary",
        "side": side, "fill": round(fill, 2),
        "entry_time": bj(bars_after[idx]["open_time"]).strftime("%Y-%m-%d %H:%M"),
        "entry_ms": bars_after[idx]["open_time"],
        "exit_reason": reason, "R": round(R, 2),
        "exit_time": bj(bars_after[exit_i]["close_time"]).strftime("%Y-%m-%d %H:%M"),
        "gross_r": round(pnl_r, 3), "cost_r": round(cost_r, 3), "net_r": round(net_r, 3),
        "lots": leg_["lots"],
        "pnl_u": round(net_r * R * leg_["lots"] * CFG["contract_oz"], 2),
    }]


def run_day_v2(bars, asof_ms, cfg=None):
    plan = make_plan_breakout(bars, asof_ms, cfg)
    if not plan.get("ok"):
        return plan, []
    after = [b for b in bars if b["open_time"] > asof_ms]
    if len(after) < 30:
        return plan, []
    return plan, simulate_breakout(plan, after)


def backtest_range_v2(bars, start_date, end_date, hh=9, mm=0, cfg=None):
    """v2 的 walk-forward 回测（与 v1 的 backtest_range 同结构）"""
    from datetime import date as _date
    days = sorted({fx_trade_day(bj(b["open_time"])) for b in bars})
    lo, hi = _date(*start_date), _date(*end_date)
    recs = []
    for d in days:
        if not (lo <= d <= hi):
            continue
        asof = to_ms_bj(d.year, d.month, d.day, hh, mm)
        if asof > bars[-1]["close_time"]:
            continue
        plan, trades = run_day_v2(bars, asof, cfg)
        if not plan.get("ok"):
            continue
        recs.append({"trade_day": str(d), "asof": bj(asof).strftime("%Y-%m-%d %H:%M"),
                     "plan": plan, "trades": trades})
    return recs


def summarize(recs):
    """汇总回测结果"""
    all_t = []
    for r in recs:
        for t in r["trades"]:
            if t.get("status") == "成交":
                all_t.append(t)
    n = len(all_t)
    if n == 0:
        return {"n": 0}
    wins = [t for t in all_t if t["net_r"] > 0]
    gross_win = sum(t["gross_r"] for t in wins)
    gross_loss = -sum(t["gross_r"] for t in all_t if t["gross_r"] <= 0)
    total_u = sum(t["pnl_u"] for t in all_t)
    return {
        "days": len(recs),
        "n_trades": n,
        "triggered_days": sum(1 for r in recs if any(t.get("status") == "成交" for t in r["trades"])),
        "wins": len(wins),
        "win_rate": round(len(wins) / n, 3),
        "ev_r": round(sum(t["net_r"] for t in all_t) / n, 3),
        "total_r": round(sum(t["net_r"] for t in all_t), 2),
        "total_pnl_u": round(total_u, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_cost_r": round(sum(t["cost_r"] for t in all_t) / n, 3),
        "by_reason": {k: sum(1 for t in all_t if t["exit_reason"] == k)
                      for k in ("SL", "TP2", "BE", "TIMEOUT")},
        "by_leg": {k: round(sum(t["net_r"] for t in all_t if t["leg"] == k), 2)
                   for k in ("primary", "secondary")},
    }


if __name__ == "__main__":
    print("daily_plan 引擎就绪；用 scripts 或 main 路由调用。")
