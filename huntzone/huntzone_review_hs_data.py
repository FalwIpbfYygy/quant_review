# -*- coding: utf-8 -*-
"""狩猎区复盘数据源：完整复刻 hunting_system/daily_push.py 的取数 + 信号链路。

复制原则（方案 B）：把 hunting_system 核心函数/常量搬进 quant_review，
不 import 外部 hunting_system 路径，也不触发 hunting_system/hunting_zone/data.py
顶部对全局代理环境变量的污染。

口径与 daily_push.py 完全一致：
  - 日线优先 Twelve Data XAU/USD spot D1（America/New_York 日界，剔除周末伪 bar）
  - 在线失败回退本地现货 CSV：_spot_data/_spot_d1_*.csv
  - 信号 = gen_signal(bars)：SMA10 顺势符号 + S_MODEL_FROZEN 冻结回归 + build()
  - 默认 Config(trend_filter='ma3', vol_filter=1.5)，与 production 一致
    （与 quant_review 内 gallery 的 ADR-4 关 ma3/vol 不同，这里必须对齐官方卡）。
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import datetime
import csv

from huntzone.hz_engine import (build, trend_series, trend_direction, Config,
                       trend_confirm, vol_spike_filter)
from huntzone.hz_signal import S_MODEL_FROZEN, predict_S
from config import PROXIES as _PROXIES, FEISHU_WEBHOOK, TWELVE_API, TWELVE_KEY


# --------------------------------------------------------------------------
# 代理：统一走 config.PROXIES（默认直连；本地 Windows 出网在 .env 设
# KLINE_PROXY / HTTP_PROXY / HTTPS_PROXY 即可）。源码不再保留任何代理地址。
# --------------------------------------------------------------------------
def _http_open(req, timeout=30):
    """带代理的 urlopen；代理来自 config.PROXIES，未配置则直连。"""
    if _PROXIES:
        handler = urllib.request.ProxyHandler({"http": _PROXIES["http"], "https": _PROXIES["https"]})
        return urllib.request.build_opener(handler).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


# --------------------------------------------------------------------------
# 路径与 Twelve Data 配置（与 hunting_system/daily_push.py 一致）
# --------------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))

# FEISHU_WEBHOOK / TWELVE_API / TWELVE_KEY 已从 config 导入（见顶部），此处不再硬编码。
SYMBOL = "XAU/USD"
TIMEZONE = "America/New_York"
LOOKBACK_DAYS = 130          # 自然日回看跨度，覆盖 SMA40 预热

# 本地现货 CSV 回退路径（与 hunting_system 同级目录一致）
SPOT_D1_CSV = os.path.join(
    os.path.expanduser("~"), "Downloads",
    "_spot_data", "_spot_d1_20251201_20260924.csv")


def _load_spot_csv(path):
    """读取本地现货 D1 CSV → [(date, open, high, low, close)]，剔除周末伪 bar。"""
    bars = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or len(row) < 5:
                continue
            dt = row[0].strip()
            try:
                wd = datetime.datetime.strptime(dt, "%Y-%m-%d").weekday()
            except ValueError:
                wd = -1
            if wd in (5, 6):
                continue
            try:
                o, h, l, c = (float(x) for x in row[1:5])
            except ValueError:
                continue
            bars.append((dt, o, h, l, c))
    bars.sort(key=lambda b: b[0])
    return bars


def fetch_d1(end_date, lookback_days=None):
    """拉取 1day 现货 D1，剔除周末伪 bar，返回 [(date,o,h,l,c)] 按日期升序。

    直接复刻 hunting_system/daily_push.fetch_d1。
    lookback_days：自然日回看跨度，默认 LOOKBACK_DAYS=130（官方卡口径）；
    复盘页长区间时由调用方传入更大值（span + 预热余量），保底不小于 130。
    """
    lookback = LOOKBACK_DAYS if lookback_days is None else max(int(lookback_days), LOOKBACK_DAYS)
    start = (datetime.date.fromisoformat(end_date)
             - datetime.timedelta(days=lookback)).isoformat()
    params = {
        "symbol": SYMBOL, "interval": "1day",
        "start_date": start, "end_date": end_date,
        "timezone": TIMEZONE, "apikey": TWELVE_KEY, "format": "JSON",
    }
    url = TWELVE_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "-daily/1.0"})
    with _http_open(req) as r:
        data = json.load(r)
    if data.get("status") == "error":
        raise RuntimeError("Twelve Data: %s" % data.get("message"))
    values = data.get("values") or []
    if not values:
        raise RuntimeError("Twelve Data 返回空 values")
    bars = []
    for v in values:
        dt = (v.get("datetime") or "").strip()
        try:
            o = float(v["open"]); h = float(v["high"])
            l = float(v["low"]); c = float(v["close"])
        except (TypeError, ValueError):
            continue
        d = dt.split(" ")[0]
        try:
            wd = datetime.date.fromisoformat(d).weekday()
        except ValueError:
            continue
        if wd in (5, 6):
            continue
        bars.append((d, o, h, l, c))
    bars.sort(key=lambda b: b[0])
    if not bars:
        raise RuntimeError("拉取后无有效交易日数据")
    return bars


def load_bars_primary(end_date, lookback_days=None):
    """优先在线拉取 Twelve Data D1；失败回退本地现货 CSV。返回 (bars, source)。"""
    try:
        return fetch_d1(end_date, lookback_days), "twelvedata"
    except Exception as e:
        if os.path.exists(SPOT_D1_CSV):
            return _load_spot_csv(SPOT_D1_CSV), "local_csv"
        raise RuntimeError("在线拉取失败（%s）且本地 CSV 不存在（%s）" % (e, SPOT_D1_CSV))


def gen_signal(bars):
    """复刻 hunting_system/daily_push.gen_signal：生成当日狩猎区卡。

    默认 Config()：trend_period=10, trend_mode='sma', trend_filter='ma3', vol_filter=1.5。
    与 production 官方卡口径一致。
    """
    cfg = Config()
    prev_bar = bars[-2]
    today_bar = bars[-1]
    prev_close = prev_bar[4]
    ma = trend_series(bars[:-1], cfg.trend_period, cfg.trend_mode)
    d = trend_direction(prev_close, ma[-1])

    S, body1, pos1 = predict_S(S_MODEL_FROZEN, prev_bar)

    direction = "short" if d == -1 else ("long" if d == 1 else None)
    dir_cn = None if direction is None else ("做空" if direction == "short" else "做多")

    ma3_ok = trend_confirm(bars[:-1], d) if d else False
    vol_ok = (not vol_spike_filter(bars[:-1], cfg.vol_filter, cfg.vol_look)) if d else False

    lad = None
    if direction is not None:
        lad = build(today_bar[1], S, direction, prev_close=prev_close)

    return {
        "date": today_bar[0],
        "direction": direction,
        "direction_cn": dir_cn,
        "S": round(S, 2),
        "S_mae": round(S_MODEL_FROZEN["loo_mae"], 1),
        "open": today_bar[1],
        "prev_close": prev_close,
        "sma": ma[-1],
        "ma3_ok": ma3_ok,
        "vol_ok": vol_ok,
        "lad": lad,
        "body1": round(body1, 2),
        "pos1": round(pos1, 3),
    }


__all__ = ["fetch_d1", "load_bars_primary", "gen_signal",
           "SPOT_D1_CSV", "TWELVE_KEY", "SYMBOL", "TIMEZONE"]
