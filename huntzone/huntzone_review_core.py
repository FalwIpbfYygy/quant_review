# -*- coding: utf-8 -*-
"""多日狩猎区复盘工具（/huntzone-review）编排层 — 复刻 hunting_system/daily_push 口径。

改动（2026-10-09 修正）：
  - 数据源不再走 quant_review 自己的 huntv2_core.fetch_daily_1d，
    而是直接复刻 hunting_system/daily_push.py 的 load_bars_primary()：
    优先 Twelve Data XAU/USD spot D1（America/New_York 日界），失败回退本地现货 CSV。
  - 信号生成直接复刻 daily_push.gen_signal()：SMA10 顺势符号 + S_MODEL_FROZEN + build()，
    默认 Config() 与官方 production 一致（trend_filter='ma3', vol_filter=1.5 仅作标注，不拦截信号）。
  - 输出结构改为按「交易日一列」组织：panels[] 每个含当日 30m K线 + ladder 档位。

红线：
  - 严格零未来函数：每日 signal 只用 ≤ 该日收盘的日线；30m 聚合只用已逝 1m bar。
  - 取数失败 / 无信号 → 明确返回 ok=False / has_signal=False，绝不猜 S。
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
import time
import requests

from data.data_sync import PROXIES as _FAPI_PROXIES
from huntzone import huntzone_review_hs_data as hs_data
from huntzone.huntback_sim import _date_to_open_ms

UTC = timezone.utc

# ---- fapi  永续蜡烛（/huntzone-review 蜡烛口径，用户指定 2026-10-10） ----
# 替代原本地库 kline_1m（PAXGUSDT 现货 +12 偏移）1m→30m 聚合。
from config import FAPI_KLINES  # 价格接口基址
_XAU_FAPI_SYMBOL = ""


def _fapi_get(url, timeout=15, retries=4, backoff=1.0):
    """复用项目代理链路取 fapi klines，带重试 + 指数退避（抗本地代理偶发抖动）。"""
    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, proxies=_FAPI_PROXIES, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    if last is not None:
        raise last
    raise RuntimeError("fapi 取数失败")


def _utc_date_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _fetch_30m_range_fapi(start_ms: int, end_ms: int) -> Dict[str, List[List[float]]]:
    """整段批量拉 fapi  30m，按 UTC 日期分组。失败抛异常（由调用方转 missing）。

    单请求上限 1500 根；30m × 30 天 = 1440 < 1500，正常单请求覆盖；
    若区间更大则按页续拉（每页续到上一页最后 openTime 之后）。
    """
    out: Dict[str, List[List[float]]] = {}
    cur = start_ms
    safety = 0
    while cur < end_ms and safety < 50:
        safety += 1
        url = (FAPI_KLINES + "?symbol=%s&interval=30m&startTime=%d&endTime=%d&limit=1500"
               % (_XAU_FAPI_SYMBOL, cur, end_ms))
        rows = _fapi_get(url)
        if not rows:
            break
        for r in rows:
            ts = int(r[0])
            o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
            out.setdefault(_utc_date_str(ts), []).append([ts, o, h, l, c])
        last_ts = int(rows[-1][0])
        if last_ts >= end_ms - 1:
            break
        cur = last_ts + 1
    for d in out:
        out[d].sort(key=lambda b: b[0])
    return out


def _iter_dates_range(start: str, end: str) -> List[str]:
    """[start, end] 闭区间所有自然日，升序。"""
    s = _date_to_open_ms(start)
    e = _date_to_open_ms(end)
    if e < s:
        s, e = e, s
    out = []
    cur = datetime.fromtimestamp(s / 1000, tz=UTC)
    end_dt = datetime.fromtimestamp(e / 1000, tz=UTC)
    while cur <= end_dt:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out




def _level_price(lad: dict, ratio: float) -> Optional[float]:
    for lv in lad.get("levels", []):
        if abs(round(lv["ratio"], 3) - round(ratio, 3)) < 1e-9:
            return float(lv["price"])
    return None


def _build_panel(date: str, sig: Optional[dict], candles_30m: List[List[float]],
                 missing_1m: bool) -> dict:
    """把 gen_signal 结果 + 30m K线 组装成前端需要的 panel。"""
    lad = sig.get("lad") if sig else None
    if lad is None:
        return {
            "date": date,
            "has_signal": False,
            "direction": None,
            "direction_cn": "无信号",
            "open_px": None,
            "S": None,
            "S_mae": None,
            "zone_lo": None,
            "zone_hi": None,
            "zone_mid": None,
            "stop": None,
            "警戒": None,
            "exh1": None,
            "exh2": None,
            "t1": None,
            "ma3_ok": None,
            "vol_ok": None,
            "levels": [],
            "candles_30m": candles_30m,
            "missing_1m": missing_1m,
        }

    direction = lad.get("direction")
    levels = []
    for lv in lad.get("levels", []):
        levels.append({
            "ratio": lv["ratio"],
            "name": lv["name"],
            "price": round(float(lv["price"]), 2),
        })

    return {
        "date": date,
        "has_signal": True,
        "direction": direction,
        "direction_cn": lad.get("direction_cn",
                                "做空" if direction == "short" else "做多"),
        "source": None,  # 顶层 range 会统一给 source
        "open_px": round(float(lad.get("open_px")), 2),
        "S": round(float(lad.get("S")), 2),
        "S_mae": round(float(sig.get("S_mae")), 2),
        "zone_lo": round(float(lad.get("zone_lo")), 2),
        "zone_hi": round(float(lad.get("zone_hi")), 2),
        "zone_mid": round(float(lad.get("zone_mid")), 2),
        "stop": round(float(lad.get("stop")), 2),
        "警戒": round(float(_level_price(lad, 0.809)), 2) if _level_price(lad, 0.809) else None,
        "exh1": round(float(lad.get("exh1")), 2),
        "exh2": round(float(lad.get("exh2")), 2),
        "t1": (round(float(lad["t1"]), 2) if lad.get("t1") is not None else None),
        "ma3_ok": bool(sig.get("ma3_ok")),
        "vol_ok": bool(sig.get("vol_ok")),
        "levels": levels,
        "candles_30m": candles_30m,
        "missing_1m": missing_1m,
    }


def build_review_view(start: Optional[str] = None, end: Optional[str] = None,
                      symbol: str = "", max_days: int = 30) -> dict:
    """构建多日狩猎区复盘视图（按交易日分 panel）。

    - start/end 皆空：默认最近 7 个自然日。
    - 每个交易日一 panel：左侧 30m K线，右侧 ladder 档位标签。
    """
    # 1) 区间解析
    if not start and not end:
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=6)
        end = end_dt.strftime("%Y-%m-%d")
        start = start_dt.strftime("%Y-%m-%d")
    elif start and not end:
        s_dt = datetime.fromtimestamp(_date_to_open_ms(start) / 1000, tz=UTC)
        e_dt = s_dt + timedelta(days=max_days - 1)
        end = e_dt.strftime("%Y-%m-%d")
    elif end and not start:
        e_dt = datetime.fromtimestamp(_date_to_open_ms(end) / 1000, tz=UTC)
        s_dt = e_dt - timedelta(days=max_days - 1)
        start = s_dt.strftime("%Y-%m-%d")

    start_open_ms = _date_to_open_ms(start)
    end_open_ms = _date_to_open_ms(end)
    if end_open_ms < start_open_ms:
        start_open_ms, end_open_ms = end_open_ms, start_open_ms
        start, end = end, start

    span_days = (end_open_ms - start_open_ms) // 86400000 + 1

    # 2) 取日线（复刻 hunting_system/daily_push 链路）；
    #    回看窗口按请求区间动态扩展（span + 60 天预热余量），
    #    否则长区间前段无日线 → 预热不足 → 全部"无信号"。
    try:
        bars_d1, source = hs_data.load_bars_primary(end, lookback_days=span_days + 60)
    except Exception as e:
        return {"ok": False, "reason": "日线取数失败：%s（不猜 S）" % e,
                "range": {"start": start, "end": end, "source": None,
                          "span_days": int(span_days)},
                "panels": [], "missing_days": []}
    if not bars_d1:
        return {"ok": False, "reason": "日线为空（不猜 S）",
                "range": {"start": start, "end": end, "source": source,
                          "span_days": int(span_days)},
                "panels": [], "missing_days": []}

    # 3) 蜡烛：fapi  永续（用户指定口径），整段一次性拉取后按日拆分
    try:
        all_30m = _fetch_30m_range_fapi(start_open_ms, end_open_ms + 86400000)
        fapi_failed = False
    except Exception:
        all_30m = {}
        fapi_failed = True

    # 4) 逐日生成 panel（严格只用 ≤ 该日收盘日线）
    panels = []
    dates_in_range = _iter_dates_range(start, end)
    date_set = set(dates_in_range)
    for d_str, o, h, l, c in bars_d1:
        if d_str not in date_set:
            continue
        bars_for_d = [(dt, oo, hh, ll, cc) for dt, oo, hh, ll, cc in bars_d1
                      if dt <= d_str]
        if len(bars_for_d) < 7:
            sig = None
        else:
            sig = hs_data.gen_signal(bars_for_d)
        candles_30m = all_30m.get(d_str, [])
        missing_1m = (len(candles_30m) == 0)
        panels.append(_build_panel(d_str, sig, candles_30m, missing_1m))

    # 4) missing_days：区间内 30m 完全缺失的日期
    present_dates = {p["date"] for p in panels if not p["missing_1m"]}
    missing_days = [d for d in dates_in_range if d not in present_dates]

    return {
        "ok": True,
        "reason": "",
        "range": {"start": start, "end": end, "source": source,
                  "span_days": int(span_days)},
        "candle_source": " 永续（%s）" % ("实时拉取" if not fapi_failed else "失败，已标记缺失"),
        "panels": panels,
        "missing_days": missing_days,
    }
