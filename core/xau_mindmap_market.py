# -*- coding: utf-8 -*-
"""
 思维导图 · 行情对话（AI 分析师 · 实验模块）

⚠️ 定位与隔离（重要）
--------------------
1. 本模块是**独立的 AI 观点生成器**，与用户的 TRAE 纯规则量化系统**物理隔离**：
   - 只读行情（Binance fapi ）+ 只读知识库规则
   - **不写任何信号库 / 不触发任何下单 / 不接入 TRAE 信号链路**
   - 用户（2026-09-09）确认「完全放开：方向+点位+止损止盈」放行边界后，**不再附 AI 水印**
2. 无未来函数：只取 open_time < now 的**已收盘** K 线（丢弃正在形成的当根）。
3. 无 LLM Key 时**不瞎编**：返回 code=503 并只给客观事实表，不生成任何观点。

与 xau_mindmap.py 的分工：
   xau_mindmap.py        = 知识库检索（纯教学，拒绝一切交易建议）
   xau_mindmap_market.py = 行情对话（AI 观点，可给方向/点位/止损止盈）
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import math
import os
import time
import logging
import datetime

import numpy as np

np.seterr(all="ignore")

LOG = logging.getLogger("xau_mindmap_market")

TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间
from config import FAPI_KLINES as BINANCE_FAPI  # 价格接口基址
SYMBOL = ""   # 强制锁定，不允许改成现货/其他 symbol

# 多周期取值计划：(时间框架, 根数)
TF_PLAN = [("1d", 60), ("4h", 150), ("1h", 200), ("15m", 120), ("5m", 120)]

# 注：用户（2026-09-09）已确认"完全放开：方向+点位+止损止盈"放行边界，
#     不再附加 AI 水印。物理隔离仍由模块边界（只读行情/不接 TRAE）保证。


# =====================================================================
# 1. 取数（唯一链路：Binance fapi ，无未来函数）
# =====================================================================

def _parse(klines, drop_unclosed=True):
    """Binance klines -> dict(opens/highs/lows/closes/volumes/times)

    drop_unclosed=True 时丢弃最后一根（正在形成、未收盘），保证**无未来函数**。
    """
    if not klines:
        raise RuntimeError("fapi 返回空数据")
    rows = klines[:-1] if (drop_unclosed and len(klines) > 1) else klines
    return {
        "t": [int(b[0]) for b in rows],
        "o": [float(b[1]) for b in rows],
        "h": [float(b[2]) for b in rows],
        "l": [float(b[3]) for b in rows],
        "c": [float(b[4]) for b in rows],
        "v": [float(b[5]) for b in rows],
    }


def _get(symbol, interval, limit, fetch_fn, end_ms=None, drop_unclosed=True):
    """唯一链路：fapi。end_ms 缺省 = 现在；只保留已收盘 K 线。"""
    if not fetch_fn:
        raise RuntimeError("未注入 fapi fetch_fn（main.py 的 _fapi_fetch）")
    q = f"symbol={symbol}&interval={interval}&limit={limit}"
    if end_ms is not None:
        q += f"&endTime={end_ms}"
    arr = fetch_fn(f"{BINANCE_FAPI}?{q}")
    return _parse(arr, drop_unclosed=drop_unclosed)


# =====================================================================
# 2. 客观事实计算（纯确定性，无 AI 参与，可审计）
# =====================================================================

def _ema(vals, n):
    if len(vals) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _atr(k, n=14):
    h, l, c = k["h"], k["l"], k["c"]
    if len(c) < n + 1:
        return None
    trs = []
    for i in range(len(c) - n, len(c)):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return float(np.mean(trs))


def _swings(k, w=5, max_n=6):
    """找摆动高低点：h[i] 是 [i-w, i+w] 内最大 → swing high。返回 [(idx, price), ...] 由新到旧。"""
    h, l = k["h"], k["l"]
    hi, lo = [], []
    for i in range(w, len(h) - w):
        if h[i] == max(h[i - w:i + w + 1]):
            hi.append((i, h[i]))
        if l[i] == min(l[i - w:i + w + 1]):
            lo.append((i, l[i]))
    # 去重相邻（价格接近只保留最新的）
    def dedup(arr):
        out = []
        for idx, p in reversed(arr):
            if not out or abs(out[-1][1] - p) > 1e-9:
                out.append((idx, p))
        return list(reversed(out))[-max_n:]
    return dedup(hi), dedup(lo)


def _patterns(k):
    """最近 K 线的客观形态判定（对齐 M02/M03 规则）：顶分型/底分型/孕线/平顶/锤子线"""
    h, l, c, o = k["h"], k["l"], k["c"], k["o"]
    out = {}
    if len(c) < 3:
        return out
    # 顶分型：中间 K 高点最高且低点最高
    if h[-2] > h[-3] and h[-2] > h[-1] and l[-2] > l[-3] and l[-2] > l[-1]:
        out["顶分型"] = {"at": h[-2], "bar": len(c) - 2}
    # 底分型：中间 K 低点最低且高点最低
    if l[-2] < l[-3] and l[-2] < l[-1] and h[-2] < h[-3] and h[-2] < h[-1]:
        out["底分型"] = {"at": l[-2], "bar": len(c) - 2}
    # 孕线（母包子）：最后一根被前一根完全包住
    if h[-1] <= h[-2] and l[-1] >= l[-2]:
        out["孕线(母包子)"] = {"mother_high": h[-2], "mother_low": l[-2]}
    # 平顶：两根高点几乎齐平且都有上影线
    body_hi = lambda i: max(o[i], c[i])
    body_lo = lambda i: min(o[i], c[i])
    up_sh = lambda i: h[i] - body_hi(i)
    dn_sh = lambda i: body_lo(i) - l[i]
    price = c[-1]
    if abs(h[-1] - h[-2]) <= max(price * 0.0015, 0.3) and up_sh(-1) > 0 and up_sh(-2) > 0:
        out["平顶(上P)"] = {"at": round(min(h[-1], h[-2]), 2)}
    # 锤子线 / 平顶加（P加）：长下影
    body = abs(c[-1] - o[-1])
    if dn_sh(-1) >= 2 * max(body, 1e-9) and up_sh(-1) <= 0.4 * dn_sh(-1):
        out["锤子线(平顶加/P加)"] = {"low": l[-1], "body_high": round(body_hi(-1), 2)}
    return out


def _w_m(k, atr, tol_ratio=0.35):
    """W 底 / M 顶客观判定：最近两个 swing 点价格接近（容差 = tol_ratio × ATR）"""
    hi, lo = _swings(k)
    tol = (atr or 0) * tol_ratio
    res = {}
    # W 底：两个 swing low 接近，中间有更高的 swing high（颈线）
    if len(lo) >= 2 and atr:
        a, b = lo[-2], lo[-1]
        if abs(a[1] - b[1]) <= tol:
            neck_hi = [p for idx, p in hi if a[0] < idx < b[0]]
            if neck_hi:
                res["W底"] = {"low1": round(a[1], 2), "low2": round(b[1], 2),
                              "neckline": round(max(neck_hi), 2)}
    # M 顶：两个 swing high 接近，中间有更低的 swing low（颈线）
    if len(hi) >= 2 and atr:
        a, b = hi[-2], hi[-1]
        if abs(a[1] - b[1]) <= tol:
            neck_lo = [p for idx, p in lo if a[0] < idx < b[0]]
            if neck_lo:
                res["M顶"] = {"high1": round(a[1], 2), "high2": round(b[1], 2),
                              "neckline": round(min(neck_lo), 2)}
    return res


def _poc(k, bucket=None, lookback=120):
    """成交量控制点 POC：把每根 K 线的成交量按典型价归入价格桶，取成交量最大的桶。"""
    c, v, h, l = k["c"], k["v"], k["h"], k["l"]
    seg = slice(max(0, len(c) - lookback), len(c))
    cs, vs, hs, ls = c[seg], v[seg], h[seg], l[seg]
    if not cs:
        return None
    if bucket is None:
        rng = max(hs) - min(ls)
        bucket = max(rng / 40.0, 0.5)
    buckets = {}
    for i in range(len(cs)):
        tp = (hs[i] + ls[i] + cs[i]) / 3.0
        key = round(tp / bucket) * bucket
        buckets[key] = buckets.get(key, 0.0) + vs[i]
    if not buckets:
        return None
    pk = max(buckets, key=buckets.get)
    return {"price": round(float(pk), 2), "bucket": round(float(bucket), 2),
            "volume": round(float(buckets[pk]), 2)}


def _mid50(price):
    """50 关键中线（M12 规则）：当前价所在的 50 美元整数区间"""
    lo = math.floor(price / 50.0) * 50.0
    hi = lo + 50.0
    return {"zone_low": round(lo, 2), "zone_high": round(hi, 2),
            "mid": round(lo + 25.0, 2),
            "dist_to_low": round(price - lo, 2), "dist_to_high": round(hi - price, 2)}


def compute_facts(fetch_fn, end_ms=None, with_stage=True):
    """拉取多周期 K 线 → 计算客观事实。返回 dict。无 AI 参与，完全可审计。"""
    tfs = {}
    for tf, lim in TF_PLAN:
        try:
            k = _get(SYMBOL, tf, lim, fetch_fn, end_ms=end_ms)
        except Exception as e:
            LOG.warning("取数失败 %s: %s", tf, e)
            tfs[tf] = {"error": f"{type(e).__name__}: {e}"}
            continue
        c, h, l = k["c"], k["h"], k["l"]
        atr = _atr(k)
        info = {
            "bars": len(c),
            "close": round(c[-1], 2),
            "prev_close": round(c[-2], 2) if len(c) > 1 else None,
            "chg_pct": round((c[-1] / c[-2] - 1) * 100, 3) if len(c) > 1 else None,
            "ema20": round(_ema(c, 20), 2) if _ema(c, 20) else None,
            "ema50": round(_ema(c, 50), 2) if _ema(c, 50) else None,
            "atr14": round(atr, 2) if atr else None,
        }
        # 近 20 根高低
        n = min(20, len(c))
        info["high20"] = round(max(h[-n:]), 2)
        info["low20"] = round(min(l[-n:]), 2)
        # 摆动点 + W/M + 形态
        hi, lo = _swings(k)
        info["swing_highs"] = [round(p, 2) for _, p in hi[-3:]]
        info["swing_lows"] = [round(p, 2) for _, p in lo[-3:]]
        info["wm"] = _w_m(k, atr)
        info["patterns"] = _patterns(k)
        if tf == "4h":
            info["poc"] = _poc(k)
        tfs[tf] = info

    # 日线：昨日高低收（PDH / PDL / PDC）
    levels = {}
    try:
        d = _get(SYMBOL, "1d", 5, fetch_fn, end_ms=end_ms)
        levels["PDH"] = round(d["h"][-1], 2)
        levels["PDL"] = round(d["l"][-1], 2)
        levels["PDC"] = round(d["c"][-1], 2)
        if len(d["c"]) > 1:
            levels["前日高"] = round(d["h"][-2], 2)
            levels["前日低"] = round(d["l"][-2], 2)
    except Exception as e:
        levels["error"] = str(e)

    price = tfs.get("1h", {}).get("close") or tfs.get("4h", {}).get("close")
    if price:
        levels["current"] = price
        levels["mid50"] = _mid50(price)

    # ABCDEF 六阶段（用户核心模型，复用 xau_stage；失败不影响其余）
    stage = {}
    if with_stage:
        try:
            from core import xau_stage as xs
            st = xs.compute_stage(fetch_fn=fetch_fn, symbol=SYMBOL, end_ms=end_ms)
            for tf in ("4h", "1h"):
                if tf in st:
                    stage[tf] = {"stage": st[tf].get("stage"),
                                 "stable": st[tf].get("stable"),
                                 "full": st[tf].get("stage_full")}
        except Exception as e:
            stage["error"] = f"{type(e).__name__}: {e}"

    now_bj = datetime.datetime.now(TZ)
    return {
        "symbol": SYMBOL,
        "asof_bj": now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": "周末" if now_bj.weekday() >= 5 else "交易日",
        "unclosed_bar_dropped": True,   # 无未来函数凭证
        "tfs": tfs,
        "levels": levels,
        "stage": stage,
    }


def format_facts(f) -> str:
    """把客观事实渲染成给 LLM 看的紧凑文本。"""
    L = []
    L.append(f"品种：{f['symbol']}（Binance 永续，非现货）")
    L.append(f"数据截至（北京时间）：{f['asof_bj']}　{f['weekday']}")
    L.append("取数口径：只含已收盘 K 线（已丢弃正在形成的当根），无未来函数")
    L.append("")
    lv = f.get("levels", {})
    if lv:
        L.append("【关键位】")
        for k in ("current", "PDH", "PDL", "PDC", "前日高", "前日低"):
            if k in lv:
                L.append(f"  {k} = {lv[k]}")
        m = lv.get("mid50")
        if m:
            L.append(f"  50 中线区间 = [{m['zone_low']}, {m['zone_high']}]，"
                     f"中值 {m['mid']}，距下沿 {m['dist_to_low']}，距上沿 {m['dist_to_high']}")
        L.append("")
    for tf in ("1d", "4h", "1h", "15m", "5m"):
        d = f.get("tfs", {}).get(tf)
        if not d:
            continue
        if "error" in d:
            L.append(f"【{tf}】取数失败：{d['error']}")
            continue
        L.append(f"【{tf}】收盘 {d['close']}（涨跌 {d['chg_pct']}%）"
                 f"　EMA20 {d['ema20']}　EMA50 {d['ema50']}　ATR14 {d['atr14']}")
        L.append(f"　近20根 高 {d['high20']} / 低 {d['low20']}")
        if d.get("swing_highs"):
            L.append(f"　摆动高点 {d['swing_highs']}　摆动低点 {d['swing_lows']}")
        if d.get("wm"):
            for name, v in d["wm"].items():
                L.append(f"　形态 {name}：{v}")
        if d.get("patterns"):
            L.append(f"　最近K线形态：{d['patterns']}")
        if d.get("poc"):
            L.append(f"　POC（成交量控制点）：{d['poc']['price']}（桶宽 {d['poc']['bucket']}）")
    st = f.get("stage", {})
    if st:
        L.append("")
        L.append("【ABCDEF 六阶段（用户核心模型）】")
        for tf in ("4h", "1h"):
            if tf in st and isinstance(st[tf], dict):
                L.append(f"　{tf}：原始 {st[tf].get('stage')} / 防抖稳定 {st[tf].get('stable')}"
                         f"　{st[tf].get('full')}")
        if "error" in st:
            L.append(f"　（阶段计算不可用：{st['error']}）")
    return "\n".join(L)


# =====================================================================
# 3. LLM 行情观点（可给方向 / 点位 / 止损止盈）
# =====================================================================

SYSTEM_MARKET = """你是 （黄金）资深日内/波段交易分析师。你会收到两部分输入：

