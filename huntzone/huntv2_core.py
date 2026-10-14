# -*- coding: utf-8 -*-
"""狩猎区 v2 编排层（纯 python，零网络依赖、零代理污染）。

职责：
  - fetch_daily_1d()：优先走 Twelve Data XAU/USD spot D1（与 hunting_system 官方卡同源），
    失败时回退 Binance fapi  1d。**绝不 import hunting_zone/data.py**（其顶部污染全局代理 env）。
  - compute_ladder()：取数 → 顺势方向 → 冻结回归 S → build() 正解几何 → 结构化结果。
  - build_response()：按现价（可选）组装 API 返回体，含 10 档位 + 距离(bp) + 警示。

红线（沿用 /wuyuan）：取数失败返回 (None, 原因)，调用方必须 502 明确报错，**绝不猜 S**。
口径：优先 Twelve Data 现货（与官方卡一致），回退 fapi  期货（存在基差，仅作 fallback）。
"""
import time
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlencode

from huntzone.hz_engine import (Config, build, trend_series, trend_direction,
                       trend_confirm, vol_spike_filter)
from huntzone.hz_signal import S_MODEL_FROZEN, predict_S
from config import TWELVE_KEY as _TWELVE_KEY, TWELVE_API as _TWELVE_API, FAPI_KLINES


# 档位角色（按 ratio 标注，用于结果表与图表配色）
_ROLE = {
    0.0: "腿端 / 中枢（失效线）",
    0.191: "止损",
    0.382: "狩猎区下沿",
    0.500: "区中挂单",
    0.618: "狩猎区上沿",
    0.809: "扩展位",
    1.000: "开盘价（锚）",
    1.618: "衰竭①",
    2.618: "衰竭②",
    4.236: "极限位",
}

# Twelve Data 配置：与 hunting_system/daily_push.py 官方卡同源（密钥 / 端点来自 config）
_TWELVE_SYMBOL = "XAU/USD"
_TWELVE_TZ = "America/New_York"
_TWELVE_LOOKBACK_DAYS = 130


def _requests_get(url, proxies=None, timeout=15):
    """兼容旧版 requests：trust_env 是 Session 属性，不能作 get() 关键字参数。"""
    import requests
    session = requests.Session()
    session.trust_env = False
    return session.get(url, proxies=proxies, timeout=timeout)


