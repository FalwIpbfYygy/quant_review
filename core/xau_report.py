# -*- coding: utf-8 -*-
"""
 每日交易计划 v2 —— 完全独立模块：
1) 数据源直连价格接口基址 BINANCE_FAPI_BASE（，无 PAXG+12 偏移）
2) 完全不依赖 MySQL / PAXG+12 偏移口径
3) 全 URL 路径 /xau + 模板常量走全新文件名，避开任何历史 cache
4) 决策时点默认 = 当前北京时（点"生成"即 now）；数据严格 asof 截断：仅用 close_time ≤ asof 的已收盘 K 线，绝不使用决策点之后的 K 线（无未来函数）
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple

# ============================================================
# 1) 配置常量（不依赖 MySQL / 不依赖 daily_plan.py / 不依赖 PAXG）
# ============================================================
SYMBOL = ""
from config import BINANCE_FAPI_BASE as FAPI_BASE
ENDPOINT = "/fapi/v1/klines"
INTERVAL = "5m"               # 主决策周期
PAGE_LIMIT = 1000             # fapi 单次允许
MAX_PAGES = 200               # 安全阀：防止无限翻页

# 代理统一来自 config（默认直连；本地 Windows 出网在 .env 设 KLINE_PROXY）。
from config import PROXIES

# 北京时间 = UTC + 8
BJ = timezone(timedelta(hours=8))
UTC = timezone.utc

# 策略参数（用户可见的常量，可在这里调整）
CFG = {
    "stop_atr": 0.30,         # 止损 = 0.30 × ATR14
    "tp1_r": 1.0,             # 第一目标 = 1R
    "tp2_r": 1.8,             # 第二目标 = 1.8R
    "spread_usd": 0.30,       # 单边成本 = 0.30 美元/oz
    "slip_usd": 0.20,         # 滑点 = 0.20 美元/oz
    "account_usd": 10000.0,   # 仓位基准 1 万美元
    "risk_per_trade": 0.01,   # 单笔风险 1%
    "atr_period": 14,
    "daily_open_hour_bj": 8,  # 外汇日切分（UTC 0:00 = BJ 08:00）
    "decision_hour_bj": 9,    # 默认决策时点 BJ 09:00
}

# 内存缓存：URL -> (ts, body)  -- 用 TTL 防过期
_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_S = 60


# ============================================================
# 2) 时间工具（避免再踩双重偏移坑）
# ============================================================
def bj(ts_ms: int) -> datetime:
    """UTC 毫秒 -> 北京时间 datetime"""
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(BJ)


def to_ms_bj(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> int:
    """北京时间 y-m-d hh:mm -> UTC 毫秒"""
    dt = datetime(y, m, d, hh, mm, tzinfo=BJ)
    return int(dt.astimezone(UTC).timestamp() * 1000)


def to_ms_utc(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.astimezone(UTC).timestamp() * 1000)


def fmt_bj(ts_ms: int, pattern: str = "%Y-%m-%d %H:%M") -> str:
    return bj(ts_ms).strftime(pattern)


def now_ms() -> int:
    return int(time.time() * 1000)


# ============================================================
# 0) 拉数据（fastapi 路由代理 fapi，与 /api/realtime/klines 同链路：PROXIES + requests）
#    本模块只接受 bars 参数（纯计算单元，方便 sandbox 测）。
# ============================================================
# 拉数据函数 —— 由 main.py 的路由调用。需要传符号 / 区间 / 起止时间。
def _normalize_klines(raw):
    """raw = Binance fapi 标准 kline 列表"""
    out = []
    for k in raw:
        ot = int(k[0])
        out.append({
            "open_time": ot,
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "close_time": int(k[6]),
            "volume": float(k[5]),
        })
    out.sort(key=lambda b: b["open_time"])
    return out


def fetch_klines_paged(start_ms, end_ms, interval=None, page_limit=1000, fetch=None):
    """
    fetch(url) -> raw list  -- 由 main.py 注入，使用项目内的 PROXIES + requests
    """
    interval = interval or INTERVAL
    out = []
    cursor = start_ms
    pages = 0
    while cursor < end_ms and pages < MAX_PAGES:
        url = (
            f"{FAPI_BASE}{ENDPOINT}?symbol={SYMBOL}"
            f"&interval={interval}&startTime={cursor}&endTime={end_ms}&limit={page_limit}"
        )
        try:
            raw = fetch(url) if fetch else None
        except Exception as e:
            raise RuntimeError(f"fapi 拉取失败: {e}") from e
        if not raw:
            break
        for b in _normalize_klines(raw):
            if start_ms <= b["open_time"] < end_ms:
                out.append(b)
        last_ot = int(raw[-1][0])
        if last_ot <= cursor:
            break
        cursor = last_ot + 1
        pages += 1
    return out


# ============================================================
# 4) 指标 + 外汇日聚合
# ============================================================
def atr(bars: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    """ATR(period) —— 用前 N 根（不含最后一根未确认）"""
    if len(bars) < period + 1:
        return None
    closed = bars[:-1]   # 严格不含最后一根未确认
    if len(closed) < period:
        return None
    trs: List[float] = []
    prev_close = closed[0]["close"]
    for b in closed[1:period + 1]:
        tr = max(b["high"] - b["low"], abs(b["high"] - prev_close), abs(b["low"] - prev_close))
        trs.append(tr)
        prev_close = b["close"]
    return sum(trs) / period if trs else None


def sma(arr: List[float], period: int) -> Optional[float]:
    if len(arr) < period:
        return None
    return sum(arr[-period:]) / period


def to_fx_daily(bars: List[Dict[str, Any]], asof_ms: int) -> Dict[str, Any]:
    """
    按 BJ 时区日期切分 K线，返回 {"prev_day":{...}, "today":{...}, "daily_used":int}
    - prev_day: asof 之前最近一个完整交易日 (BJ 08:00 -> BJ 08:00)
    - today: asof 当日（开盘到 asof）
    - daily_used: 本次回测使用的日级 K 线数
    """
    asof_dt = bj(asof_ms)
    today_key = asof_dt.date().isoformat()
    # 找 prev_day 的结束时间（BJ 08:00 today）
    today_open_ms = to_ms_bj(asof_dt.year, asof_dt.month, asof_dt.day, 0, 0)
    # 往上倒退寻找"前一完整日"
    cursor_ms = today_open_ms - 1
    cursor_dt = bj(cursor_ms)
    prev_key = cursor_dt.date().isoformat()
    # 再上一日 0:00 BJ
    prev_open_ms = to_ms_bj(cursor_dt.year, cursor_dt.month, cursor_dt.day, 0, 0) - 86400_000

    def agg(s: int, e: int) -> Dict[str, Any]:
        sub = [b for b in bars if s <= b["open_time"] < e]
        if not sub:
            return {"high": None, "low": None, "open": None, "close": None, "n": 0}
        return {
            "high": max(b["high"] for b in sub),
            "low": min(b["low"] for b in sub),
            "open": sub[0]["open"],
            "close": sub[-1]["close"],
            "n": len(sub),
        }

    prev = agg(prev_open_ms, today_open_ms)
    today = agg(today_open_ms, asof_ms + 1)
    prev["day"] = prev_key
    prev["open_ms"] = prev_open_ms
    prev["close_ms"] = today_open_ms - 1
    today["day"] = today_key
    today["open_ms"] = today_open_ms
    today["close_ms"] = asof_ms
    return {"prev_day": prev, "today": today}


def visible(bars: List[Dict[str, Any]], asof_ms: int) -> List[Dict[str, Any]]:
    """严格 asof 截断：只保留已收盘（close_time <= asof_ms）的 bar。
    这样连"正在形成的当根 K 线"也不使用，彻底无未来函数。"""
    return [b for b in bars if b["close_time"] <= asof_ms]


# ============================================================
# 5) 突破跟随 PDH/PDL 信号（v2 生产内核，简化版，不依赖旧 daily_plan）
# ============================================================
def make_plan(bars: List[Dict[str, Any]], asof_ms: int) -> Dict[str, Any]:
    """
    返回字段（前端消费的字段）：
      asof_str, cur, atr14, atrPct, prev_day(day, high, low, open, close, n),
      today(day, high, low, open, close, n, last_bar_ts), bars_used, daily_used,
      ok, reason, primary(side: long/short, trigger, stop, tp1, tp2, R, lots, entry),
      secondary(...), bias, distCurAtr, too_close
    """
    out: Dict[str, Any] = {
        "asof_str": fmt_bj(asof_ms),
        "ok": False,
        "reason": "数据不足",
        "bars_used": 0,
        "daily_used": 0,
        "primary": None,
        "secondary": None,
        "bias": "none",
        "too_close": False,
        "distCurAtr": "—",
    }
    v = visible(bars, asof_ms)
    if len(v) < 200:
        out["reason"] = f"可见 K 线仅 {len(v)} 根 (< 200)"
        return out

    cur = v[-1]["close"]
    a = atr(v, CFG["atr_period"])
    if a is None or a <= 0:
        out["reason"] = "ATR 不足"
        return out

    out["bars_used"] = len(v)
    out["cur"] = round(cur, 2)
    out["atr14"] = round(a, 2)
    out["atrPct"] = round(a / cur * 100, 2)

    fx = to_fx_daily(v, asof_ms)
    prev = fx["prev_day"]
    today = fx["today"]
    out["prev_day"] = {
        "day": prev["day"], "high": prev["high"], "low": prev["low"],
        "open": prev["open"], "close": prev["close"], "n": prev["n"],
    }
    out["today"] = {
        "day": today["day"], "high": today["high"], "low": today["low"],
        "open": today["open"], "close": today["close"], "n": today["n"],
    }
    out["daily_used"] = max(prev["n"], today["n"])

    if prev["high"] is None or prev["low"] is None:
        out["reason"] = "前日 OHLC 缺失"
        return out

    pdh = prev["high"]
    pdl = prev["low"]

    # bias：方向倾向（只看 asof 之前的 K 线）
    closes = [b["close"] for b in v[-50:]]
    if len(closes) > 5:
        last5_avg = sum(closes[-5:]) / 5
        prev6 = closes[-6]
        out["bias"] = "long" if last5_avg > prev6 else "short"
    else:
        out["bias"] = "long"

    # 主计划：突破 PDH 做多；跌破 PDL 做空。同一根 K 线先触及者胜。
    # v2 突破跟随信号
    primary_side = None
    primary_trigger = None
    primary_entry = None
    primary_stop = None
    primary_tp1 = None
    primary_tp2 = None
    secondary_side = None

    # 用 asof 之前最后一根 K 线触发
    last_bar = v[-1]
    if last_bar["high"] >= pdh >= last_bar["open"] and last_bar["close"] >= pdh:
        primary_side = "long"
        primary_trigger = round(pdh + 0.5, 2)
        primary_entry = round(pdh, 2)
        primary_stop = round(pdh - a * CFG["stop_atr"], 2)
        primary_tp1 = round(pdh + a * CFG["stop_atr"] * CFG["tp1_r"], 2)
        primary_tp2 = round(pdh + a * CFG["stop_atr"] * CFG["tp2_r"], 2)
        secondary_side = "short"
    elif last_bar["low"] <= pdl <= last_bar["open"] and last_bar["close"] <= pdl:
        primary_side = "short"
        primary_trigger = round(pdl - 0.5, 2)
        primary_entry = round(pdl, 2)
        primary_stop = round(pdl + a * CFG["stop_atr"], 2)
        primary_tp1 = round(pdl - a * CFG["stop_atr"] * CFG["tp1_r"], 2)
        primary_tp2 = round(pdl - a * CFG["stop_atr"] * CFG["tp2_r"], 2)
        secondary_side = "long"
    else:
        # 另一种判定：当日是否已经接近 PDH/PDL（用于"潜在触发"展示）
        spread = pdh - pdl
        if cur > pdh:
            # 已在 PDH 之上 → 不入场，仅输出"突破做多"的参考位
            primary_side = "long"
            primary_trigger = round(cur, 2)
            primary_entry = round(cur, 2)
            primary_stop = round(cur - a * CFG["stop_atr"], 2)
            primary_tp1 = round(cur + a * CFG["stop_atr"] * CFG["tp1_r"], 2)
            primary_tp2 = round(cur + a * CFG["stop_atr"] * CFG["tp2_r"], 2)
        elif cur < pdl:
            primary_side = "short"
            primary_trigger = round(cur, 2)
            primary_entry = round(cur, 2)
            primary_stop = round(cur + a * CFG["stop_atr"], 2)
            primary_tp1 = round(cur - a * CFG["stop_atr"] * CFG["tp1_r"], 2)
            primary_tp2 = round(cur - a * CFG["stop_atr"] * CFG["tp2_r"], 2)
        elif spread < a * CFG["stop_atr"] * 4:
            # 区间太窄，无 alpha
            out["too_close"] = True
            out["reason"] = f"PDH/PDL 区间 {spread:.2f} 美元 < 1.2R 阈值"
            out["distCurAtr"] = round((cur - (pdh + pdl) / 2) / a, 3)
            return out
        else:
            # 区间内：根据 bias 给潜在方向（仍是"潜在"——需等突破才触发）
            primary_side = "long" if out["bias"] == "long" else "short"
            pdh_dist = pdh - cur
            pdl_dist = cur - pdl
            primary_trigger = pdh if primary_side == "long" else pdl
            primary_entry = primary_trigger
            primary_stop = (primary_trigger - a * CFG["stop_atr"]) if primary_side == "long" else (primary_trigger + a * CFG["stop_atr"])
            primary_tp1 = (primary_trigger + a * CFG["stop_atr"] * CFG["tp1_r"]) if primary_side == "long" else (primary_trigger - a * CFG["stop_atr"] * CFG["tp1_r"])
            primary_tp2 = (primary_trigger + a * CFG["stop_atr"] * CFG["tp2_r"]) if primary_side == "long" else (primary_trigger - a * CFG["stop_atr"] * CFG["tp2_r"])
            out["reason"] = "区间内，需等突破"
            out["distCurAtr"] = round((cur - (pdh + pdl) / 2) / a, 3)
            secondary_side = "short" if primary_side == "long" else "long"

    if primary_side:
        R = a * CFG["stop_atr"]
        risk_usd = CFG["account_usd"] * CFG["risk_per_trade"]
        lots = round(risk_usd / (R * 100), 2)  # 100 oz/手
        out["primary"] = {
            "side": primary_side, "trigger": primary_trigger, "entry": primary_entry,
            "stop": primary_stop, "tp1": primary_tp1, "tp2": primary_tp2,
            "R": round(R, 2), "lots": lots,
        }
        if secondary_side and secondary_side != primary_side:
            out["secondary"] = {
                "side": secondary_side, "trigger": pdl if secondary_side == "long" else pdh,
                "note": "反向突破备用策略（破坏即触发）",
            }
        out["ok"] = True

    out["distCurAtr"] = round((cur - (pdh + pdl) / 2) / a, 3)
    return out


def run_day(bars: List[Dict[str, Any]], asof_ms: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    单日 asof 走一次：返回 (plan, sim)
    sim 是 [{ts, side, entry, exit, ret_R}, ...] 的完整出入场明细
    """
    v = visible(bars, asof_ms)
    plan = make_plan(v, asof_ms)
    sim: List[Dict[str, Any]] = []

    if not plan.get("ok") or not plan.get("primary"):
        # 区间内或数据不足，按"观望"返回空 sim
        return plan, sim

    primary = plan["primary"]
    side = primary["side"]
    R = primary["R"]
    trigger = primary["trigger"]
    stop = primary["stop"]
    tp1 = primary["tp1"]
    tp2 = primary["tp2"]

    # 从 asof 开始往后扫描 K 线，找首次触发（突破 trigger）
    after = [b for b in bars if b["open_time"] > asof_ms]
    if not after:
        return plan, sim

    entry_idx = None
    for i, b in enumerate(after):
        if side == "long" and b["high"] >= trigger:
            entry_idx = i; break
        if side == "short" and b["low"] <= trigger:
            entry_idx = i; break
    if entry_idx is None:
        return plan, sim

    entry_bar = after[entry_idx]
    entry_price = trigger  # 突破时刻成交
    # 扣成本（双边）
    cost_per_side = CFG["spread_usd"] + CFG["slip_usd"]
    if side == "long":
        entry_price += cost_per_side
    else:
        entry_price -= cost_per_side

    # 找出场
    exit_price = None
    exit_time = None
    exit_reason = None
    for b in after[entry_idx + 1:]:
        if side == "long":
            if b["low"] <= stop:
                exit_price = stop - cost_per_side
                exit_time = b["close_time"]
                exit_reason = "止损"
                break
            if b["high"] >= tp2:
                exit_price = tp2 - cost_per_side
                exit_time = b["close_time"]
                exit_reason = "止盈2"
                break
            if b["high"] >= tp1:
                # 半仓 TP1，剩余到 TP2 或 stop
                remaining_after = after[after.index(b) + 1:]
                exit_partial_price = tp1 - cost_per_side
                exit_partial_time = b["close_time"]
                ret_partial = (tp1 - stop) / R if side == "long" else (stop - tp1) / R
                # 模拟半仓：记第一段
                sim.append({
                    "side": side, "entry_t": asof_ms, "entry_price": round(entry_price, 2),
                    "exit_t": exit_partial_time, "exit_price": round(exit_partial_price, 2),
                    "ret_R": round(ret_partial, 3), "reason": "TP1 半仓",
                })
                # 剩余仓位尝试 TP2 或 保本
                for b2 in remaining_after:
                    if b2["low"] <= stop:
                        exit_price = entry_price  # 保本（推到 entry）
                        exit_time = b2["close_time"]
                        exit_reason = "保本"
                        break
                    if b2["high"] >= tp2:
                        exit_price = tp2 - cost_per_side
                        exit_time = b2["close_time"]
                        exit_reason = "TP2 剩余半仓"
                        break
                if exit_price is None:
                    # 当日关闭推到收盘
                    exit_price = remaining_after[-1]["close"] - cost_per_side
                    exit_time = remaining_after[-1]["close_time"]
                    exit_reason = "日终收盘"
                ret_main = (exit_price - (stop if side == "long" else tp1)) / R if False else 0
                if side == "long":
                    ret_main = (exit_price - stop) / R - 0.5 * ret_partial
                else:
                    ret_main = (stop - exit_price) / R - 0.5 * ret_partial
                sim.append({
                    "side": side, "entry_t": asof_ms, "entry_price": round(entry_price, 2),
                    "exit_t": exit_time, "exit_price": round(exit_price, 2),
                    "ret_R": round(ret_main, 3), "reason": exit_reason or "出场",
                })
                return plan, sim
        else:  # short
            if b["high"] >= stop:
                exit_price = stop + cost_per_side
                exit_time = b["close_time"]
                exit_reason = "止损"
                break
            if b["low"] <= tp2:
                exit_price = tp2 + cost_per_side
                exit_time = b["close_time"]
                exit_reason = "止盈2"
                break
            if b["low"] <= tp1:
                remaining_after = after[after.index(b) + 1:]
                exit_partial_price = tp1 + cost_per_side
                exit_partial_time = b["close_time"]
                ret_partial = (tp1 - stop) / R
                sim.append({
                    "side": side, "entry_t": asof_ms, "entry_price": round(entry_price, 2),
                    "exit_t": exit_partial_time, "exit_price": round(exit_partial_price, 2),
                    "ret_R": round(ret_partial, 3), "reason": "TP1 半仓",
                })
                for b2 in remaining_after:
                    if b2["high"] >= stop:
                        exit_price = entry_price
                        exit_time = b2["close_time"]
                        exit_reason = "保本"
                        break
                    if b2["low"] <= tp2:
                        exit_price = tp2 + cost_per_side
                        exit_time = b2["close_time"]
                        exit_reason = "TP2 剩余半仓"
                        break
                if exit_price is None:
                    exit_price = remaining_after[-1]["close"] + cost_per_side
                    exit_time = remaining_after[-1]["close_time"]
                    exit_reason = "日终收盘"
                if side == "long":
                    ret_main = (stop - exit_price) / R - 0.5 * ret_partial
                else:
                    ret_main = (exit_price - stop) / R - 0.5 * ret_partial
                sim.append({
                    "side": side, "entry_t": asof_ms, "entry_price": round(entry_price, 2),
                    "exit_t": exit_time, "exit_price": round(exit_price, 2),
                    "ret_R": round(ret_main, 3), "reason": exit_reason or "出场",
                })
                return plan, sim

    # 止损/止盈2 直接出场（无 TP1）
    if exit_price is None:
        exit_price = after[-1]["close"] - cost_per_side if side == "long" else after[-1]["close"] + cost_per_side
        exit_time = after[-1]["close_time"]
        exit_reason = "日终收盘"
    if side == "long":
        ret_R = (exit_price - stop) / R
    else:
        ret_R = (stop - exit_price) / R
    sim.append({
        "side": side, "entry_t": asof_ms, "entry_price": round(entry_price, 2),
        "exit_t": exit_time, "exit_price": round(exit_price, 2),
        "ret_R": round(ret_R, 3), "reason": exit_reason,
    })
    return plan, sim


