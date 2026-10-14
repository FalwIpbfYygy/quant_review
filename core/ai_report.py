"""
信号复盘 · AI 自然语言复盘报告（新增模块，不改动原有代码）

调用阿里云百炼（通义千问，兼容 OpenAI 接口）基于回测结果生成中文复盘简报。
角色提示词定位：资深量化交易复盘分析师，长期研究贵金属()与加密货币(ETHUSDT 等)
的日内/波段策略回测，以「策略是否具备正期望(Edge)」为核心判断标准。
"""
from openai import OpenAI
from config import BAILIAN_API_KEY, BAILIAN_BASE_URL, BAILIAN_MODEL
import time as _time


# 富文本输出约束（用户要求：Markdown 渲染，支持加粗/标题/列表；复制时前端去除标记）
CLEAN_TEXT = (
    "\n要求：输出 Markdown 格式的中文复盘报告。使用 ## 标题分段、**加粗**标注关键结论与"
    "重要数字、- 列表罗列条目，增强可读性；保持条理清晰、只依据给定数据；"
    "不要使用代码框或表格，段落之间用空行分隔。"
)

# 超时与重试（针对 qwen3.8-27b：单次生成 90-300 秒是常态）
CLIENT_TIMEOUT = 600          # 客户端默认 10 分钟（覆盖老版 180）
STREAM_TIMEOUT = 900          # 流式请求再放宽到 15 分钟
MAX_STREAM_RETRIES = 2        # 超时类错误自动最多重试 2 次（共 3 轮）

SYSTEM_PROMPT = """你是一位资深的量化交易复盘分析师，长期专注于贵金属（）与加密货币（ETHUSDT 等）的日内与波段策略研究与历史回测评估。你给交易团队做每周复盘简报。

你的专业原则：
1. 只依据给定的数据说话，绝不虚构胜率、盈亏、期望值或任何未给出的数字；若某策略样本不足或数据缺失，明确说明"样本不足/数据缺失"，不要脑补。
2. 以"策略是否具备正期望（Edge）"为第一判断标准，而不是被某几笔的盈亏带节奏；期望值 EV(R) 为正才叫有 Edge。
3. 风险意识强：主动点出最大回撤、点差对薄止损的侵蚀、未平仓浮亏、连亏与穿仓风险，以及它们对账户生存的威胁。
4. 给可执行、具体的改进动作：哪些形态/架构应保留、哪些应剔除或收紧入场条件，止盈盈亏比（RR，即 TP 距离 / 止损距离）应设到多少最合理。
5. 语气专业、克制、直接，像对成熟交易团队讲话；不堆砌废话、不拍马屁、不喊口号。
6. 使用中文，条理清晰；可用 Markdown（**加粗**标重点、## 小标题分段、- 列表罗列）增强可读性，便于在网页中渲染为富文本；不要使用代码框或表格。
7. 必须专门分析「各策略在亚盘/欧盘/美盘时段的盈利差异」：结合给定数据指出哪些策略在哪个时段 Edge 最强、哪个时段最弱，并给出可行的时段适配建议（例如某形态只在欧盘有效、美盘需收紧入场或剔除）。时段归属标准已在数据中按北京时间标注，并区分夏令时/冬令时：夏令时（每年 3–11 月，欧美盘开盘提前 1 小时）为亚盘 08:00–15:00、欧盘 15:00–20:00、美盘 20:00–次日08:00；冬令时（每年 11 月–次年 3 月，延后 1 小时）为亚盘 08:00–16:00、欧盘 16:00–21:00、美盘 21:00–次日08:00。数据中的「亚盘/欧盘/美盘」标签已按回测区间所属季节自动切换，请直接使用这些标签，并在分析时明确当前处于夏令时还是冬令时，不要机械套用单一固定边界。"""


def _client(timeout=CLIENT_TIMEOUT):
    return OpenAI(api_key=BAILIAN_API_KEY, base_url=BAILIAN_BASE_URL,
                  timeout=timeout, max_retries=1)


def _session_mode_note(result):
    """根据回测区间的月份，提示当前处于夏令时还是冬令时，避免 AI 机械套用固定时段边界。

    与 backtest.classify_session 的 DST 口径保持一致（3–11 月夏令时、11–3 月冬令时）。
    """
    dr = result.get("data_range") or {}
    months = set()
    for s in (dr.get("start"), dr.get("end")):
        if not s:
            continue
        try:
            months.add(int(str(s)[:7].split("-")[1]))
        except Exception:
            pass
    if not months:
        return "（注：未识别到回测区间月份，时段划分以数据标签为准。）"
    has_dst = any(3 <= m <= 11 for m in months)
    has_winter = any(m <= 3 or m >= 11 for m in months)
    if has_dst and not has_winter:
        return ("（注：本回测区间处于夏令时——欧美盘开盘提前 1 小时，欧盘为 15:00 起、"
                "美盘 20:00 起；数据标签已据此自动切换，请直接引用这些标签。）")
    if has_winter and not has_dst:
        return ("（注：本回测区间处于冬令时——欧盘为 16:00 起、美盘 21:00 起；"
                "数据标签已据此自动切换，请直接引用这些标签。）")
    return "（注：本回测区间跨夏令时/冬令时，请按各笔信号实际月份区分，数据中的时段标签已自动切换。）"


