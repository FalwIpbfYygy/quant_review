# -*- coding: utf-8 -*-
"""
金十数据 MCP 代理模块（新增，不改动既有 main.py 运行逻辑）

职责：在 quant_review 后端维护一个持久的金十 MCP 会话，把行情 / 本周财经
日历（含利多利空判向）/ 分主题快讯，封装成本地可调用的方法，供 main.py
代理 API 与前端「每日交易」页使用。

协议要点（实测确认，2026-09）：
- 金十 MCP 为流式 POST(SSE) 接口 ，鉴权 Bearer token。
- 服务端【不】返回 Mcp-Session-Id 头、也不用 Cookie，但仍要求
  initialize → notifications/initialized → tools/call 在【同一个 requests.Session】
  内顺序完成；跨连接直接调工具会报 "JSON RPC not handled: unsupported"。
  因此本模块复用单例 Session + threading.Lock，确保顺序与并发安全。
- tools/call 返回 result.content[0].text（JSON 字符串），但通常同时给
  result.structuredContent（结构化 dict），优先取后者，缺省再解析 text。

缓存：行情 30s，日历 10min（本周数据变化不频繁）。外部失败自动回退缓存。
"""
import os
import json
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

# ── 金十 MCP 配置 ──
# 凭据 / 端点来自 config（环境变量），源码不再硬编码。
from config import JIN10_URL, JIN10_TOKEN
JIN10_PROTOCOL = "2025-11-25"

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jin10_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 行情品种中文名
CODE_NAMES = {
    "": "现货黄金", "XAGUSD": "现货白银", "USOIL": "WTI原油",
    "UKOIL": "布伦特", "EURUSD": "欧元/美元", "USDJPY": "美元/日元",
    "USDCNH": "美元/离岸人民币",
}

# 主题快讯关键词
TOPIC_KEYWORDS = [
    ("gold", "黄金"), ("oil", "原油"), ("fed", "美联储"),
    ("usd", "美元"), ("geo", "地缘"), ("us", "美股"),
]

# ══════════════════════════════════════════════════════════════
# 黄金消息面（ 强相关基本面监控）配置
# ══════════════════════════════════════════════════════════════
# 高精度主搜索词：命中即与黄金高度相关，直接收录对应行
GOLD_PRECISE_WORDS = [
    "黄金", "金价", "现货黄金", "黄金ETF", "央行购金", "金价冲", "金价回落",
    "CPI", "非农", "失业率", "初请", "PCE", "核心PCE",
    "鲍威尔", "沃勒", "降息", "加息",
]
# 宽泛触发词：命中后，所在行还须再命中 GOLD_DRIVERS 才收录（避免次级关联噪声）
GOLD_BROAD_WORDS = [
    "美联储", "利率决议", "特朗普", "美元指数", "中东", "伊朗", "避险",
    "关税", "点阵图", "通胀",
]
# 黄金驱动强相关词：某行必须命中其一，才认为与  相关（对宽泛词生效）
GOLD_DRIVERS = [
    "黄金", "金价", "XAU", "现货金", "黄金ETF", "央行购金", "避险", "金饰",
    "美元", "美元指数", "美指",
    "美联储", "联储", "利率", "降息", "加息", "点阵图", "缩表", "QT", "QE",
    "鲍威尔", "沃勒", "哈马克", "古尔斯比",
    "CPI", "通胀", "PPI", "PCE", "初请", "非农", "失业率", "就业",
    "关税", "贸易战",
    "中东", "伊朗", "地缘", "冲突", "导弹", "核", "避险资产", "黎巴嫩", "加沙",
]
# 黄金核心锚点：收录的每一行至少命中其一，才真正与  基本面相关
GOLD_ANCHOR = [
    # 贵金属本体
    "黄金", "金价", "现货金", "现货黄金", "黄金ETF", "央行购金", "金饰", "金银",
    # 美元与利率（直接定价 ）
    "美元指数", "美元走", "美元兑", "美元下", "美元上", "美指",
    "美联储", "联储", "利率决议", "降息", "加息", "点阵图", "缩表", "QT",
    # 美联储官员
    "鲍威尔", "沃勒", "哈马克", "古尔斯比",
    # 美国核心宏观（公布即动金价）
    "CPI", "PPI", "PCE", "通胀", "初请", "非农", "失业率", "美债收益率",
    # 避险地缘
    "避险", "中东", "伊朗", "地缘", "冲突升级",
]
# 明确无关内容过滤（命中即剔除该行）
GOLD_NOISE = [
    "国内新闻", "国际新闻", "A股", "上证", "深证", "创业板",
    "港股", "科创板", "医保", "楼市", "房价", "楼价", "购房",
    "大豆", "玉米", "小麦", "豆粕",
    "原油进口", "俄罗斯制裁", "官方售价", "OPEC", "欧佩克",
    "LME铝", "铜价", "铝价", "镍", "锡", "精炼铜",
    "ETF溢价", "基金提示", "停牌", "LOF", "跨境ETF", "纳斯达克ETF",
    "纳指", "标普", "道指", "半导体ETF", "芯片LOF", "国家中小企业发展基金",
    "十部门", "上交所", "深交所", "工信部", "国务院", "发改委",
    "医保国谈", "海关总署", "商务部回应",
]