A.【客观盘面事实】——由程序从 Binance  实时计算，只含已收盘 K 线，无未来函数。
B.【思维导图规则】——用户自有交易体系知识库的检索结果（形态/止损/颈线/POC/50中线/共振等）。

你必须严格按以下结构输出（简体中文，直接输出 Markdown 文本）：

## 一、盘面定性
趋势 or 震荡；当前所处结构（W底 / M顶 / 区间 / 突破 / 回踩）；多周期是否共振。

## 二、方向观点
**做多** / **做空** / **观望**（三选一，必须明确给出，不许含糊）。附一句话理由。

## 三、交易方案（Markdown 表格）
| 项 | 数值 | 依据 |
|---|---|---|
| 进场区间 | ... | ... |
| 止损 | ... | 形态 ±0.3 / 结构位 / ATR 倍数 |
| 止盈1 | ... | 盈亏比 ≥ 2:1 |
| 止盈2 | ... | ... |
| 建议仓位 | ... | 单笔风险 ≤ 总资金 1% |
| 消息面约束 | ... | 未来N小时有★≥3数据（美联储/CPI/非农/初请…）时的规避或顺势方案 |

## 四、依据（引用规则编号）
逐条列出，格式：`M03-R04 各形态止损设置方案（+0.3/-0.3 偏移）`——说明它如何支持上面的判断。