# ============================================================
# 6) 回测：遍历 [start, end] 内所有"决策日"
# ============================================================
def backtest_range(start_bj: str, end_bj: str, decision_hour_bj: int = 9) -> Dict[str, Any]:
    """
    入口：start_bj / end_bj = "YYYY-MM-DD"（北京时）
    决策时点：每日 BJ 09:00（可调）
    返回：{ n_trades, win_rate, ev_r, profit_factor, monthly, recent, records }
    """
    sy, sm, sd = map(int, start_bj.split("-"))
    ey, em, ed = map(int, end_bj.split("-"))
    start_ms = to_ms_bj(sy, sm, sd, decision_hour_bj, 0) - 2 * 86400_000
    end_ms = to_ms_bj(ey, em, ed, decision_hour_bj, 0) + 24 * 86400_000

    try:
        all_bars = fetch_klines(start_ms, end_ms, INTERVAL)
    except Exception as e:
        return {"code": 500, "error": str(e), "n_trades": 0,
                "win_rate": 0, "ev_r": 0, "profit_factor": 0, "monthly": [], "recent": [], "records": []}

    if len(all_bars) < 200:
        return {"code": 200, "n_trades": 0, "win_rate": 0, "ev_r": 0, "profit_factor": 0,
                "monthly": [], "recent": [], "records": [],
                "note": f"窗口内只拉到 {len(all_bars)} 根"}

    records: List[Dict[str, Any]] = []
    cur = datetime(sy, sm, sd, decision_hour_bj, 0, tzinfo=BJ)
    end_dt = datetime(ey, em, ed, decision_hour_bj, 0, tzinfo=BJ)
    one = timedelta(days=1)
    while cur <= end_dt:
        asof_ms = to_ms_bj(cur.year, cur.month, cur.day, cur.hour, cur.minute)
        # 周末跳过（外汇日但币安期货 24x7；周末波动小）
        if cur.weekday() >= 5:
            cur += one; continue
        plan, sim = run_day(all_bars, asof_ms)
        if sim:
            for s in sim:
                records.append({
                    "day": cur.strftime("%Y-%m-%d"),
                    "side": s["side"],
                    "entry_price": s["entry_price"],
                    "exit_price": s["exit_price"],
                    "ret_R": s["ret_R"],
                    "reason": s["reason"],
                })
        cur += one

    # 汇总
    if not records:
        return {"code": 200, "n_trades": 0, "win_rate": 0, "ev_r": 0, "profit_factor": 0,
                "monthly": [], "recent": [], "records": [], "note": "无触发"}

    n = len(records)
    wins = [r["ret_R"] for r in records if r["ret_R"] > 0]
    losses = [r["ret_R"] for r in records if r["ret_R"] <= 0]
    win_rate = len(wins) / n if n else 0
    ev = sum(r["ret_R"] for r in records) / n if n else 0
    gross_win = sum(wins) if wins else 0
    gross_loss = sum(abs(x) for x in losses) if losses else 0
    pf = (gross_win / gross_loss) if gross_loss > 0 else None

    # 月度分布
    by_month: Dict[str, float] = {}
    for r in records:
        mk = r["day"][:7]
        by_month[mk] = by_month.get(mk, 0) + r["ret_R"]
    monthly = [{"month": m, "ev": round(v, 3)} for m, v in sorted(by_month.items())]

    recent = records[-15:][::-1]
    return {
        "code": 200,
        "n_trades": n,
        "win_rate": round(win_rate, 4),
        "ev_r": round(ev, 3),
        "profit_factor": round(pf, 2) if pf is not None else None,
        "monthly": monthly,
        "recent": recent,
        "records": records,
    }


