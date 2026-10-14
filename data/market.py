# -*- coding: utf-8 -*-
"""
 市场环境看板后端（新增模块，不改动现有 backtest.py / main.py 运行逻辑）

职责：
- 本地 JSON 缓存（market_cache/）+ 后台定时刷新线程：
  * overview     : Binance  1h/1d → 现价/涨跌/振幅/ATR/枢轴/时段，每 30s
  * trend        : Binance  1h/4h/1d/1w → 多周期趋势评分，每 60s
  * correlations : Binance  + Yahoo(DXY/US10Y/VIX/SPX/OIL) → 关联雷达，每 300s
- 复用 data_sync.PROXIES 与现有请求模式（与 binance_src 一致）。
- 外部抓取失败时自动回退本地缓存，frontend 显示 stale 标记。
"""
import os
import json
import time
import math
import threading
from datetime import datetime, timedelta
import requests
from data.data_sync import PROXIES, MAX_RETRIES, RETRY_DELAY


# ===================== 配置 =====================
from config import FAPI_KLINES as BINANCE_FAPI  # 价格接口基址（由 .env 的 BINANCE_FAPI_BASE 配置）
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=60d"

# 关联市场：name -> (yahoo_symbol, label, relation_note)
# 注意：Yahoo `^TNX` 显示值 = 真实收益率 ×10（如 4.3% 显示 43.0），代码内已 /10。
YAHOO_SYMBOLS = {
    "DXY":   ("DX-Y.NYB", "美元指数", "负相关"),
    "US10Y": ("^TNX",     "美债10Y收益率", "负相关(实际利率)"),
    "VIX":   ("^VIX",     "恐慌指数", "正相关(避险)"),
    "SPX":   ("^GSPC",    "标普500", "偏弱负相关(风险偏好)"),
    "OIL":   ("CL=F",     "WTI原油", "正相关(通胀)"),
}

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

TTL = {"overview": 30, "trend": 60, "correlations": 300}

_cache = {k: {"ts": 0, "data": None, "err": None} for k in TTL}
_cache_lock = threading.Lock()


