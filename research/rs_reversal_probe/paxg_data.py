# paxg_data.py
# PAXGUSDT 现货数据层：从价格接口基址（现货，历史远长于期货）拉取 K 线。
# 独立模块，不改动 rs_data.py（v2/v3 的期货数据层保持原样）。
# 默认基周期 = 5m（LTF 本就 5m；15m/1h/4h 均可由 5m 整除重采样，无精度损失）。
import os, csv, json, time, urllib.request, datetime as dt

# 本地 Windows 出网需代理时，设置环境变量 KLINE_PROXY / HTTP_PROXY / HTTPS_PROXY；
# 不设置或设为空串 = 直连（符合线上零代理纪律）。源码不再硬编码代理地址。
_proxy = os.environ.get("KLINE_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
if _proxy:
    os.environ["HTTP_PROXY"]  = _proxy
    os.environ["HTTPS_PROXY"] = _proxy

# 价格数据源端点（可经环境变量 BINANCE_SPOT_BASE 覆盖）
BINANCE_SPOT_BASE = os.environ.get("BINANCE_SPOT_BASE", "")  # 价格接口基址：请通过环境变量配置

BJ = dt.timezone(dt.timedelta(hours=8))


def beijing_str(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")


def _http_get(url, retries=5, timeout=20):
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code = r.getcode()
                if code == 429 or code == 418:
                    time.sleep(2.0 * (a + 1))
                    last = RuntimeError(f"rate limited {code}")
                    continue
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 418):
                time.sleep(2.0 * (a + 1))
                last = e
                continue
            last = e
            time.sleep(0.4 * (a + 1))
        except Exception as e:
            last = e
            time.sleep(0.5 * (a + 1))
    raise RuntimeError(f"spot fetch failed {url}: {last}")


_STEP = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}


def fetch_klines_spot(symbol, interval, start_ms, end_ms):
    """分页拉取现货 K 线（价格接口基址），每页 1000 根，含 429 退避。"""
    out = []
    cur = start_ms
    step = _STEP[interval]
    pages = 0
    while cur < end_ms:
        url = (f"{BINANCE_SPOT_BASE}/api/v3/klines?symbol={symbol}"
               f"&interval={interval}&startTime={cur}&limit=1000")
        batch = _http_get(url)
        if not batch:
            break
        out.extend(batch)
        pages += 1
        cur = batch[-1][0] + step * 60_000
        if len(batch) < 1000:
            break
        if pages % 50 == 0:
            time.sleep(0.2)   # 礼貌限速（每 50 页）
        else:
            time.sleep(0.06)
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


# ==================== JSON 缓存（规范化缓存格式） ====================
def _json_path(csv_path):
    return os.path.splitext(csv_path)[0] + ".json"


def save_json(json_path, rows):
    payload = {"interval": "5m",
               "rows": [[r["open_time"], r["open"], r["high"], r["low"],
                         r["close"], r["volume"]] for r in rows]}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"[PAXG] JSON 缓存写入 {len(rows)} 根 5m → {json_path}")


def load_json(json_path):
    with open(json_path, encoding="utf-8") as f:
        d = json.load(f)
    return [{"open_time": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]} for r in d["rows"]]


def get_5m(symbol, start_dt, end_dt, cache_path):
    s_ms = int(dt.datetime(*start_dt, tzinfo=dt.timezone.utc).timestamp() * 1000)
    e_ms = int(dt.datetime(*end_dt, tzinfo=dt.timezone.utc).timestamp() * 1000)
    json_path = _json_path(cache_path)

    # ① 优先 JSON 缓存（规范化格式，跨会话复用）
    if os.path.exists(json_path):
        rows = load_json(json_path)
        if rows and rows[0]["open_time"] <= s_ms + 24 * 60 * 60_000 \
                and rows[-1]["open_time"] >= e_ms - 7 * 24 * 60 * 60_000:
            print(f"[PAXG] JSON 缓存命中复用（{len(rows)} 根 5m，"
                  f"{beijing_str(rows[0]['open_time'])} ~ {beijing_str(rows[-1]['open_time'])}）")
            return rows

    # ② 退而求其次：CSV 缓存（含 2020+ 全量），切片到请求窗口后转 JSON 落盘
    if os.path.exists(cache_path):
        rows = load_csv(cache_path)
        if rows and rows[0]["open_time"] <= s_ms + 24 * 60 * 60_000 \
                and rows[-1]["open_time"] >= e_ms - 7 * 24 * 60 * 60_000:
            # 切到窗口起点（2024+）：更早数据不进入回测，避免引入无关历史
            rows = [r for r in rows if r["open_time"] >= s_ms]
            save_json(json_path, rows)
            return rows

    # ③ 都没有才下载（仅首跑，且绝不在回测逻辑内触网）
    raw = fetch_klines_spot(symbol, "5m", s_ms, e_ms)
    save_json(json_path, raw)
    print(f"[PAXG] 拉取并缓存 {len(raw)} 根 5m → {json_path}")
    return [{"open_time": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]} for r in raw]



def earliest_available(symbol="PAXGUSDT"):
    """探测现货对最早可用 1m 起点（用于确认数据天花板）。"""
    url = f"{BINANCE_SPOT_BASE}/api/v3/klines?symbol={symbol}&interval=1m&startTime=0&limit=1"
    b = _http_get(url)
    return b[0][0] if b else None