# ============================================================
# 7) 高层 API 包装（main.py 直接调用）
# ============================================================
def api_plan(asof_bj: Optional[str] = None, fetch_fn=None) -> Dict[str, Any]:
    """
    asof_bj: "YYYY-MM-DD HH:MM"（北京时）。缺省 = 当前北京时（now）
    fetch_fn: (url) -> raw list  由 main.py 注入，使用项目内的 PROXIES + requests
    返回 { code, plan, klines, warns, source, bar_count, fetch_ms }
    """
    if asof_bj:
        try:
            dt = datetime.strptime(asof_bj, "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
        except ValueError:
            return {"code": 400, "error": f"asof 格式错误：{asof_bj}"}
    else:
        dt = datetime.now(BJ)
    asof_ms = to_ms_bj(dt.year, dt.month, dt.day, dt.hour, dt.minute)

    start_ms = asof_ms - 2 * 86400_000
    end_ms = asof_ms  # 只拉 asof 之前的数据，连"未来 K 线"都不请求

    t0 = time.time()
    try:
        bars = fetch_klines_paged(start_ms, end_ms, INTERVAL, fetch=fetch_fn)
    except Exception as e:
        return {"code": 502, "error": f"fapi 拉取失败: {e}", "plan": None}
    fetch_ms_val = int((time.time() - t0) * 1000)

    plan = make_plan(bars, asof_ms)
    v = visible(bars, asof_ms)
    klines = [{
        "t": fmt_bj(b["open_time"]),
        "o": round(b["open"], 2),
        "c": round(b["close"], 2),
        "l": round(b["low"], 2),
        "h": round(b["high"], 2),
    } for b in v[-432:]]

    warns: List[Dict[str, Any]] = []
    last_ct = v[-1]["close_time"] if v else 0
    if asof_ms - last_ct > 3600_000:
        warns.append({
            "level": "warn",
            "t": "数据滞后",
            "m": f"本地可见 K 线止于 {fmt_bj(last_ct)}",
        })
    if dt.weekday() >= 5 and plan.get("prev_day", {}).get("day"):
        warns.append({
            "level": "warn",
            "t": "周末薄盘",
            "m": f"前一交易日 {plan['prev_day']['day']} 是周末",
        })
    if plan.get("too_close"):
        warns.append({"level": "warn", "t": "区间过窄", "m": "PDH/PDL < 1.2R，无 alpha"})

    return {
        "code": 200,
        "plan": plan,
        "klines": klines,
        "warns": warns,
        "source": f"{FAPI_BASE or '价格接口基址'} {SYMBOL} {INTERVAL}",
        "bar_count": len(bars),
        "visible_count": len(v),
        "fetch_ms": fetch_ms_val,
        "asof_str": plan.get("asof_str"),
        "asof_ms": asof_ms,
    }


def api_backtest(start_bj: str, end_bj: str, decision_hour_bj: int = 9, fetch_fn=None) -> Dict[str, Any]:
    """fetch_fn: (url) -> raw list  由 main.py 注入"""
    sy, sm, sd = map(int, start_bj.split("-"))
    ey, em, ed = map(int, end_bj.split("-"))
    start_ms = to_ms_bj(sy, sm, sd, decision_hour_bj, 0) - 2 * 86400_000
    end_ms = to_ms_bj(ey, em, ed, decision_hour_bj, 0) + 24 * 86400_000

    try:
        all_bars = fetch_klines_paged(start_ms, end_ms, INTERVAL, fetch=fetch_fn)
    except Exception as e:
        return {"code": 500, "error": str(e), "n_trades": 0,
                "win_rate": 0, "ev_r": 0, "profit_factor": 0,
                "monthly": [], "recent": [], "records": []}

    if len(all_bars) < 200:
        return {"code": 200, "n_trades": 0, "win_rate": 0, "ev_r": 0,
                "profit_factor": 0, "monthly": [], "recent": [], "records": [],
                "note": f"窗口内只拉到 {len(all_bars)} 根"}

    records: List[Dict[str, Any]] = []
    cur = datetime(sy, sm, sd, decision_hour_bj, 0, tzinfo=BJ)
    end_dt = datetime(ey, em, ed, decision_hour_bj, 0, tzinfo=BJ)
    one = timedelta(days=1)
    while cur <= end_dt:
        asof_ms = to_ms_bj(cur.year, cur.month, cur.day, cur.hour, cur.minute)
        if cur.weekday() >= 5:
            cur += one; continue
        plan, sim = run_day(all_bars, asof_ms)
        if sim:
            for s in sim:
                records.append({
                    "day": cur.strftime("%Y-%m-%d"),
                    "side": s["side"],
                    "entry_price": s["entry_price"],
                    "exit_price": s["exit_price"],
                    "ret_R": s["ret_R"],
                    "reason": s["reason"],
                })
        cur += one

    if not records:
        return {"code": 200, "n_trades": 0, "win_rate": 0, "ev_r": 0,
                "profit_factor": 0, "monthly": [], "recent": [], "records": [],
                "note": "无触发"}

    n = len(records)
    wins = [r["ret_R"] for r in records if r["ret_R"] > 0]
    losses = [r["ret_R"] for r in records if r["ret_R"] <= 0]
    win_rate = len(wins) / n if n else 0
    ev = sum(r["ret_R"] for r in records) / n if n else 0
    gross_win = sum(wins) if wins else 0
    gross_loss = sum(abs(x) for x in losses) if losses else 0
    pf = (gross_win / gross_loss) if gross_loss > 0 else None

    by_month: Dict[str, float] = {}
    for r in records:
        mk = r["day"][:7]
        by_month[mk] = by_month.get(mk, 0) + r["ret_R"]
    monthly = [{"month": m, "ev": round(v, 3)} for m, v in sorted(by_month.items())]

    recent = records[-15:][::-1]
    return {
        "code": 200,
        "n_trades": n,
        "win_rate": round(win_rate, 4),
        "ev_r": round(ev, 3),
        "profit_factor": round(pf, 2) if pf is not None else None,
        "monthly": monthly,
        "recent": recent,
        "records": records,
        "source": f"{FAPI_BASE or '价格接口基址'} {SYMBOL} {INTERVAL}",
    }


# ============================================================
# 8) 命令行自测（fetch_fn 用 urllib 直连）
# ============================================================
if __name__ == "__main__":
    import sys as _s
    import urllib.request
    import urllib.error

    def _mock_fetch(url):
        """CLI 自测时用一个内存生成器构造稳定 mock 数据"""
        # 解析 url
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        sym = q.get("symbol", [""])[0]
        iv = q.get("interval", ["5m"])[0]
        st = int(q.get("startTime", ["0"])[0])
        ed = int(q.get("endTime", ["99999999999999"])[0])
        iv_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000}.get(iv, 300000)
        if st == 0 or ed == 0:
            return []
        n = min(1000, max(1, (ed - st) // iv_ms + 1))
        random_idx = sum(ord(c) for c in sym + iv)
        rnd = __import__("random").Random(random_idx + st)
        cur = 4400.0
        out = []
        for i in range(n):
            ot = st + i * iv_ms
            if ot >= ed:
                break
            cur += rnd.uniform(-1.5, 1.3)
            op = cur - 0.5
            cl = cur + rnd.uniform(-0.6, 0.6)
            hi = max(op, cl) + abs(rnd.uniform(0.1, 1.5))
            lo = min(op, cl) - abs(rnd.uniform(0.1, 1.5))
            out.append([ot, op, hi, lo, cl, 100, ot + iv_ms - 1, 1000, 0, 0, 0, 0])
        return out

    if len(_s.argv) > 1 and _s.argv[1] == "plan":
        asof = _s.argv[2] if len(_s.argv) > 2 else None
        j = api_plan(asof, fetch_fn=_mock_fetch)
        print(json.dumps(j, ensure_ascii=False, indent=2, default=str)[:3000])
    elif len(_s.argv) > 1 and _s.argv[1] == "backtest":
        s = _s.argv[2] if len(_s.argv) > 2 else "2026-08-07"
        e = _s.argv[3] if len(_s.argv) > 3 else "2026-09-04"
        j = api_backtest(s, e, fetch_fn=_mock_fetch)
        print(json.dumps({k: v for k, v in j.items() if k != "records"},
                         ensure_ascii=False, indent=2, default=str)[:1500])
    else:
        print("用法: python xau_report.py plan [asof_bj] | python xau_report.py backtest [start] [end]")
