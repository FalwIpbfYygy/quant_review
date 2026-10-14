# -*- coding: utf-8 -*-
"""
实时阶段闸门（ABCDEF）· AI 分析师报告生成

调用阿里云百炼（兼容 OpenAI 接口）基于结构化阶段判定，生成一份
「ABCDEF 阶段闸门 · 实时开仓决策报告」（Markdown）。

与 daily_report_ai.py 同款 LLM 链路（config.BAILIAN_MODEL）。
为稳健起见：LLM 不可用时自动回退到确定性模板报告（不编造任何数值）。
"""

from config import BAILIAN_API_KEY, BAILIAN_BASE_URL, BAILIAN_MODEL

CLIENT_TIMEOUT = 180
MAX_RETRIES = 1

SYSTEM_PROMPT = """你现在是拥有10年贵金属交易经验的资深分析师，精通黄金（）规则化信号体系与 ABCDEF 周期阶段模型，
熟悉 HTML 前端排版。请基于用户提供的「结构化阶段判定数据」生成一份「ABCDEF 阶段闸门 · 实时开仓决策报告」，输出 Markdown。

#### 前置要求
1. 所有判断严格依据用户提供的结构化数据：4H 阶段、1H 阶段、ATR 比率、4H 区间、决策结论（该不该开/用哪套/开多大/理由）。**不得编造任何点位或数值**，仅当某字段缺失时才做定性推演并标注「需以实时数据复核」。
2. 报告顶部必须置顶红色加粗风险提示：「⚠️ 重要风险提示：本报告仅为交易逻辑知识分享，不构成任何投资建议。现货黄金、外汇及合约交易属高风险产品，杠杆可能放大亏损，极端行情下存在本金全部亏损风险，请结合自身风险承受能力独立决策。」
3. 配色符合国内习惯：上涨用「↑ 红」、下跌用「↓ 绿」；关键结论用高亮。
4. 全篇中文，结构化分段清晰；不要用代码框。

#### 报告固定结构（严格按顺序）
##### 模块1：实时阶段快照
- 决策时点（北京时间）、 现价、4H 阶段（总开关，含防抖稳定阶段）、1H 阶段（微调，含防抖稳定阶段）、4H ATR 比率、4H 近120根区间、交易时段状态。

##### 模块2：开仓决策（核心）
- **该不该开**：明确「开 / 不开 / 停手」及依据（必须引用回测结论——4H=B 唯一稳健盈利、4H=D 显著亏损、A/E 为噪声或负 EV）。
- **用哪套策略**：给出具体策略集（core_code / ICT / Al_Brookss / high_winss 的子集）。
- **开多大**：明确仓位倍数与 1H 微调后的修正。

##### 模块3：阶段语义与行为纪律
- 用 2–3 句话解释当前 4H 阶段的语义，及该阶段下「该做/不该做」的动作清单。

##### 模块4：风险提示与下一步
- 当前最该警惕的陷阱（如 A 阶段反复止损、B 阶段一闪而过抓不住、E 阶段禁开顺势单等），以及下一根 4H K 线收盘后需重新判定的提示。"""


def _client(timeout=CLIENT_TIMEOUT):
    from openai import OpenAI
    return OpenAI(api_key=BAILIAN_API_KEY, base_url=BAILIAN_BASE_URL,
                  timeout=timeout, max_retries=1)


def _build_user(stage: dict) -> str:
    d = stage.get("decision", {})
    m = stage.get("metrics", {})
    lines = []
    lines.append("【结构化阶段判定数据】")
    lines.append(f"决策时点（北京）：{stage.get('time_bj')}")
    lines.append(f" 现价：{stage.get('price')}")
    lines.append(f"数据源：{stage.get('source')}")
    lines.append(f"4H 阶段（总开关）：{stage.get('stage_4h')}（防抖稳定：{stage.get('stage_4h_stable')}）")
    lines.append(f"1H 阶段（微调）：{stage.get('stage_1h')}（防抖稳定：{stage.get('stage_1h_stable')}）")
    lines.append(f"4H ATR 比率（ATR/ATR_ma60）：{m.get('atr_ratio_4h')}")
    lines.append(f"1H ATR 比率：{m.get('atr_ratio_1h')}")
    lines.append(f"4H 近120根区间：{m.get('range_4h')}")
    lines.append(f"交易时段状态：{m.get('session')}")
    lines.append("")
    lines.append("【开仓决策（由回测 + cluster bootstrap 得出）】")
    lines.append(f"该不该开：{d.get('open')}")
    lines.append(f"用哪套：{d.get('set')}")
    lines.append(f"开多大：{d.get('size')}")
    lines.append(f"理由：{d.get('why')}")
    lines.append("")
    lines.append("请严格按系统设定中的「报告固定结构（4 个模块）」输出 Markdown，"
                 "所有数值只能引用上方结构化数据，严禁编造未提供的点位。")
    return "\n".join(lines)