def _fapi_fetch(url):
    """自包含取数：复用项目内 PROXIES + requests（与 main._fapi_fetch 等价，避免 import main 成环）。"""
    from data import data_sync
    resp = _requests_get(url, proxies=data_sync.PROXIES, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _date_to_ms(d: str) -> int:
    """UTC 自然日 'YYYY-MM-DD' 的开盘毫秒（仅用于排序/过滤标签）。"""
    y, m, day = map(int, d.split("-"))
    return int(datetime(y, m, day, tzinfo=timezone.utc).timestamp() * 1000)


def _fetch_twelve_daily():
    """拉取 Twelve Data XAU/USD spot D1，返回 Binance-like rows [[ts,o,h,l,c,v,close_time], ...] 升序。

    与 hunting_system/daily_push.fetch_d1 同源：symbol=XAU/USD、timezone=America/New_York、
    剔除周末伪 bar。失败直接抛异常，由 fetch_daily_1d 回退 fapi。
    """
    from data import data_sync
    end = date.today()
    start = end - timedelta(days=_TWELVE_LOOKBACK_DAYS)
    params = {
        "symbol": _TWELVE_SYMBOL,
        "interval": "1day",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": _TWELVE_TZ,
        "apikey": _TWELVE_KEY,
        "format": "JSON",
    }
    url = _TWELVE_API + "?" + urlencode(params)
    resp = _requests_get(url, proxies=data_sync.PROXIES, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "error":
        raise RuntimeError("Twelve Data: %s" % data.get("message"))
    values = data.get("values") or []
    if not values:
        raise RuntimeError("Twelve Data 返回空 values")
    rows = []
    for v in values:
        dt = (v.get("datetime") or "").strip().split(" ")[0]
        if not dt:
            continue
        try:
            wd = date.fromisoformat(dt).weekday()
            o = float(v["open"]); h = float(v["high"])
            l = float(v["low"]); c = float(v["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if wd in (5, 6):           # 剔除周末伪 bar
            continue
        ts = _date_to_ms(dt)
        rows.append([ts, o, h, l, c, 0, ts + 86399999])
    rows.sort(key=lambda r: r[0])
    if not rows:
        raise RuntimeError("Twelve Data 无有效交易日")
    return rows


def fetch_daily_1d(symbol="", limit=60):
    """取 1d 日线原始 K线。优先 Twelve Data XAU/USD spot，失败回退 fapi 。

    返回 (rows, err, source)；rows 元素 = [ts, o, h, l, c, v, close_time, ...]（Binance 原始格式）。
    source = 'twelvedata' | 'fapi' | None（失败）。
    """
    try:
        rows = _fetch_twelve_daily()
        if not rows:
            raise RuntimeError("Twelve Data 返回空")
        return rows, None, "twelvedata"
    except Exception as e1:
        try:
            url = (FAPI_KLINES + "?symbol=%s"
                   "&interval=1d&limit=%d" % (symbol.upper(), limit))
            rows = _fapi_fetch(url)
            if not rows:
                return None, "fapi 返回空数组（日线不可得）", None
            return rows, None, "fapi"
        except Exception as e2:
            return None, "twelvedata: %s; fapi: %s" % (e1, e2), None


def compute_ladder(rows, source="fapi"):
    """由 1d 原始 K线生成今日狩猎区卡。返回结构化 dict。

    成功：{"ok": True, "ladder": build_dict, "source": ...}
    失败（无信号/数据不足）：{"ok": False, "reason": ...}
    """
    now_ms = int(time.time() * 1000)
    closed = [r for r in rows if int(r[6]) < now_ms]
    opened = [r for r in rows if int(r[6]) >= now_ms]
    if len(closed) < 7:
        return {"ok": False,
                "reason": "日线数据不足（需 ≥7 根已收盘），无法生成"}

    # bars = (date, o, h, l, c)，含今日（进行中）那根作为最后元素
    today = opened[-1] if opened else rows[-1]
    bars = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
            for r in closed]
    bars.append((int(today[0]), float(today[1]), float(today[2]),
                 float(today[3]), float(today[4])))
    bars = sorted(bars, key=lambda b: b[0])

    prev_bar = bars[-2]
    prev_history = bars[:-1]

    cfg = Config()
    ma = trend_series(prev_history, cfg.trend_period, cfg.trend_mode)
    prev_close = prev_bar[4]
    d = trend_direction(prev_close, ma[-1])
    if d == 0:
        return {"ok": False,
                "reason": "顺势方向未定（昨收 == 均线，临界），今日无信号"}
    if cfg.trend_filter == "ma3" and not trend_confirm(prev_history, d):
        return {"ok": False,
                "reason": "趋势过滤（ma3）：SMA5/20/40 未同向对齐 → 今日空仓"}
    if cfg.vol_filter and vol_spike_filter(prev_history, cfg.vol_filter, cfg.vol_look):
        return {"ok": False,
                "reason": "波动过滤：前一日振幅异常放大 → 今日空仓"}

    direction = "short" if d == -1 else "long"
    S, body1, pos1 = predict_S(S_MODEL_FROZEN, prev_bar)
    lad = build(today[1], S, direction, prev_close=prev_close)
    lad["mae"] = S_MODEL_FROZEN["loo_mae"]
    lad["body1"] = round(body1, 2)
    lad["pos1"] = round(pos1, 3)
    src_label = "%s XAU/USD 1d（已收盘）" % (source or "unknown")
    return {"ok": True, "ladder": lad, "source": src_label}


def _round_ratio(r):
    return round(float(r) * 1000) / 1000


def build_response(comp, live_info=None):
    """组装 API 返回体。comp = compute_ladder 的成功结果；live_info = _wuyuan_live 返回或 None。"""
    lad = comp["ladder"]

    # 基准：优先现价，否则狩猎区中值
    if live_info and live_info.get("px") is not None:
        base = float(live_info["px"])
        base_kind = "live"
    else:
        base = float(lad["zone_mid"])
        base_kind = "zone"

    levels = []
    for lv in lad["levels"]:
        price = float(lv["price"])
        r = _round_ratio(lv["ratio"])
        dist_pt = price - base
        dist_bp = (dist_pt / base * 10000.0) if base else None
        levels.append({
            "ratio": lv["ratio"],
            "name": lv["name"],
            "price": price,
            "role": _ROLE.get(r, "—"),
            "dist_pt": round(dist_pt, 2),
            "dist_bp": (round(dist_bp, 1) if dist_bp is not None else None),
        })

    t1 = lad.get("t1")
    if t1 is not None:
        t1 = float(t1)
        dpt = t1 - base
        levels.append({
            "ratio": None, "name": "目标①（昨收）", "price": t1,
            "role": "第一目标位 · 到价减仓 + 止损移保本",
            "dist_pt": round(dpt, 2),
            "dist_bp": (round(dpt / base * 10000.0, 1) if base else None),
        })

    res = {
        "code": 200,
        "ok": True,
        "mode": "self_sufficient",
        "engine": "huntv2 (build 正解几何 + S_MODEL_FROZEN 冻结回归)",
        "direction_cn": lad["direction_cn"],
        "direction": lad["direction"],
        "open_px": round(float(lad["open_px"]), 2),
        "S": round(float(lad["S"]), 2),
        "S_mae": round(float(lad["mae"]), 2),
        "R": round(float(lad["R"]), 2),
        "zone_lo": round(float(lad["zone_lo"]), 2),
        "zone_hi": round(float(lad["zone_hi"]), 2),
        "zone_mid": round(float(lad["zone_mid"]), 2),
        "zone_width": round(float(lad["zone_width"]), 2),
        "stop": round(float(lad["stop"]), 2),
        "leg_start": round(float(lad["leg_start"]), 2),
        "exh1": round(float(lad["exh1"]), 2),
        "exh2": round(float(lad["exh2"]), 2),
        "t1": (round(t1, 2) if t1 is not None else None),
        "prev_close": (round(float(lad["prev_close"]), 2)
                       if lad["prev_close"] is not None else None),
        "special_gap": bool(lad["special_gap"]),
        "body1": lad["body1"],
        "pos1": lad["pos1"],
        "base": round(base, 2),
        "base_kind": base_kind,
        "levels": levels,
        "source": comp.get("source", ""),
        "live": live_info,
        "warnings": [],
        "note": ("档位几何可信；S 为冻结回归预测（±%.1f 点 LOO MAE），低置信度，按区间使用。"
                 % float(lad["mae"])),
        "disclaimer": ("现价为 fapi  期货参考价，与官方现货口径存在基差"
                       "（实测 −98 ~ +24 点），仅用于显示距离，不参与档位计算。"),
    }
    return res
