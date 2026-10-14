# -*- coding: utf-8 -*-
"""
每日交易计划 · AI 分析师报告生成（新增模块，不改动原有代码）

调用阿里云百炼（通义千问，兼容 OpenAI 接口）基于当日结构化行情与突破跟随计划，
生成一份「 每日交易计划报告」（Markdown）。

数据源：
-  5m K线：价格接口基址 BINANCE_FAPI_BASE（经 main.py 注入的 PROXIES + requests，与 /realtime 同链路）
- 美元指数 DXY / 非美交叉盘 EURUSD·GBPUSD·AUDUSD：TwelveData（见 xau_macro.py，
  复用参考项目 D:/shit/TRAE/ICT 的 ICE 合成方案）

设计约束（与用户要求一致）：
1. 本服务 LLM 走私有业务空间网关，**无联网检索能力**，只能依据下方「结构化行情数据」分析。
2. 现已接入真实 DXY / EURUSD / GBPUSD / AUDUSD 数值 —— 模型**优先使用这些真实数据**；
   仅当某维度数据因限流/失败而缺失(None)时，才基于  结构推演并标注「需以实时数据复核」，
   严禁编造未提供的具体数值。
3. 输出 Markdown：## 标题分段、**加粗**关键价位与结论、- 短列表；上涨用「↑ 红」、下跌用「↓ 绿」。
4. 大模型选型：config.BAILIAN_MODEL（"qwen3.7-max-2026-06-08"）。
"""

from openai import OpenAI
from config import BAILIAN_API_KEY, BAILIAN_BASE_URL, BAILIAN_MODEL

CLIENT_TIMEOUT = 600          # 单次生成最长等待（秒）
MAX_RETRIES = 2              # 仅对超时/连接错误自动重试