# 缓存 TTL（秒）
TTL = {"quotes": 30, "calendar": 600, "flash": 300, "gold_news": 240}

_lock = threading.Lock()          # 保护对 MCP session 的所有访问（顺序 + 并发）
_refresh_lock = threading.Lock()  # 保护缓存写
_cache = {k: {"ts": 0, "data": None, "err": None} for k in TTL}

_session = None                   # 单例 requests.Session（保存服务端会话状态）
_session_ok = False


# ══════════════════════════════════════════════════════════════
# 底层 MCP 通信
# ══════════════════════════════════════════════════════════════
def _new_session() -> requests.Session:
    s = requests.Session()
    return s


def _post_headers():
    return {
        "Authorization": f"Bearer {JIN10_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _post_plain(s: requests.Session, payload: dict, timeout: int = 40):
    """仅发送并读取原始文本（不要求解析出 result）。用于 notifications/initialized。"""
    r = s.post(JIN10_URL, json=payload, headers=_post_headers(), timeout=timeout, stream=True)
    r.raise_for_status()
    for _chunk in r.iter_content(chunk_size=None):
        pass  # 消费完 body，释放连接
    return None


def _post(s: requests.Session, payload: dict, timeout: int = 40):
    headers = _post_headers()
    r = s.post(JIN10_URL, json=payload, headers=headers, timeout=timeout, stream=True)
    r.raise_for_status()
    raw = "".join(chunk.decode("utf-8", "replace") for chunk in r.iter_content(chunk_size=None))
    # 解析 SSE：取 jsonrpc 对象（首个带 id 且含 result/error 的）
    for block in raw.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                    return obj
    raise Exception(f"金十无有效响应: {raw[:200]}")


def _ensure_session():
    """在锁内确保已握手，返回就绪 session。"""
    global _session, _session_ok
    if _session is not None and _session_ok:
        return _session
    s = _new_session()
    # 1 initialize
    init = _post(s, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": JIN10_PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "kline-review", "version": "1.0"},
        },
    })
    if "error" in init:
        raise Exception(f"金十 initialize 失败: {init['error']}")
    # 2 initialized 通知（无响应体，只发送）
    _post_plain(s, {"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10)
    _session = s
    _session_ok = True
    return s


def _call_tool(name: str, arguments: dict = None) -> dict:
    """调用一个工具，返回其 data 结构（已解包 structuredContent / content.text）。"""
    global _session_ok
    with _lock:
        for attempt in range(2):
            try:
                s = _ensure_session()
                req = {
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                }
                obj = _post(s, req)
                if "error" in obj:
                    raise Exception(f"金十 {name} 错误: {obj['error']}")
                result = obj.get("result", {})
                # 优先 structuredContent
                sc = result.get("structuredContent")
                if isinstance(sc, dict):
                    return sc.get("data", sc) if "data" in sc else sc
                # 否则解析 content[0].text
                content = result.get("content") or []
                if content and isinstance(content[0], dict):
                    txt = content[0].get("text", "")
                    try:
                        parsed = json.loads(txt)
                        if isinstance(parsed, dict):
                            return parsed.get("data", parsed)
                        return parsed
                    except json.JSONDecodeError:
                        return {"raw": txt}
                return result
            except requests.ConnectionError:
                # 会话可能失效，强制重握手一次
                _session_ok = False
                _session = None
                if attempt == 0:
                    continue
                raise
            except Exception:
                raise


# ══════════════════════════════════════════════════════════════
# 业务方法（带本地缓存）
# ══════════════════════════════════════════════════════════════
def _now():
    return datetime.utcnow() + timedelta(hours=8)  # 北京时间


def get_quotes(codes: Optional[List[str]] = None) -> dict:
    """批量取行情。返回 {code: {...quote}}。"""
    codes = codes or ["", "XAGUSD", "USOIL", "UKOIL", "EURUSD", "USDJPY"]
    out = {}
    for code in codes:
        try:
            q = _call_tool("get_quote", {"code": code})
            if isinstance(q, dict) and q.get("close") is not None:
                q["code"] = code
                q.setdefault("name", CODE_NAMES.get(code, code))
                out[code] = q
        except Exception as e:
            _set_err("quotes", f"{code}:{type(e).__name__}:{str(e)[:80]}")
    _set_ok("quotes", out)
    return out


def get_calendar_week() -> List[dict]:
    """本周（周一~周日）财经日历，含 affect_txt 利多/利空判向与星级。"""
    try:
        data = _call_tool("list_calendar", {})
        if not isinstance(data, list):
            data = []
        # 保证字段
        for r in data:
            r.setdefault("affect_txt", "")
            r.setdefault("star", 0)
        _set_ok("calendar", data)
        return data
    except Exception as e:
        _set_err("calendar", f"{type(e).__name__}:{str(e)[:120]}")
        return []


def search_flash_topics(keywords: Optional[List[tuple]] = None) -> Dict[str, list]:
    """按主题关键词搜索快讯。返回 {topic_key: [item...]}。

    search_flash 返回 {items:[...]}，每条 item 的 content 可能是「国内/国际多条
    合一段」的大文本块；为便于前端展示，这里保留原样并限制条数。
    """
    topics = keywords or TOPIC_KEYWORDS
    out = {}
    for key, kw in topics:
        try:
            data = _call_tool("search_flash", {"keyword": kw})
            if isinstance(data, dict) and "items" in data:
                items = data["items"]
            elif isinstance(data, list):
                items = data
            else:
                items = []
            out[key] = items[:8]
        except Exception:
            out[key] = []
    _set_ok("flash", out)
    return out


# ══════════════════════════════════════════════════════════════
# 黄金消息面： 强相关基本面监控
# ══════════════════════════════════════════════════════════════
def _parse_item_time(t_str: str):
    """解析金十时间(带时区)，失败回退 None。"""
    if not t_str:
        return None
    try:
        ts = t_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        try:
            return datetime.strptime(str(t_str)[:16], "%Y-%m-%d %H:%M")
        except Exception:
            return None


def _clean_line(raw: str) -> str:
    """清洗单行：去序号前缀、金十冒号冗余、空白。"""
    s = raw.strip()
    # 去 "1. " "② " "①" 等序号
    import re
    s = re.sub(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]+\s*", "", s)
    s = re.sub(r"^\s*\d+[\.、]\s*", "", s)
    # 去掉金十数据原文的尾缀（"金十数据X月X日讯" 保留，因含时效），仅清多余空白
    s = re.sub(r"\s+", " ", s).strip()
    # 去掉"金十数据X月X日讯，"冗余前缀中的多余（保留正文），只压缩
    return s.strip(" 。；;,")


def _line_relevant(line: str) -> bool:
    """强过滤：命中任一 GOLD_DRIVERS 且不含 GOLD_NOISE，判为与  相关。"""
    if not line or len(line) < 6:
        return False
    if any(n in line for n in GOLD_NOISE):
        return False
    return any(d in line for d in GOLD_DRIVERS)


def _classify_gold_line(line: str) -> str:
    """给黄金消息面条目打类型标签。"""
    if any(w in line for w in ["特朗普", "鲍威尔", "沃勒", "哈马克", "古尔斯比", "讲话", "发言", "表态", "称 ", "表示"]):
        return "讲话"
    if any(w in line for w in ["CPI", "通胀", "PPI", "PCE", "初请", "非农", "失业率", "就业", "零售", "PMI", "GDP", "数据"]):
        return "数据"
    if any(w in line for w in ["降息", "加息", "利率", "美联储", "联储", "点阵图", "决议", "缩表"]):
        return "货币"
    if any(w in line for w in ["中东", "伊朗", "地缘", "冲突", "导弹", "核", "黎巴嫩", "加沙", "避险"]):
        return "地缘"
    if any(w in line for w in ["央行购金", "黄金ETF", "持仓", "实物金", "金饰", "黄金需求", "各国央行"]):
        return "央行"
    if any(w in line for w in ["金价", "现货金", "黄金", "XAU"]):
        return "市场"
    return "要闻"


def _gold_affect(line: str) -> str:
    """粗判利多/利空（供展示，非权威）。返回 利多/利空/中性/空。"""
    bull = ["避险", "降息", "央行购金", "黄金ETF增持", "地缘", "冲突", "核", "导弹",
            "通胀走高", "通胀上升", "CPI超预期", "加息预期降温", "金价上涨", "上行",
            "利多", "关税升级", "美元走弱", "美元下跌"]
    bear = ["加息", "缩表", "鹰派", "黄金ETF减持", "持仓减少", "美元走强", "美元上涨",
            "美债收益率上升", "金价下跌", "下行", "利空", "风险偏好回升", "通胀回落", "CPI不及预期"]
    has_bull = any(b in line for b in bull)
    has_bear = any(b in line for b in bear)
    if has_bull and not has_bear:
        return "利多"
    if has_bear and not has_bull:
        return "利空"
    return "中性"


# 本周日历标题中，直接影响黄金的强相关事件词（用于抽取出高影响数据事件）
_CAL_GOLD_WORDS = ["CPI", "非农", "失业率", "初请", "PCE", "PPI", "利率决议",
                   "美联储", "零售销售", "就业", "通胀", "ISM", "密歇根",
                   "房屋", "贸易帐", "耐用品", "工业产出"]


def _is_cal_gold_relevant(title: str) -> bool:
    """判断日历事件标题是否影响黄金（美国/欧元区核心宏观 + 央行）。"""
    return any(w in title for w in _CAL_GOLD_WORDS)


def get_gold_fundamentals(force: bool = False) -> dict:
    """聚合黄金消息面。

    高精度词(CPI/非农/鲍威尔/黄金/降息等)命中→直接收；宽泛词(美联储/特朗普/美元/中东/
    关税等)命中→该行还须命中 GOLD_DRIVERS 才收。最终拆行→清洗→去重→时间倒序。

    返回:
      {
        "events": [ {time, ts, title, content, type, affect, group, url} ...] 按时间倒序
        "data_events": [ ... ] 本周黄金相关高影响日历事件
        "fetched_at", "err"
      }
    """
    # 1) 拉取全部搜索词命中
    raw_map = {}  # content 前60字 -> {time, content, via_broad(bool)}
    def _ingest(kw, broad):
        try:
            data = _call_tool("search_flash", {"keyword": kw})
            items = data.get("items", []) if isinstance(data, dict) else data
        except Exception:
            items = []
        for it in (items or []):
            c = (it.get("content", "") or "").strip()
            if not c:
                continue
            key = it.get("url") or c[:60]
            # 已存在则保留（高精度命中优先，宽泛不覆盖）
            if key in raw_map and not broad:
                raw_map[key] = {"time": it.get("time", ""), "content": c, "broad": False}
            elif key not in raw_map:
                raw_map[key] = {"time": it.get("time", ""), "content": c, "broad": broad}

    for kw in GOLD_PRECISE_WORDS:
        _ingest(kw, broad=False)
    for kw in GOLD_BROAD_WORDS:
        _ingest(kw, broad=True)

    # 2) 拆行清洗过滤
    seen = set()
    events = []
    for key, blk in raw_map.items():
        content = blk["content"]
        t_raw = blk["time"]
        for ln in content.split("\n"):
            cleaned = _clean_line(ln)
            if not cleaned or len(cleaned) < 8:
                continue
            # 噪声剔除（优先级最高）
            if any(n in cleaned for n in GOLD_NOISE):
                continue
            # 黄金锚点门槛：收录的每一行必须真正含  相关锚点词，
            # 避免宽泛词(美联储/特朗普/美元/中东)搜索带进来的次级关联噪声。
            if not any(a in cleaned for a in GOLD_ANCHOR):
                continue
            # "今日重点关注/财经日历"纯预告类，若不含美国黄金锚点则跳过
            if cleaned.startswith(("今日重点", "财经日历")) or "重点关注的财经数据" in cleaned:
                if "美国" not in cleaned and "黄金" not in cleaned:
                    continue
            dedupe = cleaned[:30]
            if dedupe in seen:
                continue
            seen.add(dedupe)
            events.append({
                "time": t_raw,
                "ts": _parse_item_time(t_raw),
                "title": cleaned[:80] + ("…" if len(cleaned) > 80 else ""),
                "content": cleaned,
                "type": _classify_gold_line(cleaned),
                "affect": _gold_affect(cleaned),
            })

    # 3) 时间倒序（无时间的放最后）
    def _ek(e):
        return e["ts"].timestamp() if e["ts"] else 0
    events.sort(key=_ek, reverse=True)
    # 上限 260 条，避免一次性渲染过大
    events = events[:260]

    # 4) 从本周日历抽取黄金高影响数据事件
    data_events = []
    try:
        cal = get_calendar_week()
        for r in cal:
            if _is_cal_gold_relevant(r.get("title", "")) and (r.get("star") or 0) >= 1:
                title = r.get("title", "")
                data_events.append({
                    "title": title,
                    "pub_time": r.get("pub_time", ""),
                    "star": r.get("star") or 0,
                    "affect_txt": r.get("affect_txt", "") or "",
                    "actual": r.get("actual"),
                    "consensus": r.get("consensus"),
                    "previous": r.get("previous"),
                    # 美国/美元驱动事件对  影响最直接，置顶优先级高
                    "us": any(u in title for u in ["美国", "美联储", "美元"]),
                })
        def _dk(d):
            try:
                return datetime.strptime(str(d["pub_time"])[:16], "%Y-%m-%d %H:%M").timestamp()
            except Exception:
                return 0
        # 先按是否美国置顶，再按时间倒序（离现在最近的美国数据优先）
        data_events.sort(key=lambda d: (d["us"], _dk(d)), reverse=True)
    except Exception:
        data_events = []

    payload = {
        "events": events,
        "data_events": data_events,
        "fetched_at": datetime.now().astimezone(timezone(timedelta(hours=8))).isoformat(),
        "err": None,
    }
    _set_ok("gold_news", payload)
    return payload


# ── 缓存读写 ──
def _set_ok(key, data):
    with _refresh_lock:
        _cache[key]["ts"] = int(time.time())
        _cache[key]["data"] = data
        _cache[key]["err"] = None
        _save(key, data)


def _set_err(key, err):
    with _refresh_lock:
        _cache[key]["err"] = err
        # 保留旧数据，供 stale 回退


def _save(key, data):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()), "data": data}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _load_cache(key):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ── 对外便捷读取（main.py / 前端用） ──
def snapshot_quotes(codes=None):
    codes = codes or ["", "XAGUSD", "USOIL", "UKOIL", "EURUSD", "USDJPY"]
    with _lock:
        c = dict(_cache["quotes"])
    fresh = int(time.time()) - c["ts"] < TTL["quotes"]
    if fresh and c["data"]:
        # 只返回请求的子集
        return {k: v for k, v in c["data"].items() if k in codes}
    data = get_quotes(codes)
    return data


def snapshot_calendar():
    with _lock:
        c = dict(_cache["calendar"])
    fresh = int(time.time()) - c["ts"] < TTL["calendar"]
    if fresh and c["data"]:
        return {"data": c["data"], "stale": False, "ts": c["ts"], "err": None}
    data = get_calendar_week()
    return {"data": data, "stale": bool(c["err"]), "ts": c["ts"], "err": c.get("err")}


def snapshot_flash():
    with _lock:
        c = dict(_cache["flash"])
    fresh = int(time.time()) - c["ts"] < TTL["flash"]
    if fresh and c["data"]:
        return {"data": c["data"], "stale": False, "ts": c["ts"], "err": None}
    data = search_flash_topics()
    return {"data": data, "stale": bool(c["err"]), "ts": c["ts"], "err": c.get("err")}


def snapshot_gold_news(force: bool = False):
    with _lock:
        c = dict(_cache["gold_news"])
    fresh = (not force) and (int(time.time()) - c["ts"] < TTL["gold_news"])
    if fresh and c["data"]:
        snap = dict(c["data"])
        snap.setdefault("stale", False)
        return snap
    data = get_gold_fundamentals(force=force)
    data.setdefault("stale", bool(c["err"]))
    return data