def build_user_prompt(result):
    """把结构化回测结果拼成模型易读的纯文本。"""
    s = result.get("summary", {}) or {}
    lines = []
    lines.append("以下是一次历史信号回测的结果，请基于这些数据撰写一份复盘分析报告。")
    dr = result.get("data_range") or {}
    lines.append(f"回测区间：{dr.get('start','?')} ~ {dr.get('end','?')}（注：行情使用  1 分钟数据，PAXGUSDT 信号按黄金近似回测）。")
    lines.append(_session_mode_note(result))

    lines.append("【资金汇总】")
    lines.append(
        f"起始资金 {s.get('start_capital')}u，期末净值 {s.get('end_equity')}u，"
        f"总收益率 {s.get('total_return')}，最大回撤 {s.get('max_drawdown')}，"
        f"穿仓次数 {s.get('breach_count')}，已了结 {s.get('closed_count')} 笔 / 未平仓 {s.get('open_count')} 笔。"
    )

    lines.append("【策略统计（仅已了结交易，未平仓不计入）】")
    for st in result.get("strategy_stats", []):
        lines.append(
            f"- {st['pattern']}：笔数 {st['n']}，胜率 {st['win_rate']}，"
            f"平均RR {st['avg_rr']}，EV(R) {st['ev_r']}，盈利因子 {st['profit_factor']}，"
            f"总盈亏 {st['total_pnl']}u"
        )

    lines.append("【最优盈亏比建议（k = TP1 距入场 / 止损距离，扫描取 EV 最大）】")
    for b in result.get("best_rr", []):
        curve = "，".join(f"k={p['k']}:EV={p['ev']}" for p in b.get("curve", []))
        lines.append(f"- {b['pattern']}：建议 k={b.get('best_k')}（最佳EV={b.get('best_ev')}）；扫描 {curve}")

    lines.append("【各时段（亚/欧/美盘）整体盈利情况】")
    for ses in ("亚盘", "欧盘", "美盘"):
        d = (result.get("session_stats") or {}).get(ses)
        if not d or not d.get("n"):
            lines.append(f"- {ses}：无已了结交易")
            continue
        pf = d.get("profit_factor")
        pf_txt = "∞" if pf == 999 else (str(pf) if pf is not None else "—")
        lines.append(
            f"- {ses}：笔数 {d['n']}，胜率 {d['win_rate']}，"
            f"总盈亏 {d['total_pnl']}u，盈利因子 {pf_txt}"
        )

    lines.append("【各策略 × 时段盈利情况】")
    spb = result.get("session_by_pattern") or []
    if not spb:
        lines.append("- 暂无分时段策略统计")
    for sp in spb:
        pf = sp.get("profit_factor")
        pf_txt = "∞" if pf == 999 else (str(pf) if pf is not None else "—")
        lines.append(
            f"- {sp['pattern']} @ {sp['session']}：笔数 {sp['n']}，胜率 {sp['win_rate']}，"
            f"总盈亏 {sp['total_pnl']}u，盈利因子 {pf_txt}"
        )

    lines.append("【逐笔交割单】")
    for t in result.get("trades", []):
        sym = t.get("symbol") or ""
        if not t.get("closed"):
            lines.append(
                f"- {t['signal_time']} {sym} {t['interval']} {t['pattern']} {t['direction']} "
                f"入场{t['entry']}：未平仓（浮 {t.get('unrealized_final')}u）"
            )
        else:
            lines.append(
                f"- {t['signal_time']} {sym} {t['interval']} {t['pattern']} {t['direction']} "
                f"入场{t['entry']} → {t['result']}，盈亏 {t['pnl_u']}u（R={t['pnl_r']}）"
            )

    lines.append("")
    lines.append(
        "请输出以下五部分：1）总体评价（账户表现与主要问题）；2）每个策略的 Edge 判断与去留建议；"
        "3）最优盈亏比设置建议；4）主要风险与下一步改进动作；"
        "5）各策略在亚盘/欧盘/美盘时段的盈利差异分析（明确哪个时段 Edge 最强、哪个最弱，结合数据解释原因，并给出时段适配建议，如某形态只在欧盘有效、美盘应收紧或剔除）。"
    )
    return "\n".join(lines)


def generate_report(result, temperature=0.7):
    """返回纯文本复盘报告；异常时返回可读错误信息（不抛出）。"""
    try:
        client = _client(timeout=STREAM_TIMEOUT)  # 流式 / 非流式统一 15 分钟
        user = build_user_prompt(result)
        resp = client.chat.completions.create(
            model=BAILIAN_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user + CLEAN_TEXT},
            ],
            temperature=temperature,
            timeout=STREAM_TIMEOUT,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"[AI 生成失败] {type(e).__name__}: {e}"


