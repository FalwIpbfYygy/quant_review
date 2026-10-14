# -*- coding: utf-8 -*-
"""白银 XAGUSD 狩猎区复盘 · 编排层（纯新增，复刻 /huntzone-review 原逻辑）。

与 huntzone_review_core 的唯一差异：
  1) 数据源换成 huntzone_review_xag_data（Binance fapi XAGUSDT 日线 + 30m）；
  2) 复用 huntzone_review_hs_data.gen_signal —— 即 /huntzone-review 的**原逻辑**
     （SMA10 顺势 + S_MODEL_FROZEN 冻结回归 S + hz_engine.build 档位）；
  3) 额外支持 manual_S：用户可传入白银自适应 S 覆盖冻结模型（白银单价 ~$40，
     冻结模型 S 区间 36~117 美元点会与白银数量级错配，故提供覆盖入口）；
  4) 返回体附带 suggested_S（白银自适应建议值，供前端一键应用）。

红线：严格零未来函数；取数失败 → ok=False，绝不猜 S。
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

from huntzone.huntzone_review_hs_data import gen_signal
from huntzone.huntzone_review_xag_data import (fetch_d1, fetch_30m_range, suggested_S,
                                      _date_to_open_ms, _valid_symbol)
from huntzone.hz_engine import build
from huntzone.huntback_sim import _date_to_open_ms as _d2o


UTC = timezone.utc
SOURCE = "binance_fapi"


def _iter_dates_range(start: str, end: str) -> List[str]:
    """[start, end] 闭区间所有自然日，升序（UTC 日界）。"""
    s = _d2o(start)
    e = _d2o(end)
    if e < s:
        s, e = e, s
    out = []
    cur = datetime.fromtimestamp(s / 1000, tz=UTC)
    end_dt = datetime.fromtimestamp(e / 1000, tz=UTC)
    while cur <= end_dt:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _build_panel(date: str, sig: Optional[dict], candles_30m: List[List[float]],
                 missing_30m: bool) -> dict:
    """把 gen_signal 结果 + 30m K线 组装成前端需要的 panel（与 XAU 版一致）。"""
    lad = sig.get("lad") if sig else None
    if lad is None:
        return {
            "date": date, "has_signal": False,
            "direction": None, "direction_cn": "无信号",
            "open_px": None, "S": None, "S_mae": None,
            "zone_lo": None, "zone_hi": None, "zone_mid": None,
            "stop": None, "警戒": None, "exh1": None, "exh2": None, "t1": None,
            "ma3_ok": None, "vol_ok": None,
            "levels": [], "candles_30m": candles_30m, "missing_30m": missing_30m,
        }

    direction = lad.get("direction")
    levels = [{"ratio": lv["ratio"], "name": lv["name"], "price": round(float(lv["price"]), 2)}
              for lv in lad.get("levels", [])]

    def _lv(ratio):
        for lv in lad.get("levels", []):
            if abs(round(lv["ratio"], 3) - round(ratio, 3)) < 1e-9:
                return float(lv["price"])
        return None

    return {
        "date": date, "has_signal": True,
        "direction": direction,
        "direction_cn": lad.get("direction_cn", "做空" if direction == "short" else "做多"),
        "source": SOURCE,
        "open_px": round(float(lad.get("open_px")), 2),
        "S": round(float(lad.get("S")), 2),
        "S_mae": round(float(sig.get("S_mae")), 2),
        "zone_lo": round(float(lad.get("zone_lo")), 2),
        "zone_hi": round(float(lad.get("zone_hi")), 2),
        "zone_mid": round(float(lad.get("zone_mid")), 2),
        "stop": round(float(lad.get("stop")), 2),
        "警戒": round(float(_lv(0.809)), 2) if _lv(0.809) is not None else None,
        "exh1": round(float(lad.get("exh1")), 2),
        "exh2": round(float(lad.get("exh2")), 2),
        "t1": (round(float(lad["t1"]), 2) if lad.get("t1") is not None else None),
        "ma3_ok": bool(sig.get("ma3_ok")),
        "vol_ok": bool(sig.get("vol_ok")),
        "levels": levels,
        "candles_30m": candles_30m,
        "missing_30m": missing_30m,
    }


def build_review_view(start: Optional[str] = None, end: Optional[str] = None,
                      symbol: str = "XAGUSDT", manual_S: Optional[float] = None,
                      max_days: int = 30, mode: str = "adaptive") -> dict:
    """构建白银多日狩猎区复盘视图（按交易日分 panel）。

    - start/end 皆空：默认最近 7 个自然日。
    - S 取值优先级：manual_S（手动） > mode=='adaptive'（自适应，逐日因果）
      > mode=='frozen'（原逻辑黄金冻结模型，仅 XAG/黄金语境适用）。
    - 红线：adaptive S 只用 <= 当日 的日线计算，零未来函数。
    - symbol 支持 XAGUSDT / ETHUSDT / BTCUSDT（白名单校验，非法直接报错不回退）。
    """
    # 0) symbol 校验（不在白名单 → 明确报错，绝不猜、绝不回退 XAG）
    try:
        symbol = _valid_symbol(symbol)
    except ValueError as e:
        return {"ok": False, "reason": str(e),
                "range": {"start": start or "", "end": end or "", "source": SOURCE},
                "panels": [], "missing_days": [], "suggested_S": None}

    # 1) 区间解析（与 XAU 版一致）
    if not start and not end:
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=6)
        end = end_dt.strftime("%Y-%m-%d")
        start = start_dt.strftime("%Y-%m-%d")
    elif start and not end:
        s_dt = datetime.fromtimestamp(_d2o(start) / 1000, tz=UTC)
        e_dt = s_dt + timedelta(days=max_days - 1)
        end = e_dt.strftime("%Y-%m-%d")
    elif end and not start:
        e_dt = datetime.fromtimestamp(_d2o(end) / 1000, tz=UTC)
        s_dt = e_dt - timedelta(days=max_days - 1)
        start = s_dt.strftime("%Y-%m-%d")

    start_open_ms = _d2o(start)
    end_open_ms = _d2o(end)
    if end_open_ms < start_open_ms:
        start_open_ms, end_open_ms = end_open_ms, start_open_ms
        start, end = end, start

    span_days = (end_open_ms - start_open_ms) // 86400000 + 1

    # 2) 取日线（Binance fapi 指定币种 1d）
    try:
        bars_d1 = fetch_d1(end, symbol=symbol)
    except Exception as e:
        return {"ok": False, "reason": "日线取数失败：%s（不猜 S）" % e,
                "range": {"start": start, "end": end, "source": SOURCE,
                          "span_days": int(span_days)},
                "panels": [], "missing_days": [], "suggested_S": None}
    if not bars_d1:
        return {"ok": False, "reason": "日线为空（不猜 S）",
                "range": {"start": start, "end": end, "source": SOURCE,
                          "span_days": int(span_days)},
                "panels": [], "missing_days": [], "suggested_S": None}

    sug_S = suggested_S(bars_d1)

    # 3) 30m 整段（单请求，按 UTC 日拆分）
    try:
        bars_30m_all = fetch_30m_range(start_open_ms, end_open_ms + 86400000, symbol=symbol)
    except Exception as e:
        return {"ok": False, "reason": "30m 取数失败：%s（不猜 S）" % e,
                "range": {"start": start, "end": end, "source": SOURCE,
                          "span_days": int(span_days)},
                "panels": [], "missing_days": [], "suggested_S": sug_S}
    by_day: Dict[str, List[List[float]]] = {}
    for ts, o, h, l, c in bars_30m_all:
        d = datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d")
        by_day.setdefault(d, []).append([ts, o, h, l, c])

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
            sig = gen_signal(bars_for_d)
            # 有效 S 优先级：手动 > 白银自适应(逐日因果，仅用 <= 当日 日线) > 原逻辑冻结
            eff_S = None
            if manual_S is not None:
                eff_S = float(manual_S)
            elif mode == "adaptive":
                eff_S = suggested_S(bars_for_d)   # 零未来函数：只用当日及以前的日线
            # 覆盖重建 lad（沿用 open_px / direction / prev_close 原逻辑）
            if sig and sig.get("lad") is not None and eff_S is not None:
                try:
                    lad = build(sig["open"], eff_S, sig["direction"],
                                prev_close=sig.get("prev_close"))
                    sig = dict(sig)
                    sig["S"] = float(eff_S)
                    sig["lad"] = lad
                except Exception:
                    pass  # 覆盖失败时退回原逻辑冻结模型
        candles_30m = by_day.get(d_str, [])
        panels.append(_build_panel(d_str, sig, candles_30m, missing_30m=(len(candles_30m) == 0)))

    # 5) missing_days：区间内 30m 完全缺失的日期
    present_dates = {p["date"] for p in panels if not p["missing_30m"]}
    missing_days = [d for d in dates_in_range if d not in present_dates]

    return {
        "ok": True, "reason": "",
        "range": {"start": start, "end": end, "source": SOURCE,
                  "span_days": int(span_days)},
        "symbol": symbol,
        "mode": ("manual" if manual_S is not None else mode),
        "panels": panels,
        "missing_days": missing_days,
        "suggested_S": sug_S,
    }
