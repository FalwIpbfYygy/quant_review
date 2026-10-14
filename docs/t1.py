import requests
import numpy as np

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from config import FAPI_KLINES as BINANCE_URL


def get_kline(symbol, interval, limit=1000):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(BINANCE_URL, params=params, timeout=15)
    arr = resp.json()
    opens, highs, lows, closes = [], [], [], []
    for bar in arr:
        o = float(bar[1])
        h = float(bar[2])
        l = float(bar[3])
        c = float(bar[4])
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
    return opens, highs, lows, closes


def calc_atr(highs, lows, closes, period=14):
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)
    atr = np.convolve(tr_list, np.ones(period) / period, mode="valid")
    return atr


def detect_stage_raw(opens, highs, lows, closes, lookback=120):
    """无防抖原始阶段计算，快照模式直接使用"""
    atr_arr = calc_atr(highs, lows, closes, 14)
    if len(atr_arr) < 60:
        return "A 震荡均衡｜均值回归优先", {}
    current_atr = atr_arr[-1]
    atr_ma = np.mean(atr_arr[-60:])

    seg_highs = []
    seg_lows = []
    step = 20
    for i in range(lookback, len(closes)):
        seg_highs.append(max(highs[i - step:i]))
        seg_lows.append(min(lows[i - step:i]))

    diff_h = np.diff(seg_highs)
    diff_l = np.diff(seg_lows)

    # ========== 修复：空数组保护 ==========
    if len(diff_h) == 0:
        higher_high = False
        lower_high = False
    else:
        higher_high = np.sum(diff_h >= 0) / len(diff_h) >= 0.8
        lower_high = np.sum(diff_h <= 0) / len(diff_h) >= 0.8

    if len(diff_l) == 0:
        higher_low = False
        lower_low = False
    else:
        higher_low = np.sum(diff_l >= 0) / len(diff_l) >= 0.8
        lower_low = np.sum(diff_l <= 0) / len(diff_l) >= 0.8
    # ======================================

    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    last_close = closes[-1]

    info = {
        "current_atr": round(current_atr, 2),
        "atr_ma": round(atr_ma, 2),
        "recent_high": round(recent_high, 2),
        "recent_low": round(recent_low, 2),
        "close": round(last_close, 2),
    }

    if current_atr < atr_ma * 1.1:
        return "A 震荡均衡｜均值回归优先", info
    slope_total = (closes[-1] - closes[-lookback]) / lookback
    # 多头分支
    if higher_high and higher_low:
        if abs(last_close - recent_high) / recent_high < 0.003:
            return "B 向上突破转换｜突破策略", info
        if 0 < slope_total < 0.0008:
            return "C 稳定上升趋势｜趋势跟随", info
        elif slope_total >= 0.0008:
            shadow_ratio = np.mean([(highs[i] - closes[i]) / (highs[i] - lows[i] + 1e-8) for i in range(-40, 0)])
            if shadow_ratio > 0.45:
                return "E 冲顶失稳｜减仓，禁止新开多单", info
            else:
                return "D 加速上升｜回踩续趋势", info
    # 空头分支
    if lower_high and lower_low:
        if abs(last_close - recent_low) / recent_low < 0.003:
            return "B 向下突破转换｜突破策略", info
        if -0.0008 < slope_total < 0:
            return "C 稳定下跌趋势｜顺势空", info
        elif slope_total <= -0.0008:
            shadow_ratio = np.mean([(closes[i] - lows[i]) / (highs[i] - lows[i] + 1e-8) for i in range(-40, 0)])
            if shadow_ratio > 0.45:
                return "E 冲底失稳｜减仓，禁止新开空单", info
            else:
                return "D 加速下跌｜反弹续空", info

    if current_atr > atr_ma * 1.2:
        return "F 高波动修正｜等待突破确认，禁止猜顶抄底", info
    return "A 震荡均衡｜均值回归优先", info



class StageFilter:
    """【仅回测逐K循环场景使用】防抖锁：连续 confirm_bar 根K线输出同一阶段，才切换"""
    def __init__(self, confirm_bar=3):
        self.confirm_bar = confirm_bar
        self.last_raw_stage = None
        self.stable_stage = None
        self.same_count = 0

    def update(self, raw_stage):
        if raw_stage == self.last_raw_stage:
            self.same_count += 1
        else:
            self.same_count = 1
            self.last_raw_stage = raw_stage

        if self.same_count >= self.confirm_bar:
            self.stable_stage = raw_stage
        return self.stable_stage


if __name__ == "__main__":
    SYMBOL = ""
    o_4h, h_4h, l_4h, c_4h = get_kline(SYMBOL, interval="4h", limit=1000)
    o_1h, h_1h, l_1h, c_1h = get_kline(SYMBOL, interval="1h", limit=1000)
    o_1m, h_1m, l_1m, c_1m = get_kline(SYMBOL, interval="1m", limit=1000)

    # 快照模式直接使用raw_stage，防抖StageFilter留给回测循环
    stage_4h, info_4h = detect_stage_raw(o_4h, h_4h, l_4h, c_4h, lookback=120)
    stage_1h, info_1h = detect_stage_raw(o_1h, h_1h, l_1h, c_1h, lookback=120)
    stage_1m, info_1m = detect_stage_raw(o_1m, h_1m, l_1m, c_1m, lookback=120)

    print("===== 4H【大格局，最高权重】 =====")
    print(f"阶段:{stage_4h}")
    print(info_4h)
    print("===== 1H【中周期，入场参考】 =====")
    print(f"阶段:{stage_1h}")
    print(info_1h)
    print("===== 1min【仅精细点位，不判断行情阶段】 =====")
    print(f"阶段:{stage_1m}")
    print(info_1m)

    print("\n======== 综合交易推演 ========")
    print(f"【大周期4H】{stage_4h}")
    print(f"【中周期1H】{stage_1h}")

    if "A 震荡均衡" in stage_4h:
        print("\n👉大级别箱体震荡：优先均值回归策略；1H出现趋势仅当作震荡内部小波段，禁止重仓追趋势。")
    elif "C" in stage_4h or "D" in stage_4h:
        print("\n👉大级别趋势行情：优先顺势，回调开仓；避开E冲顶/冲底阶段新开仓。")
    elif "F" in stage_4h:
        print("\n👉大周期高波动修正：不猜反转，等待B突破信号再开仓。")

    if "B" in stage_1h:
        print("✅【1H检测到B突破转换信号，可以按规则准备入场】")
    if "F" in stage_1h:
        print("⚠️1H处于F高波动修正，严禁抄底摸顶，等待方向突破确认。")
    if "E" in stage_1h:
        print("⚠️1H处于E冲顶/冲底失稳，只减仓，禁止新开顺势单子。")