## 五、失效条件
明确列出：价格走到哪里 / 出现什么形态，就说明这个判断错了，必须离场。

## 六、风险提示
最多 3 条，针对当前盘面（如：数据行情、流动性、震荡假突破）。

## 七、消息面与数据窗口约束（仅当【消息面（金十）】段存在时生效）
若用户问题涉及交易方案 / 方向，你必须结合【消息面（金十）】段：
1. 在「三、交易方案」表格的「消息面约束」行，列出未来 24–72 小时内将公布的 ★≥3 数据时点（如美联储决议、CPI、非农、初请），并说明方案如何规避或应对数据行情（数据前减仓 / 数据后顺势）。
2. 在「五、失效条件」中必须包含：若关键数据公布方向与持仓相反（如做多遇到鹰派决议 / 强美元数据），应视为失效或减仓信号。
3. 价格口径铁律：金十是**现货 **，Binance 是**永续 **，存在基差；消息面价格只用于判断美元强弱 / 风险偏好，**所有交易点位一律取自【客观盘面事实】（Binance），严禁把现货价与永续价混算**。
4. 时效铁律：每条消息面自带北京时间戳；已公布事件按「已公布」处理，未公布的按「待公布」处理，不得把已公布事件当成「即将公布」。
5. 若【消息面（金十）】段标注「消息面不可用」，直接忽略本节，不得编造任何事件或数值。

