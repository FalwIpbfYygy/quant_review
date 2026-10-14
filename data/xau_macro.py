# -*- coding: utf-8 -*-
"""宏观数据源：美元指数 DXY + 主要非美交叉盘实时数据。

复用参考项目 D:/shit/TRAE/ICT 的方案：
- 币安期货无 DXY 合约，从 TwelveData 拉取 6 个外汇对，按 ICE 美元指数公式合成 DXY 序列。
- EUR/USD、GBP/USD、AUD/USD 等直接经 TwelveData time_series 取最新收盘 + 近 N 日序列。

ICE 美元指数公式：
    DXY = 50.14348112
          * EURUSD^(-0.576) * USDJPY^(0.136) * GBPUSD^(-0.119)
          * USDCAD^(0.091)  * USDSEK^(0.042)  * USDCHF^(0.036)

限流约束（TwelveData 免费版）：每分钟 ≤8 次、每天 ≤800 次。
本模块默认串行 + 1s 间隔 + 15 分钟长缓存，避免触发限流。
失败时返回 None（不抛异常），由上层决定降级策略。
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import time
import math
import requests
from typing import Any, Dict, List, Optional, Tuple

# ---- TwelveData 配置（密钥 / 端点来自 config，源码不再硬编码） ----
from config import TWELVEDATA_API_KEY, TD_BASE

# 合成 DXY 的 6 个外汇对及其指数幂（ICE 官方权重）
_FX_PAIRS = ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CAD", "USD/SEK", "USD/CHF"]
_FX_POWERS = {
    "EUR/USD": -0.576,
    "USD/JPY": 0.136,
    "GBP/USD": -0.119,
    "USD/CAD": 0.091,
    "USD/SEK": 0.042,
    "USD/CHF": 0.036,
}
_DXY_COEFF = 50.14348112

# 直接需要的非美交叉盘（AUD/USD 不在 6 合成对里，需单独拉）
_DIRECT_FX = ["EUR/USD", "GBP/USD", "AUD/USD"]

# 缓存：所有品种共享 15 分钟冷却，避免频繁请求触发限流
_CACHE: Dict = {"ts": 0.0, "dxy": [], "fx": {}}
_CACHE_SECONDS = 900
_REQ_INTERVAL = 1.0  # 串行请求间隔（秒）


def _get(url: str, timeout: int = 15) -> Optional[dict]:
    """请求 TwelveData，返回 JSON dict；失败/限流返回 None。"""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 429:
            return None
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("status") != "ok" or "values" not in data:
        return None
    return data


def _series_from_values(values: List[dict], interval: str) -> List[Tuple[int, float]]:
    """TwelveData values（新→旧）转为升序 [(ts_ms, close)]。

    interval 支持 '1min'/'5min'/'15min'/'1h'/'1day' 等；时间戳解析按格式自适应。
    """
    out: List[Tuple[int, float]] = []
    for v in values:
        dt_str = v.get("datetime") or v.get("date") or v.get("time")
        if not dt_str:
            continue
        ts = _parse_td(dt_str)
        try:
            close = float(v["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if ts is not None:
            out.append((ts, close))
    out.sort(key=lambda x: x[0])
    return out


def _parse_td(dt_str: str) -> Optional[int]:
    """TwelveData 时间字符串 → 毫秒时间戳。支持 'YYYY-MM-DD HH:MM:SS' 与 'YYYY-MM-DD'。"""
    dt_str = dt_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            from datetime import datetime, timezone
            dt = datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def _fetch_fx_series(symbol: str, interval: str, outputsize: int) -> List[Tuple[int, float]]:
    url = (f"{TD_BASE}/time_series?symbol={symbol}&interval={interval}"
           f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}")
    data = _get(url)
    if not data:
        return []
    return _series_from_values(data["values"], interval)


def _synthesize_dxy(fx_data: Dict[str, List[Tuple[int, float]]]) -> List[Tuple[int, float]]:
    """按时间戳对齐 6 个外汇对，逐点合成 DXY 序列（升序）。"""
    if not fx_data:
        return []
    common_ts = None
    for sym, d in fx_data.items():
        ts_set = set(t for t, _ in d)
        common_ts = ts_set if common_ts is None else (common_ts & ts_set)
    if not common_ts:
        return []
    series = []
    for ts in sorted(common_ts):
        product = 1.0
        ok = True
        for sym, power in _FX_POWERS.items():
            c = dict(fx_data[sym]).get(ts)
            if c is None or c <= 0:
                ok = False
                break
            product *= c ** power
        if ok:
            series.append((ts, _DXY_COEFF * product))
    return series


def fetch_macro(force: bool = False, interval: str = "1day", outputsize: int = 5) -> Dict[str, Any]:
    """获取宏观数据快照：{ dxy:{cur,prev,chg24}, fx:{SYM:{cur,prev,chg24}}, ok, note }

    返回结构（前端 / AI 报告消费）：
      dxy.cur    : 最新合成 DXY 值
      dxy.chg24  : 最近两点的百分比变化（近似 24h）
      fx['EUR/USD'].cur / .chg24  etc.
      ok         : bool（是否至少有一个数据可用）
      note       : 失败说明（用于降级提示）
    """
    now = time.time()
    if not force and (now - _CACHE["ts"]) < _CACHE_SECONDS:
        return _assemble_from_cache()

    # DXY 合成：拉 6 对
    fx_data: Dict[str, List[Tuple[int, float]]] = {}
    for sym in _FX_PAIRS:
        fx_data[sym] = _fetch_fx_series(sym, interval, outputsize)
        time.sleep(_REQ_INTERVAL)
    dxy_series = _synthesize_dxy(fx_data)

    # 直接交叉盘：EUR/USD、GBP/USD 已在 6 对里，AUD/USD 单独拉
    fx_direct: Dict[str, List[Tuple[int, float]]] = {}
    for sym in _DIRECT_FX:
        if sym in fx_data and fx_data[sym]:
            fx_direct[sym] = fx_data[sym]
        else:
            fx_direct[sym] = _fetch_fx_series(sym, interval, outputsize)
            time.sleep(_REQ_INTERVAL)

    _CACHE["ts"] = now
    _CACHE["dxy"] = dxy_series
    _CACHE["fx"] = {k: v for k, v in fx_direct.items()}

    return _assemble_from_cache()


def _assemble_from_cache() -> Dict[str, Any]:
    dxy_series = _CACHE["dxy"]
    fx = _CACHE["fx"]
    out: Dict[str, Any] = {"dxy": {"cur": None, "prev": None, "chg24": None},
                            "fx": {}, "ok": False, "note": ""}
    if dxy_series and len(dxy_series) >= 2:
        cur = dxy_series[-1][1]
        prev = dxy_series[-2][1]
        out["dxy"] = {
            "cur": round(cur, 3),
            "prev": round(prev, 3),
            "chg24": round((cur - prev) / prev * 100.0, 3) if prev else None,
        }
    for sym, series in fx.items():
        if series and len(series) >= 2:
            cur = series[-1][1]
            prev = series[-2][1]
            out["fx"][sym] = {
                "cur": round(cur, 5),
                "prev": round(prev, 5),
                "chg24": round((cur - prev) / prev * 100.0, 3) if prev else None,
            }
    out["ok"] = (out["dxy"]["cur"] is not None) or bool(out["fx"])
    if not out["ok"]:
        out["note"] = "TwelveData 拉取失败或触发限流（免费版 8 次/分钟），DXY/交叉盘数据暂不可用"
    return out


def get_latest_dxy(force: bool = False) -> Optional[float]:
    m = fetch_macro(force=force)
    return m["dxy"]["cur"]


# 便捷：把 "EUR/USD" 之类的 symbol 转成模板里好读的 key
def _sym_key(sym: str) -> str:
    return sym.replace("/", "")


if __name__ == "__main__":
    import json
    m = fetch_macro(force=True)
    print(json.dumps(m, ensure_ascii=False, indent=2))