SYSTEM_PROMPT = """你现在是拥有10年贵金属交易经验的资深分析师，专注于（现货黄金）交易策略研究，熟悉黄金与美元指数、主流非美货币交叉盘的联动规律，同时掌握HTML前端排版技能。请为我生成一份「每日交易计划报告」，输出为 Markdown 格式（标题用 ## 、关键价位与结论用 **加粗**、条目用 - 短列表）。

#### 前置要求
1. 你**可以**直接使用用户在「结构化行情数据」中提供的真实数值——包括  最新价、ATR、PDH/PDL、摆动高低、偏置(bias)，以及美元指数 DXY、EUR/USD、GBP/USD、AUD/USD 的最新值与 24 小时涨跌幅。对这些已提供具体数值的维度，直接引用、深入分析，不要推演。仅当某个品种标注为「数据暂不可用」(None) 时，才基于  已给结构做逻辑推演，并明确标注「需以实时数据复核」，严禁编造任何未提供的点位或数值。
2. 报告顶部必须置顶醒目的风险提示模块，用红色加粗标注：「⚠️ 重要风险提示：本报告仅为交易逻辑知识分享，不构成任何投资建议，现货黄金、外汇交易属于高风险金融产品，杠杆交易可能放大亏损，极端行情下存在本金全部亏损的风险，请投资者结合自身风险承受能力独立决策，入市前请充分了解产品规则。」
3. 整体配色符合国内交易习惯：上涨用红色、下跌用绿色，关键交易信号、核心价位用高亮色块标注（Markdown 中用「↑ 红」标注关键阻力位、「↓ 绿」标注关键支撑位），页面响应式适配手机和PC端，结构清晰易读。

#### 报告固定结构（必须严格按此顺序输出）
##### 模块1：基础信息栏
包含：报告日期、最新参考价、前24小时涨跌幅、当日核心驱动标签（如「美联储降息预期升温」「地缘风险升级」「美元指数走弱」「交叉盘背离信号」等，必须来自数据）。

##### 模块2：隔夜市场回顾
1. 美元指数（DXY）前一日走势总结、核心驱动因素（**必须基于提供的真实 DXY 值与 24h 涨跌幅**）；
2. 与联动性最高的3类资产表现：① 美元直盘（EUR/USD、GBP/USD等）；② 商品货币直盘（AUD/USD、CAD/USD、NZD/USD）；③ 核心交叉盘（AUD/JPY、USD/JPY、EUR/AUD等），**基于提供的真实 EUR/USD、GBP/USD、AUD/USD 数值**明确标注各资产与的走势匹配度，是否存在背离；
3. 前一日影响黄金走势的核心事件（如美元走强/走弱、地缘事件等）的影响复盘（基于真实数据，不虚构未公布的事件）。

##### 模块3：核心逻辑研判（重点模块，需详细撰写）
1. 基本面维度：当日及近期影响金价的核心因素（美联储政策、美元强弱、地缘风险、全球通胀等）的利多/利空权重排序，**必须结合真实 DXY 与交叉盘数值**；
2. 技术面维度：日线、4小时、1小时级别的趋势判断、核心指标（ATR、PDH/PDL、偏置 bias）信号、关键支撑阻力位；
3. 【-美元-交叉盘联动分析（必须包含）】：明确当前美元指数的强弱（由真实 DXY 值判定），对应商品货币、日元等避险货币的走势预判，验证黄金走势与美元、交叉盘的常规联动逻辑是否成立，若存在背离需分析背离原因，同时给出交叉盘走势对交易的辅助信号（如商品货币走强+黄金滞涨，需警惕美元外的利空压制金价）。

##### 模块4：当日具体交易计划（必须具体可执行，禁止空泛表述）
1. 日内趋势判断：明确为多头趋势、空头趋势还是区间震荡，及对应依据（结合 PDH/PDL 突破状态与 bias）；
2. 关键价位清单：标注3个核心阻力位（↑ 红）、3个核心支撑位（↓ 绿），明确每个价位的触发逻辑（技术面阻力/事件触发位）；
3. 入场策略：分场景给出具体交易方案（突破 PDH 做多 / 跌破 PDL 做空），包括入场条件、入场方向、**止损点位**、**止盈点位**、**建议仓位占比**（单笔不超过总资金 2%，具体参考提供的 lots 手数）；
4. 特殊场景预案：如重要经济数据公布前的仓位调整建议、极端波动下的应对方案（基于「周末薄盘 / 区间过窄 / 数据滞后」等预警标签给出具体动作）。

##### 模块5：关联标的参考
给出与联动性最高的3个交叉盘（如AUD/JPY、EUR/AUD、USD/CHF，可结合提供的 EUR/USD、GBP/USD、AUD/USD 真实数值衍生）的当日关键价位、走势预期，作为对冲交易或联动验证的参考。

#### 约束条件
1. 所有数据、事件需符合用户提供的结构化信息；未提供具体数值且数据不可用的维度不得虚构。
2. 分析逻辑需符合黄金与美元的负相关规律、交叉盘走势为两种货币兑美元强弱叠加的基本规律，不得出现逻辑硬伤。
3. 交易计划需具体到可执行的标准，禁止「逢低做多」「逢高做空」这类无条件的模糊表述。
4. 全篇使用中文，Markdown 分段清晰；不要使用代码框。
5. 若用户在【消息面（金十）】中提供了实时数据窗口与快讯，交易计划必须明确标注未来 24–72 小时内 ★≥3 数据时点（美联储决议/CPI/非农/初请等）的应对预案（数据前减仓 / 数据后顺势），并严格区分现货  与永续  的基差——所有交易点位一律采用「结构化行情数据」中的 ，**严禁把现货价与永续价混算**；未提供消息面时忽略本条，不得编造事件或数值。"""


def _client(timeout=CLIENT_TIMEOUT):
    return OpenAI(api_key=BAILIAN_API_KEY, base_url=BAILIAN_BASE_URL,
                  timeout=timeout, max_retries=1)


def _fmt(v, nd=2):
    if v is None:
        return "数据暂不可用"
    return f"{v:.{nd}f}"


