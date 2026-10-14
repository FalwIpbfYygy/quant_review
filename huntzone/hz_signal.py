# -*- coding: utf-8 -*-
"""信号生成（自给自足）：自动估算今日跨度 S 并输出今日狩猎区卡。

移植自 hunting_zone/signal.py，并做工程化改造：
  - 文件改名 hz_signal.py，避免与 Python 标准库 signal 进程级遮蔽（uvicorn/SIGTERM 依赖之）。
  - 改相对导入 `from .engine import` → `from hz_engine import`（扁平化到 quant_review 根）。
  - 完全剥离 hunting_zone/data.py（该模块顶部污染全局代理环境变量 + 硬编码不存在的现货 CSV），
    本模块零网络、零文件 IO，纯计算。

S 预测说明（研究结论，2026-09-24）：
  - 官方 0.0 档/中枢出自未公开的「中枢回归」层，S 无法精确推导。
  - 折中：用 17 张历史官方卡反解的真值 S 做有监督线性回归，
    特征 = 前日实体(body1=│收−开│) + 前日收盘位置(pos1=(收−低)/(高−低))。
  - 留一法(LOO) MAE ≈ 21.95 点（相对 S 中位数约 32%）；模型输出带 ±LOO_MAE 误差区间，
    S 应按「区间」而非「精确点」使用；S 预测值已 clamp 到历史 S 的 [min, max]。
"""
from huntzone.hz_engine import (build, trend_series, trend_direction, trend_confirm,
                       vol_spike_filter, Config)


# --------------------------------------------------------------------------
# 自给自足（不依赖官方卡）：S 用调研阶段冻结的回归系数作常数
# --------------------------------------------------------------------------
# 调研冻结（2026-09-24）：17 张官方卡反解 S 真值 + 前日特征(b1/pos1) 的最小二乘回归。
# 冻结后为常数，运行/交易/回测时不再读取任何官方卡文件。
S_MODEL_FROZEN = {
    "a": 45.555041179875445,       # S = a + b1·body1 + b2·pos1（截距）
    "b1": 0.4112464298010658,      # 前日实体 │收−开│ 系数
    "b2": 7.803036292028391,       # 前日收盘位置 (收−低)/(高−低) 系数
    "s_min": 36.21349331026339,    # 历史 S 下界（clamp）
    "s_max": 117.62808562255931,   # 历史 S 上界（clamp）
    "loo_mae": 21.953412240825234, # 留一法 MAE（点），S 按 ±此区间浮动使用
    "source": "17 张官方卡全样本 OLS 拟合（调研一次性冻结）",
}


def _feat(bar):
    """bar=(date,o,h,l,c) → (body1, pos1)。"""
    o, h, l, c = bar[1], bar[2], bar[3], bar[4]
    rng = h - l
    body1 = abs(c - o)
    pos1 = (c - l) / rng if rng > 0 else 0.5
    return body1, pos1


def predict_S(model, prev_bar):
    """用「前一交易日 bar」预测今日 S，返回 (S, body1, pos1)。"""
    body1, pos1 = _feat(prev_bar)
    s = model["a"] + model["b1"] * body1 + model["b2"] * pos1
    s = max(model["s_min"], min(model["s_max"], s))
    return s, body1, pos1


def generate_self_sufficient(bars, cfg):
    """自给自足生成今日狩猎区卡：不读取官方卡。

    - 方向 = sign(昨收 − SMA/EMA(收盘, N))，纯 K 线数据，完全自给。
    - S = S_MODEL_FROZEN 冻结回归系数 + 前日特征（body1, pos1）预测。

    返回 build() 的档位 dict；若方向临界 / 趋势未成立 / 波动过滤空仓则返回 None。
    （None 由调用方负责给出结构化原因，不在本层 print。）
    """
    bars = sorted(bars, key=lambda b: b[0])
    if len(bars) < 7:
        return None

    today = bars[-1]
    prev_bar = bars[-2]              # 昨日完整 bar
    prev_history = bars[:-1]         # 不含今日（进行中）bar

    ma = trend_series(prev_history, cfg.trend_period, cfg.trend_mode)
    prev_close = prev_bar[4]
    d = trend_direction(prev_close, ma[-1])
    if d == 0:
        return None
    if cfg.trend_filter == "ma3" and not trend_confirm(prev_history, d):
        return None
    if cfg.vol_filter and vol_spike_filter(prev_history, cfg.vol_filter, cfg.vol_look):
        return None
    direction = "short" if d == -1 else "long"

    S, body1, pos1 = predict_S(S_MODEL_FROZEN, prev_bar)

    lad = build(today[1], S, direction, prev_close=prev_close)
    lad["mae"] = S_MODEL_FROZEN["loo_mae"]
    lad["body1"] = round(body1, 2)
    lad["pos1"] = round(pos1, 3)
    return lad