格式铁律（直接关系前端可读性）：
1. 所有价格数字必须来自【客观盘面事实】或由其可推导，**禁止编造**。
2. 必须给出失效条件，不允许只讲对的可能。
3. 不允许承诺胜率、不允许说"必涨/必跌"。
4. 若【客观盘面事实】不足以支撑判断，直接说"观望"，不要硬凑方案。
5. **不要在标题/段首加 emoji 装饰**（📊 ✅ ❌ 🚀 之类）。
6. **不要用反斜杠转义字符**（不要写 `\\n` `\\*` `\\\\` 等）——直接用 Markdown 语法。
7. **不要用代码块（```）包裹整个回答**——前端已用 marked 渲染，写了反而变成多行原文本。
8. **数字精炼到 1 位**，如 `4385.30` 不要写成 `4385.300000`；可用则用表格而不是段落堆叠。
"""

USER_MARKET = """【客观盘面事实】
{facts}

【思维导图规则（知识库检索结果）】
{rules}

【消息面（金十）】
{news}

【用户问题】
{question}

请按系统要求的结构输出。"""


def market_chat(question: str, fetch_fn, top_k: int = 6, max_tokens: int = 4096,
                with_news: bool = True) -> dict:
    """行情对话主入口：取实时行情 → 算客观事实 → 检索规则 → LLM 出观点。

    注：max_tokens 升到 4096，给长 prompt + 长回答留余量（之前默认 1600 已被验证不够）。

    返回 dict：
      code=200 正常（mode='llm'）
      code=503 未配置 LLM Key（只返回客观事实，不生成任何观点）
      code=502 行情取数失败
    """
    t0 = time.time()
    # 1) 客观事实
    try:
        facts = compute_facts(fetch_fn)
    except Exception as e:
        return {"code": 502, "msg": f"行情取数失败: {type(e).__name__}: {e}", "data": {}}

    facts_txt = format_facts(facts)

    # 2) 知识库规则检索
    rules_txt = "（无匹配规则）"
    sources = []
    try:
        from core import xau_mindmap as xm
        hits = xm.search(question or "当前盘面 形态 止损 颈线 共振", top_k=top_k)
        lines = []
        for mod, rule, sc in hits:
            lines.append(f"- 【{mod.mid} / {rule.id}】{rule.name}\n  {rule.detail}")
            sources.append({"module": mod.mid, "module_title": mod.title,
                            "rule": rule.id, "rule_name": rule.name, "score": round(sc, 3)})
        if lines:
            rules_txt = "\n".join(lines)
    except Exception as e:
        LOG.warning("规则检索失败: %s", e)

    # 2.5) 消息面（金十），独立 try/except，任一源失败只丢消息面段
    news_text = "（未结合消息面）"
    if with_news:
        try:
            from data import xau_news as xn
            nf = xn.compute_news_facts()
            news_text = nf.get("text") or "（消息面不可用）"
        except Exception as e:
            LOG.warning("消息面取数失败: %s", e)
            news_text = "（消息面不可用：%s）" % e

    # 3) LLM（配置复用项目 config.py，与 /xau 报告同一链路）
    try:
        from core.xau_mindmap import llm_config
        conf = llm_config()
    except Exception:
        conf = {"api_key": os.environ.get("BAILIAN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or "",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3-max"}
    api_key = conf["api_key"]
    if not api_key:
        return {
            "code": 503,
            "msg": "未配置 BAILIAN_API_KEY / DASHSCOPE_API_KEY，无法生成 AI 行情观点。"
                   "（已返回客观盘面事实，不含任何观点，绝不瞎编）",
                "data": {
                    "mode": "no_key",
                    "facts": facts,
                    "facts_text": facts_txt,
                    "news_text": news_text,
                    "sources": sources,
                    "answer": None,
                    "latency_ms": int((time.time() - t0) * 1000),
                },
        }

    try:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=conf["base_url"])
        model = os.environ.get("BAILIAN_MARKET_MODEL") or conf["model"]   # 可用快模型单独覆盖
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_MARKET},
                {"role": "user", "content": USER_MARKET.format(
                    facts=facts_txt, rules=rules_txt, news=news_text,
                    question=question or "请分析当前  盘面并给出交易方案")},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        answer = (resp.choices[0].message.content or "").strip()
        mode = "llm"
    except Exception as e:
        LOG.warning("LLM 调用失败: %s", e)
        return {
            "code": 500, "msg": f"LLM 调用失败: {type(e).__name__}: {e}",
            "data": {"mode": "error", "facts": facts, "facts_text": facts_txt,
                     "news_text": news_text, "sources": sources, "answer": None,
                     "latency_ms": int((time.time() - t0) * 1000)},
        }

    return {
        "code": 200, "msg": "ok",
        "data": {"mode": mode, "answer": answer, "facts": facts,
                 "facts_text": facts_txt, "news_text": news_text, "sources": sources,
                 "model": model,
                 "latency_ms": int((time.time() - t0) * 1000)},
    }


if __name__ == "__main__":
    # 自检：用合成 K 线验证事实计算（不联网）
    import random
    random.seed(7)
    base = 4380.0
    kl = []
    for i in range(300):
        o = base + random.uniform(-8, 8)
        c = o + random.uniform(-9, 9)
        h = max(o, c) + random.uniform(0, 5)
        l = min(o, c) - random.uniform(0, 5)
        kl.append([i * 3600000, o, h, l, c, random.uniform(100, 900)])
        base = c

    def mock_fetch(url):
        return kl

    f = compute_facts(mock_fetch, with_stage=False)
    print("[自检] 合成 K 线事实计算：")
    print("  asof:", f["asof_bj"], "| 丢弃未收盘当根:", f["unclosed_bar_dropped"])
    for tf in ("4h", "1h"):
        d = f["tfs"].get(tf, {})
        print(f"  {tf}: close={d.get('close')} atr={d.get('atr14')} "
              f"ema20={d.get('ema20')} wm={d.get('wm')}")
    print("  4h POC:", f["tfs"].get("4h", {}).get("poc"))
    print("  levels:", f["levels"])
    print()
    print(format_facts(f)[:900])