def build_user_prompt(plan: dict, warns: list, macro: dict, source: str, asof_str: str,
                      news: dict = None) -> str:
    """把结构化行情 + 宏观数据 + 计划拼成模型易读的文本块。"""
    lines = []
    lines.append("【结构化行情数据】")
    lines.append(f"数据源：{source}")
    lines.append(f"决策时点(asof)：{asof_str}")
    lines.append(f" 最新参考价：{plan.get('cur')}")
    if plan.get('atr14') is not None:
        lines.append(f"ATR14(日)：{plan['atr14']}　ATR%：{plan.get('atrPct')}")
    lines.append(f"偏置(bias)：{plan.get('bias')}　现价距 PDH/PDL 中枢(ATR倍数)：{plan.get('distCurAtr')}")

    pd = plan.get("prev_day") or {}
    lines.append(f"前一交易日 {pd.get('day')}：开 {pd.get('open')} / 高(PDH) {pd.get('high')} / "
                 f"低(PDL) {pd.get('low')} / 收 {pd.get('close')}（外汇日切分：纽约17:00收市）")
    td = plan.get("today") or {}
    if td.get("open") is not None:
        lines.append(f"当日(截至asof)：开 {td.get('open')} / 高 {td.get('high')} / 低 {td.get('low')} / 收 {td.get('close')}")

    # 前 24h 涨跌幅（近似：现价 vs 前一日收盘）
    if plan.get("cur") is not None and pd.get("close"):
        chg = (plan["cur"] - pd["close"]) / pd["close"] * 100.0
        lines.append(f"前24小时涨跌幅(近似)：{chg:.2f}%")

    # 主计划 A / 备用 B
    p = plan.get("primary") or {}
    ps = plan.get("secondary") or {}
    lines.append("【主计划 A（突破跟随 PDH/PDL）】")
    if p:
        side_cn = "做多" if p.get("side") == "long" else ("做空" if p.get("side") == "short" else p.get("side"))
        lines.append(f"A 方向：{side_cn}　触发(突破价)：{p.get('trigger')}　止损：{p.get('stop')}"
                     f"（R={p.get('R')}）　TP1：{p.get('tp1')}(1.0R)　TP2：{p.get('tp2')}(1.8R)　建议仓位：{p.get('lots')} 手")
    else:
        lines.append(f"信号状态：{plan.get('reason')}（区间待突破 / 数据不足）")
    if ps:
        side_cn = "做多" if ps.get("side") == "long" else ("做空" if ps.get("side") == "short" else ps.get("side"))
        lines.append(f"B 方向（备选/反向）：{side_cn}　触发：{ps.get('trigger')}　说明：{ps.get('note')}")

    # 宏观：DXY + 交叉盘
    lines.append("【宏观数据：美元指数 DXY 与主要非美交叉盘（来自 TwelveData 真实数值）】")
    dxy = (macro or {}).get("dxy") or {}
    if dxy.get("cur") is not None:
        lines.append(f"美元指数 DXY 最新：{dxy['cur']}　前一日：{dxy.get('prev')}　24h涨跌幅：{dxy.get('chg24')}%")
    else:
        lines.append("美元指数 DXY：数据暂不可用（TwelveData 限流/失败），需以实时数据复核")
    fx = (macro or {}).get("fx") or {}
    for sym in ("EUR/USD", "GBP/USD", "AUD/USD"):
        d = fx.get(sym)
        if d and d.get("cur") is not None:
            lines.append(f"{sym} 最新：{d['cur']}　24h涨跌幅：{d.get('chg24')}%")
        else:
            lines.append(f"{sym}：数据暂不可用，需以实时数据复核")

    if warns:
        lines.append("【系统预警】")
        for w in warns:
            if isinstance(w, dict):
                lines.append(f"- [{w.get('t')}] {w.get('m')}")
            else:
                lines.append(f"- {w}")

    lines.append("")
    # 消息面（金十），与 /mindmap 同一聚合模块（xau_news.compute_news_facts）
    if news and news.get("text"):
        lines.append("【消息面（金十）】")
        lines.append(news["text"])
        lines.append("（注：金十为现货 ，Binance 为永续 ，存在基差；点位一律采用上方结构化行情数据，"
                     "勿混用现货价；数据已公布/待公布以时间戳为准，不得编造）")
        lines.append("")
    lines.append("请严格按照系统设定中的「报告固定结构（5 个模块）」输出 Markdown 报告，"
                 "所有具体数值只能引用上方结构化数据；交叉盘维度优先使用真实 EUR/USD、GBP/USD、AUD/USD 数值，"
                 "仅数据不可用处才推演并标注「需以实时数据复核」。")
    return "\n".join(lines)


def generate(plan: dict, warns: list, macro: dict, source: str = "", asof_str: str = "",
             model: str = None, temperature: float = 0.6, news: dict = None):
    """返回 Markdown 报告字符串；异常时返回可读错误信息（不抛出）。"""
    user = build_user_prompt(plan, warns, macro, source, asof_str, news=news)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    mdl = model or BAILIAN_MODEL
    last_err = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            client = _client()
            resp = client.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=temperature,
                timeout=CLIENT_TIMEOUT,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:200])
            et = type(e).__name__
            transient = et in ("APITimeoutError", "APIConnectionError", "Timeout", "ConnectionError") \
                or "timeout" in et.lower() or "timeout" in last_err.lower()
            if transient and attempt < MAX_RETRIES:
                continue
            return "[AI 生成失败] %s" % last_err
    return "[AI 生成失败] %s" % last_err