# ===================== 抓取 =====================
def _get(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, proxies=PROXIES, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    return None


def _fetch_binance(symbol, interval, limit):
    url = f"{BINANCE_FAPI}?symbol={symbol}&interval={interval}&limit={limit}"
    return _get(url)


def _fetch_yahoo(symbol):
    return _get(YAHOO_CHART.format(sym=symbol))


# ===================== 技术指标 =====================
def _ema(vals, n):
    if not vals:
        return []
    k = 2.0 / (n + 1)
    ema = vals[0]
    out = [ema]
    for v in vals[1:]:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _atr(klines, n=14):
    trs = []
    for i in range(1, len(klines)):
        h = float(klines[i][2]); l = float(klines[i][3]); pc = float(klines[i-1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    if len(trs) < n:
        return sum(trs) / len(trs)
    atr = sum(trs[:n]) / n
    for v in trs[n:]:
        atr = (atr * (n - 1) + v) / n
    return atr


def _rsi(closes, n=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    if len(gains) < n:
        return 50.0
    ag = sum(gains[:n]) / n; al = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _macd(closes):
    e12 = _ema(closes, 12); e26 = _ema(closes, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    sig = _ema(macd, 9)
    hist = [m - s for m, s in zip(macd, sig)]
    return macd[-1], sig[-1], hist[-1]


def _pivot(h, l, c):
    p = (h + l + c) / 3.0
    return {
        "p": round(p, 2),
        "r1": round(2 * p - l, 2), "r2": round(p + (h - l), 2), "r3": round(h + 2 * (p - l), 2),
        "s1": round(2 * p - h, 2), "s2": round(p - (h - l), 2), "s3": round(l - 2 * (h - p), 2),
    }


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 2:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a)); db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def _session_now():
    bj = datetime.utcnow() + timedelta(hours=8)
    h = bj.hour + bj.minute / 60.0
    if 7 <= h < 15:
        return "亚盘"
    if 15 <= h < 21:
        return "欧盘"
    if h >= 21 or h < 3:
        return "美盘"
    return "低流动性"


def _trend_score(closes):
    """返回 0-100 趋势强度分 + 明细。50=中性, 100=强多, 0=强空。"""
    if len(closes) < 60:
        return 50, {"note": "数据不足"}
    e20 = _ema(closes, 20)[-1]; e50 = _ema(closes, 50)[-1]
    price = closes[-1]
    rsi = _rsi(closes)
    macd, signal, hist = _macd(closes)
    bull = 0
    if price > e20 > e50:
        bull = 1
    elif price < e20 < e50:
        bull = -1
    score = 50
    score += 20 if bull == 1 else (-20 if bull == -1 else 0)
    score += -5 if e50 > e20 else 0
    score += 10 if (macd > 0 and hist > 0) else (-10 if (macd < 0 and hist < 0) else 0)
    score += 5 if rsi > 70 else (-5 if rsi < 30 else 0)
    score = max(0, min(100, score))
    return score, {
        "price": round(price, 2), "ema20": round(e20, 2), "ema50": round(e50, 2),
        "rsi": round(rsi, 1), "macd": round(macd, 2), "hist": round(hist, 2),
        "dir": "多" if bull == 1 else ("空" if bull == -1 else "震荡"),
    }


# ===================== 计算 =====================
def _calc_overview():
    k1h = _fetch_binance("", "1h", 25)
    k1d = _fetch_binance("", "1d", 30)
    if not k1h or not k1d:
        return None
    last = k1h[-1]
    cur = float(last[4])
    day_ago = float(k1h[0][1])
    change = cur - day_ago
    change_pct = change / day_ago * 100 if day_ago else 0
    atr = _atr(k1h[-15:], 14)
    highs = [float(x[2]) for x in k1h]
    lows = [float(x[3]) for x in k1h]
    rng = max(highs) - min(lows)
    pd = k1d[-2]
    pivot = _pivot(float(pd[2]), float(pd[3]), float(pd[4]))
    return {
        "price": round(cur, 2),
        "day_change": round(change, 2),
        "day_change_pct": round(change_pct, 2),
        "atr": round(atr, 2),
        "range": round(rng, 2),
        "session": _session_now(),
        "pivot": pivot,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _calc_trend():
    out = {}
    for tf, lim in (("1h", 200), ("4h", 200), ("1d", 200), ("1w", 200)):
        k = _fetch_binance("", tf, lim)
        if not k:
            continue
        closes = [float(x[4]) for x in k]
        score, detail = _trend_score(closes)
        out[tf] = {"score": score, "detail": detail}
    if not out:
        return None
    scores = [v["score"] for v in out.values()]
    out["_composite"] = round(sum(scores) / len(scores), 1)
    return out


def _calc_correlations():
    xau = _fetch_binance("", "1d", 65)
    if not xau:
        return None
    xau_closes = [float(x[4]) for x in xau]
    items = []
    for key, (sym, label, rel) in YAHOO_SYMBOLS.items():
        y = _fetch_yahoo(sym)
        if not y:
            continue
        try:
            res = y["chart"]["result"][0]
            meta = res["meta"]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None][-60:]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or (closes[-2] if len(closes) > 1 else price)
            if price is None or prev is None:
                continue
            # 涨跌幅用原始值计算（避免下方 /10 显示转换污染）
            chg = (price - prev) / prev * 100 if prev else None
            # Yahoo ^TNX 显示值 = 收益率×10；仅在明显 >10 时除 10（收益率不会 >10%）
            display_price = price / 10.0 if (key == "US10Y" and price > 10) else price
            c20 = _pearson(xau_closes[-20:], closes[-20:]) if len(closes) >= 20 else None
            c60 = _pearson(xau_closes[-60:], closes[-60:]) if len(closes) >= 60 else None
            items.append({
                "key": key, "label": label, "relation": rel,
                "price": round(display_price, 2) if key != "SPX" else round(display_price, 0),
                "change_pct": round(chg, 2) if chg is not None else None,
                "corr20": round(c20, 2) if c20 is not None else None,
                "corr60": round(c60, 2) if c60 is not None else None,
            })
        except Exception:
            continue
    if not items:
        return None
    return items


# ===================== 本地 JSON 缓存 =====================
def _save(key, data):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()), "data": data}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _load(key):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


_CALC = {"overview": _calc_overview, "trend": _calc_trend, "correlations": _calc_correlations}


def _refresh_loop():
    while True:
        for key in TTL:
            try:
                data = _CALC[key]()
                with _cache_lock:
                    if data is not None:
                        _cache[key]["ts"] = int(time.time())
                        _cache[key]["data"] = data
                        _cache[key]["err"] = None
                        _save(key, data)
                    else:
                        _cache[key]["err"] = "external fetch failed"
            except Exception as e:
                with _cache_lock:
                    _cache[key]["err"] = str(e)[:120]
            time.sleep(TTL[key])
        time.sleep(1)


def _init():
    for key in TTL:
        c = _load(key)
        if c:
            with _cache_lock:
                _cache[key]["ts"] = c.get("ts", 0)
                _cache[key]["data"] = c.get("data")
    threading.Thread(target=_refresh_loop, daemon=True).start()


# ===================== 对外 API =====================
def get_overview():
    with _cache_lock:
        c = dict(_cache["overview"])
    return {"code": 200 if c["data"] else 503, "stale": c["err"] is not None,
            "ts": c["ts"], "data": c["data"], "err": c["err"]}


def get_trend():
    with _cache_lock:
        c = dict(_cache["trend"])
    return {"code": 200 if c["data"] else 503, "stale": c["err"] is not None,
            "ts": c["ts"], "data": c["data"], "err": c["err"]}


def get_correlations():
    with _cache_lock:
        c = dict(_cache["correlations"])
    return {"code": 200 if c["data"] else 503, "stale": c["err"] is not None,
            "ts": c["ts"], "data": c["data"], "err": c["err"]}


_init()