def template_report(stage: dict) -> str:
    """确定性模板兜底：LLM 不可用时仍产出高质量中文报告。"""
    d = stage.get("decision", {})
    m = stage.get("metrics", {})
    s4, s4s = stage.get("stage_4h"), stage.get("stage_4h_stable")
    s1, s1s = stage.get("stage_1h"), stage.get("stage_1h_stable")
    price = stage.get("price")
    t = stage.get("time_bj", "")
    SEM = {
        "A": "A 震荡均衡｜均值回归优先：箱体运动，反复测试高低点，突破前不追。",
        "B": "B 突破转换｜突破策略：结构刚被打破，动量最强但窗口极短（平均仅 7.8 小时）。",
        "C": "C 稳定趋势｜趋势跟随：斜率温和的单边，适合回踩顺势。",
        "D": "D 加速趋势｜回踩续趋势：斜率陡峭，已脱离成本区，追单风险大、且回测显著亏损。",
        "E": "E 冲顶/冲底失稳｜减仓，禁止新开顺势单：长上/下影线频现，顶部/底部结构松动。",
        "F": "F 高波动修正｜等突破确认，禁止猜顶抄底：ATR 放大，方向未明。",
    }
    md = []
    md.append("## ABCDEF 阶段闸门 · 实时开仓决策报告\n")
    md.append("> ⚠️ **重要风险提示**：本报告仅为交易逻辑知识分享，不构成任何投资建议。"
              "现货黄金、外汇及合约交易属高风险产品，杠杆可能放大亏损，极端行情下存在本金全部亏损风险，"
              "请结合自身风险承受能力独立决策。\n")
    md.append("## 模块1：实时阶段快照\n")
    md.append(f"- **决策时点（北京时间）**：{t}")
    md.append(f"- ** 现价**：**{price}** USD/oz")
    md.append(f"- **4H 阶段（总开关）**：**{s4}**（防抖稳定：{s4s}）")
    md.append(f"- **1H 阶段（微调）**：**{s1}**（防抖稳定：{s1s}）")
    md.append(f"- **4H ATR 比率**：{m.get('atr_ratio_4h')}（<1.1 为低波动箱体，>1.2 为高波动）")
    md.append(f"- **1H ATR 比率**：{m.get('atr_ratio_1h')}")
    md.append(f"- **4H 近120根区间**：{m.get('range_4h')}")
    md.append(f"- **交易时段状态**：{m.get('session')}\n")
    md.append("## 模块2：开仓决策（核心）\n")
    md.append(f"- **该不该开**：**{d.get('open')}**")
    md.append(f"- **用哪套策略**：{d.get('set')}")
    md.append(f"- **开多大**：**{d.get('size')}**")
    md.append(f"- **理由**：{d.get('why')}\n")
    md.append("## 模块3：阶段语义与行为纪律\n")
    md.append(f"- 当前 4H 阶段语义：**{SEM.get(s4, s4)}**")
    md.append(f"- 该阶段下动作：**{d.get('open')}**；切忌把阶段当方向预测器——它只回答「该不该开、用哪套、开多大」。"
              "回测铁律：**只有 4H=B 稳健盈利（bootstrap P亏 0%），4H=D 显著亏损（P亏 99.2%），A/E 为噪声或负 EV**。"
              "1H 仅做加减仓微调、不当开关。\n")
    md.append("## 模块4：风险提示与下一步\n")
    if s4 == "A":
        md.append("- **当前陷阱**：A 占黄金 66% 时间，你的四套策略在 A 阶段裸亏（口径B −4,522），是反复止损的主因；"
                  "别在箱体里硬做突破。")
    elif s4 == "D":
        md.append("- **当前陷阱**：D 阶段加速趋势看似好做，实则是回测唯一显著亏损阶段，追单必吃大止损。")
    elif s4 == "B":
        md.append("- **当前陷阱**：B 一闪而过（平均 7.8 小时），宁可错过不要扛单；严格 SL，到点即走。")
    elif s4 == "E":
        md.append("- **当前陷阱**：E 阶段长影线频现、顶部松动，禁开顺势单，只减仓不平反向加。")
    else:
        md.append("- **当前陷阱**：该阶段样本极少/标定不足，先观察不急着下重注。")
    md.append(f"- **下一步**：阶段标签是 4H K 线**收盘后**才确定的（最多 4 小时滞后），"
              f"下一根 4H 收盘（约 {t} 后）需重新判定；若 4H 切到 B 再考虑开仓，切到 D/F 立即停手。")
    return "\n".join(md)


def generate(stage: dict, model: str = None, temperature: float = 0.5):
    """返回 Markdown 报告；LLM 异常时回退确定性模板。"""
    user = _build_user(stage)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    mdl = model or BAILIAN_MODEL
    try:
        from openai import OpenAI  # 懒加载：缺包时直接走模板兜底
    except Exception:
        return template_report(stage)
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=mdl, messages=messages, temperature=temperature, timeout=CLIENT_TIMEOUT)
        return resp.choices[0].message.content
    except Exception as e:
        # LLM 不可用 → 确定性模板兜底（不编造数值，保证页面永远有可读报告）
        return template_report(stage)
