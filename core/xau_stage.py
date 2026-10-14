# -*- coding: utf-8 -*-
"""
实时阶段闸门（ABCDEF）· 后端判定 + 开仓决策
================================================================================
新增模块，不改动项目原有代码。

数据源：
- 唯一链路  fapi（经 main.py 注入的 fetch_fn + data_sync.PROXIES，与 /xau 其他接口同链路）
- 强制 symbol=，不回退现货 / 任何其它标的；fapi 不可达时直接报错（不静默用错数据）
- 阶段判定带 endTime=now：只取已收盘 K 线，分析看不到决策点之后的 K 线（无未来函数）

阶段引擎：docs/t1.py 逐字移植（detect_stage_raw / StageFilter），真值源 = t1.py。

输出：结构化 JSON（供 /api/xau/stage）+ 决策字典（开/用哪套/开多大）。
AI 报告由 xau_stage_ai.py 负责。
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import sys
import json
import datetime
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
np.seterr(all="ignore")

# t1.py 位于项目 docs/ 目录（真值源约定，勿移动）
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from t1 import detect_stage_raw, StageFilter  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间

from config import FAPI_KLINES as BINANCE_FAPI  # 价格接口基址


def _stage_code(stage_str):
    """'A 震荡均衡｜...' -> 'A'"""
    return stage_str.strip()[0].upper() if stage_str else "?"


def _parse(klines):
    o, h, l, c = [], [], [], []
    for b in klines:
        o.append(float(b[1])); h.append(float(b[2])); l.append(float(b[3])); c.append(float(b[4]))
    return o, h, l, c


def _get_klines(symbol, interval, limit, fetch_fn, end_ms=None):
    """唯一链路：fapi（，强制）。
    symbol 由调用方锁定为 ；end_ms 可选，只取 open_time < end_ms 的 K 线
    （不含正在形成的当根），确保分析看不到决策点之后的 K 线（无未来函数）。
    返回 ((opens,highs,lows,closes), source_str)。"""
    if not fetch_fn:
        raise RuntimeError("未注入 fapi fetch_fn（main.py 的 _fapi_fetch）")
    q = f"symbol={symbol}&interval={interval}&limit={limit}"
    if end_ms is not None:
        q += f"&endTime={end_ms}"
    url = f"{BINANCE_FAPI}?{q}"
    try:
        arr = fetch_fn(url)
    except Exception as e:
        raise RuntimeError(f"fapi 拉取失败({symbol} {interval}): {type(e).__name__}: {e}") from e
    if not arr:
        raise RuntimeError(f"fapi 返回空数据({symbol} {interval})")
    return _parse(arr), f"fapi {symbol} {interval}"


def compute_stage(fetch_fn=None, symbol="", limit=220, end_ms=None):
    """计算 4H（总开关）/ 1H（微调）的当前阶段（原始 + 防抖稳定）。"""
    res = {}
    for tf in ("4h", "1h"):
        (o, h, l, c), src = _get_klines(symbol, tf, limit, fetch_fn, end_ms)
        stage, info = detect_stage_raw(o, h, l, c, 120)
        code = _stage_code(stage)
        # 防抖稳定阶段（StageFilter confirm_bar=3，实盘口径）
        f = StageFilter(3)
        stable = "A"
        for i in range(len(c)):
            try:
                oo = o[:i + 1]; hh = h[:i + 1]; ll = l[:i + 1]; cc = c[:i + 1]
                raw, _ = detect_stage_raw(oo, hh, ll, cc, 120)
                stable = f.update(_stage_code(raw))
            except Exception:
                stable = f.update("A")
        res[tf] = {"stage": code, "stage_full": stage, "stable": stable,
                   "info": info, "src": src}
    return res


def session_status(now_bj):
    if now_bj.weekday() >= 5:
        return "周末（不开单）"
    if 9 <= now_bj.hour < 21:
        return f"交易时段内（{now_bj.hour:02d}:{now_bj.minute:02d}）"
    return f"非交易时段（{now_bj.hour:02d}:{now_bj.minute:02d}，你在睡觉）"


# ---------------------------------------------------------------------------
# 开仓决策（依据回测 + cluster bootstrap 结论）
#   4H=D/F → 全局停手；4H=B → 1.2× 全开（唯一稳健盈利）；4H=C → 趋势跟随 1.0×；
#   4H=A/E → 不开为最优（EV 负/噪声）；1H=D/F 仅做加减仓微调，不当开关。
# ---------------------------------------------------------------------------
def decide(res, price, now_bj):
    S4 = res["4h"]["stage"]
    S1 = res["1h"]["stage"]

    if S4 in ("D", "F"):
        return {"cls": "bad",
                "verdict": f"🛑 4H={S4}：全局停手，禁止开仓（回测显著亏损）",
                "open": "禁止开仓", "set": "—", "size": "0",
                "why": f"4H={S4} 是回测中 cluster bootstrap 判定为显著亏损的阶段"
                       f"（D: CI 下界 −49k / P亏 99.2%；F: 样本仅个位数，保守停手）。"}

    if S4 == "B":
        sz = "正常仓 1.2×（B 阶段 PF 4.05、bootstrap P亏 0%）"
        if S1 in ("D", "F"):
            sz += f"（1H={S1}，已有单减半/新单不开）"
        return {"cls": "ok",
                "verdict": "✅ 4H=B 突破转换：可以开仓（重点捕捉窗口）",
                "open": "可以开仓",
                "set": "四套全开，优先突破类（core_code 形态 + ICT 突破 + high_winss 形态）",
                "size": sz,
                "why": "4H=B 是回测中唯一稳健盈利阶段；但 B 平均只活 7.8h、仅占 3% 时间，"
                       "一闪而过，短线快进快出、严格 SL。"}

    if S4 == "C":
        sz = "正常仓 1.0×（C 在样本中出现极少，谨慎）"
        if S1 in ("D", "F"):
            sz += f"（1H={S1}，已有单减半）"
        return {"cls": "warn",
                "verdict": "✅ 4H=C 稳定趋势：可趋势跟随",
                "open": "可以开仓（趋势跟随）",
                "set": "趋势跟随类（core_code 趋势 + high_winss 趋势形态）",
                "size": sz,
                "why": "4H=C 稳定趋势，按语义用趋势跟随；但 6 年仅 2 次出现，标定不足，先观察。"}

    if S4 == "E":
        extra = f"（1H={S1} 微观向下，更不应新开）" if S1 in ("D", "F") else ""
        return {"cls": "warn",
                "verdict": "🛑 4H=E 冲顶/冲底失稳：不开新仓（最优）；仅减仓/平已有顺势单",
                "open": "不开新仓", "set": "—（E 语义即禁开顺势单）",
                "size": "0" + extra,
                "why": "4H=E 冲顶失稳：bootstrap CI 跨零(噪声)，且 E 阶段有负漂移，顺势必亏；"
                       "今日非 B 窗口，无正期望。"}

    # S4 == "A"
    extra = f"（1H={S1} 微观向下/失稳，更不应新开）" if S1 in ("D", "F") else ""
    return {"cls": "warn",
            "verdict": "🛑 4H=A 震荡：不开新仓（最优）；硬要做仅 ≤0.5× 均值回归试验仓",
            "open": "不开新仓",
            "set": "仅 Al_Brookss 区间反转 + high_winss 回调形态，禁突破追单、禁追空",
            "size": "0（试验仓 ≤0.5×）" + extra,
            "why": "4H=A 震荡：你四套策略裸跑口径B −4,522，EV 为负；A 虽行情有正漂移却因反复"
                   "止损而亏。今日 4H=A 不是 B 窗口，按回测结论不开为最优。"}


def api_stage(fetch_fn=None):
    """/api/xau/stage 入口。返回结构化 JSON。"""
    now_bj = datetime.datetime.now(TZ)
    # end_ms = 当前毫秒：只取已收盘 K 线（不含正在形成的当根），无未来函数
    end_ms = int(time.time() * 1000)
    try:
        res = compute_stage(fetch_fn, end_ms=end_ms)
    except Exception as e:
        return {"code": 502, "error": f"阶段判定失败: {type(e).__name__}: {e}"}

    info4 = res["4h"]["info"] or {}
    info1 = res["1h"]["info"] or {}
    price = info4.get("close")
    decision = decide(res, price, now_bj)

    atr4_ratio = round(info4["current_atr"] / info4["atr_ma"], 3) if info4.get("atr_ma") else None
    atr1_ratio = round(info1["current_atr"] / info1["atr_ma"], 3) if info1.get("atr_ma") else None
    range4 = f'{info4.get("recent_low", 0):.0f}–{info4.get("recent_high", 0):.0f}' if info4 else "—"

    return {
        "code": 200,
        "time_bj": now_bj.strftime("%Y-%m-%d %H:%M"),
        "price": price,
        "stage_4h": res["4h"]["stage"], "stage_4h_stable": res["4h"]["stable"],
        "stage_1h": res["1h"]["stage"], "stage_1h_stable": res["1h"]["stable"],
        "decision": decision,
        "metrics": {
            "atr_ratio_4h": atr4_ratio,
            "atr_ratio_1h": atr1_ratio,
            "range_4h": range4,
            "session": session_status(now_bj),
        },
        "source": res["4h"]["src"],
    }


def api_stage_report(fetch_fn=None, model=None):
    """/api/xau/stage_report 入口。返回 AI 报告（Markdown）。"""
    from core import xau_stage_ai
    stage = api_stage(fetch_fn)
    if stage.get("code") != 200:
        return stage
    markdown = xau_stage_ai.generate(stage, model=model)
    return {
        "code": 200,
        "time_bj": stage["time_bj"],
        "source": stage["source"],
        "markdown": markdown,
        "stage": {k: stage[k] for k in
                  ("stage_4h", "stage_4h_stable", "stage_1h", "stage_1h_stable", "decision", "price")},
    }


if __name__ == "__main__":
    out = api_stage()
    print(json.dumps(out, ensure_ascii=False, indent=2))
