# rs_data.py
# 本地开发数据层：拉取 Binance 期货 K 线 + 缓存 + 北京时间 + HTF 重采样 + HTF 偏向
# 纯标准库，无第三方依赖，可直接 `python rs_data.py` 之外被 import。
import os, csv, json, time, urllib.request, datetime as dt

# ==================== 代理配置（默认直连，按需启用） ====================
# 本地 Windows 出网需代理时，设置环境变量 KLINE_PROXY / HTTP_PROXY / HTTPS_PROXY；
# 不设置或设为空串 = 直连（符合线上零代理纪律）。源码不再硬编码代理地址。
_proxy = os.environ.get("KLINE_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
if _proxy:
    os.environ["HTTP_PROXY"]  = _proxy
    os.environ["HTTPS_PROXY"] = _proxy

# 价格数据源端点（可经环境变量 BINANCE_FAPI_BASE 覆盖）
BINANCE_FAPI_BASE = os.environ.get("BINANCE_FAPI_BASE", "")  # 价格接口基址：请通过环境变量配置

BJ = dt.timezone(dt.timedelta(hours=8))  # 北京时间 UTC+8（无夏令时）


def beijing_str(ms):
    """毫秒时间戳 → 北京时间字符串（UTC+8），用于信号时间/入场/平仓全部显示。"""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")


def _http_get(url, retries=3, timeout=15):
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(0.4 * (a + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


_STEP = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}


def fetch_klines(symbol, interval, start_ms, end_ms):
    """分页拉取，每页最多 1000 根（Binance 上限），逐页推进 startTime。"""
    out = []
    cur = start_ms
    step = _STEP[interval]
    while cur < end_ms:
        url = (f"{BINANCE_FAPI_BASE}/fapi/v1/klines?symbol={symbol}"
               f"&interval={interval}&startTime={cur}&limit=1000")
        batch = _http_get(url)
        if not batch:
            break
        out.extend(batch)
        cur = batch[-1][0] + step * 60_000
        if len(batch) < 1000:
            break
        time.sleep(0.05)  # 礼貌限速，避免权重超限
    return out


def _save(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for k in rows:
            w.writerow([k[0], k[1], k[2], k[3], k[4], k[5]])


def load_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "open_time": int(r["open_time"]), "open": float(r["open"]),
                "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"]), "volume": float(r["volume"]),
            })
    return rows


def get_1m(symbol, start_dt, end_dt, cache_path):
    """拉取（并缓存到 CSV）1m K 线；区间已被缓存则直接复用，避免重复请求。"""
    s_ms = int(dt.datetime(*start_dt, tzinfo=dt.timezone.utc).timestamp() * 1000)
    e_ms = int(dt.datetime(*end_dt, tzinfo=dt.timezone.utc).timestamp() * 1000)
    if os.path.exists(cache_path):
        rows = load_csv(cache_path)
        if rows and rows[0]["open_time"] <= s_ms and rows[-1]["open_time"] >= e_ms - 60_000:
            return rows
    raw = fetch_klines(symbol, "1m", s_ms, e_ms)
    _save(cache_path, raw)
    return load_csv(cache_path)


def resample_htf(candles, tf_min):
    """因果重采样：1m → HTF（如 1h）。按周期分桶，每桶 [open, close)。"""
    bms = tf_min * 60_000
    htf = []
    cb = None
    c = None
    for k in candles:
        b = k["open_time"] // bms
        if b != cb:
            if c is not None:
                htf.append(c)
            cb = b
            c = {"open_time": b * bms, "open": k["open"], "high": k["high"],
                 "low": k["low"], "close": k["close"], "volume": k["volume"]}
        else:
            c["high"] = max(c["high"], k["high"])
            c["low"] = min(c["low"], k["low"])
            c["close"] = k["close"]
            c["volume"] += k["volume"]
    if c is not None:
        htf.append(c)
    return htf


def _ema(vals, p):
    if len(vals) < p:
        return vals[-1]
    k = 2 / (p + 1)
    e = sum(vals[:p]) / p
    for v in vals[p:]:
        e = v * k + e * (1 - k)
    return e


def _adx(htf, p=14):
    """Wilder ADX（基于 HTF 高低收），用于趋势环境判定。"""
    n = len(htf)
    if n < p + 1:
        return 0.0
    pdm = [0.0] * n
    mdm = [0.0] * n
    tr = [0.0] * n
    for j in range(1, n):
        h = htf[j]["high"]; l = htf[j]["low"]; pc = htf[j - 1]["close"]
        up = h - htf[j - 1]["high"]; dn = htf[j - 1]["low"] - l
        pdm[j] = max(up, 0) if up > dn else 0.0
        mdm[j] = max(dn, 0) if dn > up else 0.0
        tr[j] = max(h - l, abs(h - pc), abs(l - pc))

    def w(s):
        s0 = sum(s[1:p + 1]) / p
        for v in s[p + 1:]:
            s0 = (s0 * (p - 1) + v) / p
        return s0

    atr = w(tr); ap = w(pdm); am = w(mdm)
    pdi = ap / atr * 100 if atr else 0.0
    mdi = am / atr * 100 if atr else 0.0
    return abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) else 0.0


def htf_bias(htf, i, fast=20, slow=50, adx_p=14):
    """HTF 偏向（因果）：只使用第 i 根【已收盘】HTF 桶之前的数据（htf[:i]）。"""
    if i < slow:
        return 0, 0.0
    closes = [h["close"] for h in htf[:i]]
    ef = _ema(closes, fast)
    es = _ema(closes, slow)
    adx = _adx(htf[:i], adx_p)
    bias = 1 if ef > es else (-1 if ef < es else 0)
    return bias, adx
