# -*- coding: utf-8 -*-
"""白银 XAGUSD 狩猎区复盘 · 数据源层（纯新增，不改动任何既有文件）。

数据来源：**XAGUSDT USDT-M 合约**（价格接口基址 FAPI_KLINES，由 .env 的 BINANCE_FAPI_BASE 配置），与用户指定接口一致。
本模块复用同一端点，按需要传 interval / startTime / endTime / limit：
  - 日线：interval=1d   （供狩猎区信号：SMA10 顺势 + S_MODEL_FROZEN + build）
  - 30m ：interval=30m  （供每列 K 线，单请求拉整段范围后按 UTC 日拆分）

取数链路：复用项目统一 config.PROXIES + requests（与 /api/realtime/klines、_fapi_fetch 一致）。
代理默认直连；本地 Windows 出网需在 .env 设 KLINE_PROXY=。

红线：
  - 严格零未来函数：日线只用 ≤ 该日收盘 bar；30m 只用已收盘 bar（fapi 返回的即已收盘）。
  - 取数失败一律抛异常，由 core 统一返回 ok=False，绝不猜 S。
"""
import datetime
import time
import requests

from config import PROXIES

UTC = datetime.timezone.utc
from config import FAPI_KLINES as FAPI
SYMBOL = "XAGUSDT"
# 支持的币种（均为 Binance USDT-M 永续，fapi 可用）。新增币种在此追加即可。
ALLOWED_SYMBOLS = ("XAGUSDT", "ETHUSDT", "BTCUSDT")


def _valid_symbol(sym):
    """校验并归一化交易对；不在白名单直接抛错（绝不猜、绝不回退 XAG）。"""
    sym = (sym or "").upper().strip()
    if sym not in ALLOWED_SYMBOLS:
        raise ValueError("不支持的交易对：%s（仅支持 %s）"
                         % (sym or "空", "/".join(ALLOWED_SYMBOLS)))
    return sym


def _get(url, timeout=15, retries=4, backoff=1.0):
    """复用项目代理链路取 fapi klines，返回原始二维数组。

    带重试 + 指数退避：本地代理对 Binance 偶发抖动（502/超时），
    单次请求无重试会直接失败；此处最多重试 4 次（1s/2s/4s）抗偶发抖动。
    """
    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, proxies=PROXIES, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    if last is not None:
        raise last
    raise RuntimeError("未知取数失败")


def _date_to_open_ms(date: str) -> int:
    """UTC 当日 00:00 毫秒（与 huntback_sim._date_to_open_ms 同口径）。"""
    y, m, d = map(int, date.split("-"))
    return int(datetime.datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def _utc_date_str(ts_ms: int) -> str:
    return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def fetch_d1(end_date: str, lookback: int = 150, symbol: str = SYMBOL):
    """拉取指定币种日线（fapi 1d），返回 [(date, o, h, l, c)] 升序。

    - 以 end_date 当天为终点，向前 lookback 个自然日（覆盖 SMA 预热）。
    - 期货 24/7 交易，周末也有 bar；不再剔除周末（与 XAU 现货口径不同）。
    - 失败抛异常（调用方处理）。
    """
    symbol = _valid_symbol(symbol)
    end_ms = _date_to_open_ms(end_date) + 86400000  # 含 end 当天
    start_ms = end_ms - lookback * 86400000
    url = (FAPI + "?symbol=%s&interval=1d&startTime=%d&endTime=%d&limit=1500"
           % (symbol, start_ms, end_ms))
    rows = _get(url)
    if not rows:
        raise RuntimeError("fapi 返回空数组（%s 1d 不可得）" % symbol)
    bars = []
    for r in rows:
        ts = int(r[0])
        o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
        dt = _utc_date_str(ts)
        bars.append((dt, o, h, l, c))
    bars.sort(key=lambda b: b[0])
    if not bars:
        raise RuntimeError("拉取后无有效日线")
    return bars


def fetch_30m_range(start_ms: int, end_ms: int, symbol: str = SYMBOL):
    """拉取 [start_ms, end_ms) 内全部 30m K线，返回 [(ts_ms, o, h, l, c)] 升序。

    单请求覆盖整段范围（≤30 天 × 48 = 1440 根 < 1500 上限）。失败抛异常。
    """
    symbol = _valid_symbol(symbol)
    url = (FAPI + "?symbol=%s&interval=30m&startTime=%d&endTime=%d&limit=1500"
           % (symbol, start_ms, end_ms))
    rows = _get(url)
    out = []
    for r in rows:
        out.append((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    out.sort(key=lambda b: b[0])
    return out


def suggested_S(daily_bars, factor: float = 0.6, window: int = 20):
    """白银自适应 S 建议值：近期真实波幅(TR)中位数 × factor。

    冻结模型 S_MODEL_FROZEN 是按黄金标定的（36~117 美元点），白银单价仅 ~$40，
    直接套用会数量级错配。此值仅作「可用」默认建议，用户可自行覆盖。
    """
    if len(daily_bars) < 2:
        return None
    trs = []
    for i in range(1, len(daily_bars)):
        pc = daily_bars[i - 1][4]
        o, h, l, c = daily_bars[i][1], daily_bars[i][2], daily_bars[i][3], daily_bars[i][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if not trs:
        return None
    recent = trs[-window:]
    recent.sort()
    med = recent[len(recent) // 2]
    s = med * factor
    return round(s, 2)