def _stream_with_retry(messages, temperature=0.7):
    """流式生成器：按给定 messages 调 LLM，每次 yield 一个 delta 文本片段。

    - 单次连接 timeout=900s（适配 qwen3.8-27b 慢响应）
    - 仅对超时 / 连接错误自动最多 MAX_STREAM_RETRIES=2 次重试
    - 异常时 yield [AI 生成失败] ... 字符串
    """
    for attempt in range(MAX_STREAM_RETRIES + 1):
        client = None
        try:
            client = _client()  # 每次重试起新 client，避免旧 socket 卡住
            resp = client.chat.completions.create(
                model=BAILIAN_MODEL,
                messages=messages,
                temperature=temperature,
                stream=True,
                timeout=STREAM_TIMEOUT,
            )
            for chunk in resp:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None) if delta else None
                if content:
                    yield content
            return  # 正常完成
        except Exception as e:
            err_type = type(e).__name__
            err_msg = str(e)[:200]
            # 仅对超时 / 连接错误做自动重试
            is_transient = err_type in ("APITimeoutError", "APIConnectionError",
                                        "Timeout", "ConnectionError") \
                or "Timeout" in err_type or "timeout" in err_msg.lower()
            if is_transient and attempt < MAX_STREAM_RETRIES:
                print(f"[ai_report] 第 {attempt+1} 轮 {err_type}，将于 2s 后重试…")
                yield f"\n\n⏱ **连接超时，正在自动重试（{attempt+2}/{MAX_STREAM_RETRIES+1}）…**\n\n"
                _time.sleep(2)
                continue
            yield f"[AI 生成失败] {err_type}: {err_msg}"
            return


def stream_report(result, temperature=0.7):
    """
    流式生成器：每次 yield 一个 delta 文本片段（首份复盘报告）。
    """
    user = build_user_prompt(result)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user + CLEAN_TEXT},
    ]
    yield from _stream_with_retry(messages, temperature)


# ==================== 多轮对话支持（D1-D10） ====================

# 用户越权/注入指令过滤（D7）：剥离"忽略上文/重置/切换角色/你现在是"等越权话术
_OVERRIDE_PATTERNS = [
    "忽略", "无视", "忘掉", "忘记", "重置", "reset", "ignore", "forget",
    "忽略上文", "忽略上面", "忽略之前", "忽略前面", "忽略所有", "忽略以下", "忽略上述", "忽略指令",
    "切换角色", "你现在是", "你现在扮演", "假设你是", "从现在起你是", "重新设定", "重新设定你的",
    "system prompt", "系统提示", "开发者模式", "developer mode", "jailbreak", "越狱",
    "以上指令无效", "无视之前的", "disregard", "忽略你的设定", "忽略设定",
]

def filter_user_input(text):
    """前置过滤用户输入：剥离句首越权/注入话术，保留正文其余内容（D7）。

    命中多个前缀模式时取最长者剥离，避免短前缀（如"忽略"）残留"上文"等残余。
    """
    if not text:
        return ""
    t = text.strip()
    low = t.lower()
    matched = None
    for p in _OVERRIDE_PATTERNS:
        if low.startswith(p.lower()):
            if matched is None or len(p) > len(matched):
                matched = p
    if matched:
        rest = t[len(matched):].lstrip("，。,. ：: \n\t（(【[")
        print(f"[ai_report] 已过滤越权前缀: {matched}")
        return rest
    return t


def seed_messages(result):
    """构建首轮对话的完整 messages（含 system）。供 chat 重建复用（D3）。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(result) + CLEAN_TEXT},
    ]


def stream_chat(messages, temperature=0.7):
    """多轮对话流式生成：直接复用现有重试/超时逻辑（D2）。"""
    yield from _stream_with_retry(messages, temperature)


def generate_report_from_messages(messages, temperature=0.7):
    """多轮对话非流式生成（兜底端点用）。"""
    try:
        client = _client(timeout=STREAM_TIMEOUT)
        resp = client.chat.completions.create(
            model=BAILIAN_MODEL,
            messages=messages,
            temperature=temperature,
            timeout=STREAM_TIMEOUT,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"[AI 生成失败] {type(e).__name__}: {e}"


# 上下文截断阈值（D4）：保留 system + 首条 seed + 最近 N 轮
MAX_CONV_TURNS = 12  # 最近 12 轮 = 24 条 user/assistant


def truncate_conversation(turns):
    """turns 为不含 system 的 user/assistant 列表；超长则保留首条 seed + 最近 MAX_CONV_TURNS 轮。"""
    if len(turns) <= 1 + MAX_CONV_TURNS * 2:
        return turns
    return turns[:1] + turns[-(MAX_CONV_TURNS * 2):]


