import os
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta
import asyncio
import json
import threading
import time
import uuid
from data.db import query_kline, MAX_ROWS
from config import TABLE_MAP, FAPI_KLINES, BINANCE_FAPI_BASE
from core.backtest import run_backtest
from data.binance_src import run_backtest_binance
from core.psych import add_record, list_records, delete_record, get_stats
from data.market import get_overview, get_trend, get_correlations
from data import jin10
from core import month_cal
from core import ai_report
from core import ai_store
from data import data_sync
from core import daily_plan

app = FastAPI(title="多周期四分屏K线复盘")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 本地静态资源（Vue / ECharts / marked / dompurify），避免依赖外部 CDN
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENDORS_DIR = os.path.join(_BASE_DIR, "vendors")
_STATIC_DIR  = os.path.join(_BASE_DIR, "static")
app.mount("/vendors", StaticFiles(directory=_VENDORS_DIR), name="vendors")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ==================== 多轮对话会话状态 ====================
# 进程内会话：chatId -> 完整 messages（含 system）。重启后从 ai_history.json 的 conversation 重建。
CHAT_SESSIONS = {}
CHAT_LOCK = threading.Lock()


# 旧记录（无 conversation，仅有 report）重建会话时的引导前缀
_REPORT_RESUME_PREFIX = "以下是已经生成的一份复盘报告（请据此回答用户的后续追问）：\n\n"


def _load_chat_messages(chat_id):
    """加载会话完整 messages（含 system）。

    - 内存会话优先；
    - 否则从 ai_history 的 conversation 重建；
    - 若 conversation 为空但存在 report，则用 report 重建最小会话，
      让「未追问过 / 旧报告」也能继续追问（修复追问入口为空的问题）。
    None 表示记录根本不存在。
    """
    if not chat_id:
        return None
    with CHAT_LOCK:
        if chat_id in CHAT_SESSIONS:
            return list(CHAT_SESSIONS[chat_id])
    rec = ai_store.get(chat_id)
    if not rec:
        return None
    conv = rec.get("conversation")
    if conv:
        return [{"role": "system", "content": ai_report.SYSTEM_PROMPT}] + list(conv)
    # 兼容旧记录：无 conversation，但有 report → 用 report 重建最小会话。
    # 以 report 本身作为首条 assistant 消息，前端 openDetail 用 c.slice(1) 展示时
    # 恰好等价于「report 作为首条 AI 消息」，前后端显示完全一致。
    report = rec.get("report") or ""
    if report:
        return [
            {"role": "system", "content": ai_report.SYSTEM_PROMPT},
            {"role": "user", "content": _REPORT_RESUME_PREFIX + report},
            {"role": "assistant", "content": report},
        ]
    return None


def _build_seed(payload):
    """首轮对话的 user seed（与 ai_report 保持一致）。"""
    return ai_report.build_user_prompt(payload) + ai_report.CLEAN_TEXT


def _register_session(chat_id, payload, assistant_text):
    """首轮报告完成后：建内存会话（含 system）+ 持久化 conversation（D1/D6/D10）。"""
    seed = _build_seed(payload)
    with CHAT_LOCK:
        CHAT_SESSIONS[chat_id] = [
            {"role": "system", "content": ai_report.SYSTEM_PROMPT},
            {"role": "user", "content": seed},
            {"role": "assistant", "content": assistant_text},
        ]
    conversation = [
        {"role": "user", "content": seed},
        {"role": "assistant", "content": assistant_text},
    ]
    try:
        ai_store.save(assistant_text, payload, conversation=conversation, rid=chat_id)
    except Exception as e:
        print(f"[ai_store] 会话保存失败: {e}")


def datetime_to_ts(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def parse_date_str(date_str: str):
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str, fmt)
        except:
            continue
    return None


async def run_query(table_name, start_ts, end_ts):
    return await asyncio.to_thread(query_kline, table_name, start_ts, end_ts)


@app.get("/")
async def index_page():
    return FileResponse("web/index.html")


@app.get("/replay")
async def replay_page():
    return FileResponse(
        "web/replay.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.post("/api/backtest")
async def backtest_api(payload: dict):
    signals = payload.get("signals", [])
    lot = float(payload.get("lot", 0.01))
    start_capital = float(payload.get("startCapital", 200))
    spread_pips = float(payload.get("spreadPips", 30))
    review_end = payload.get("reviewEnd")
    result = await asyncio.to_thread(
        run_backtest,
        signals, lot, start_capital, spread_pips, review_end,
    )
    return result


@app.post("/api/backtest/binance")
async def backtest_binance_api(payload: dict):
    """Binance 实时行情回测：拉取 fapi 1m K线（按 symbol 分组、复用 PROXIES、点差偏移修正），
    复用现有回测/统计/资金曲线/Ai 复盘链路，返回与 /api/backtest 相同 schema。"""
    signals = payload.get("signals", [])
    lot = float(payload.get("lot", 0.01))
    start_capital = float(payload.get("startCapital", 200))
    spread_pips = float(payload.get("spreadPips", 30))
    review_end = payload.get("reviewEnd")
    result = await asyncio.to_thread(
        run_backtest_binance,
        signals, lot, start_capital, spread_pips, review_end,
    )
    return result


@app.post("/api/ai/summary")
async def ai_summary_api(payload: dict):
    # 前端传入 /api/backtest 的完整结果，交由百炼生成中文复盘报告
    try:
        report = await asyncio.to_thread(ai_report.generate_report, payload)
        # 生成成功则自动存入历史库（与流式接口一致）
        chat_id = None
        if report and not report.lstrip().startswith("[AI 生成失败]"):
            try:
                chat_id = uuid.uuid4().hex
                _register_session(chat_id, payload, report)
            except Exception as e:
                print(f"[ai_store] 保存失败: {e}")
        return {"code": 200, "report": report, "chatId": chat_id}
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}


@app.post("/api/ai/summary/stream")
async def ai_summary_stream(payload: dict):
    """SSE 流式输出：每次推一段 delta，前端 fetch + ReadableStream 实时渲染。"""
    def _sse_pack(data: dict) -> bytes:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    async def _event_gen():
        # 心跳先发一帧，避免部分代理对长连接的 60s 超时
        yield _sse_pack({"hello": True})
        full_parts = []
        try:
            loop = asyncio.get_running_loop()
            # 在线程里迭代同步生成器，避免阻塞事件循环
            queue: asyncio.Queue = asyncio.Queue()

            def _producer():
                try:
                    for chunk in ai_report.stream_report(payload):
                        loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, ("err", f"{type(e).__name__}: {e}"))
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

            threading.Thread(target=_producer, daemon=True).start()

            while True:
                kind, val = await queue.get()
                if kind == "end":
                    break
                if kind == "err":
                    yield _sse_pack({"error": val})
                    break
                if kind == "chunk" and val:
                    full_parts.append(val)
                    yield _sse_pack({"delta": val})
        except Exception as e:
            yield _sse_pack({"error": f"{type(e).__name__}: {e}"})
        finally:
            # 生成完成 → 自动保存到历史库（与非流式接口一致）
            text = "".join(full_parts)
            chat_id = None
            if text and not text.lstrip().startswith("[AI 生成失败]"):
                try:
                    chat_id = uuid.uuid4().hex
                    await asyncio.to_thread(_register_session, chat_id, payload, text)
                except Exception as e:
                    print(f"[ai_store] 流式保存失败: {e}")
            yield _sse_pack({"done": True, "chatId": chat_id})

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/ai/chat/stream")
async def ai_chat_stream(payload: dict):
    """SSE 多轮对话端点（D2 无限队列 + hello 心跳 + 失败降级）。body: {chatId, userText}。"""
    def _sse_pack(data: dict) -> bytes:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    chat_id = payload.get("chatId")
    user_text = ai_report.filter_user_input(payload.get("userText", ""))

    async def _event_gen():
        yield _sse_pack({"hello": True})
        full_parts = []
        try:
            # 加载会话（加锁内部已处理，返回副本，不在此嵌套持锁，避免死锁 D5）
            messages = _load_chat_messages(chat_id)
            if messages is None:
                yield _sse_pack({"error": "会话不存在或已过期，请重新生成报告"})
                return
            messages = list(messages)
            messages.append({"role": "user", "content": user_text})

            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def _producer():
                try:
                    for chunk in ai_report.stream_chat(messages):
                        loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, ("err", f"{type(e).__name__}: {e}"))
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

            threading.Thread(target=_producer, daemon=True).start()

            while True:
                kind, val = await queue.get()
                if kind == "end":
                    break
                if kind == "err":
                    yield _sse_pack({"error": val})
                    return
                if kind == "chunk" and val:
                    full_parts.append(val)
                    yield _sse_pack({"delta": val})
        except Exception as e:
            yield _sse_pack({"error": f"{type(e).__name__}: {e}"})
        finally:
            # done 后才落库并更新会话（D6）
            # messages 此时已含 system + 历史 + 当前 user，直接追加 assistant 即可，
            # 避免旧逻辑中「base is None 分支重复追加 user」导致畸形上下文。
            text = "".join(full_parts)
            if text and not text.lstrip().startswith("[AI 生成失败]"):
                try:
                    with CHAT_LOCK:
                        new_msgs = list(messages) + [{"role": "assistant", "content": text}]
                        CHAT_SESSIONS[chat_id] = new_msgs
                        turns = ai_report.truncate_conversation(new_msgs[1:])
                        ai_store.save(None, None, conversation=turns, rid=chat_id)
                except Exception as e:
                    print(f"[ai_store] 对话保存失败: {e}")
            yield _sse_pack({"done": True})

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/ai/chat")
async def ai_chat_api(payload: dict):
    """多轮对话非流式兜底端点。body: {chatId, userText}。"""
    chat_id = payload.get("chatId")
    user_text = ai_report.filter_user_input(payload.get("userText", ""))
    try:
        messages = _load_chat_messages(chat_id)
        if messages is None:
            return {"code": 404, "msg": "会话不存在或已过期，请重新生成报告"}
        messages = list(messages)
        messages.append({"role": "user", "content": user_text})
        answer = await asyncio.to_thread(ai_report.generate_report_from_messages, messages)
        if answer.lstrip().startswith("[AI 生成失败]"):
            return {"code": 500, "msg": answer}
        with CHAT_LOCK:
            # messages 已含 system + 历史 + 当前 user，直接追加 assistant
            new_msgs = list(messages) + [{"role": "assistant", "content": answer}]
            CHAT_SESSIONS[chat_id] = new_msgs
            turns = ai_report.truncate_conversation(new_msgs[1:])
            ai_store.save(None, None, conversation=turns, rid=chat_id)
        return {"code": 200, "answer": answer}
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}


@app.get("/api/ai/history")
async def ai_history_list():
    """返回全部 AI 复盘历史（按生成时间倒序），含报告全文。"""
    return {"code": 200, "records": ai_store.list_all()}


@app.delete("/api/ai/history/{rid}")
async def ai_history_delete(rid: str):
    ok = ai_store.delete(rid)
    return {"code": 200 if ok else 404, "ok": ok}


@app.get("/ai_history")
async def ai_history_page():
    return FileResponse(
        "ai_history.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/psych")
async def psych_page():
    return FileResponse(
        "web/psych.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/habits")
async def habits_page():
    return FileResponse(
        "web/habits.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ==================== 市场环境看板（）API ====================
@app.get("/market")
async def market_page():
    return FileResponse(
        "web/market.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/market/overview")
def market_overview():
    return get_overview()


@app.get("/api/market/trend")
def market_trend():
    return get_trend()


@app.get("/api/market/correlations")
def market_correlations():
    return get_correlations()


# ==================== 金十数据代理（每日交易页） ====================
async def _jin10_snapshot(fn):
    """金十请求为同步阻塞，放到线程池避免卡住事件循环。"""
    return await asyncio.to_thread(fn)


@app.get("/api/jin10/quotes")
async def jin10_quotes(codes: str = ",XAGUSD,USOIL,UKOIL,EURUSD,USDJPY"):
    """金十行情快照（含缓存 30s）。codes 逗号分隔。"""
    code_list = [c.strip().upper() for c in codes.split(",") if c.strip()]
    try:
        data = await _jin10_snapshot(lambda: jin10.snapshot_quotes(code_list))
        ok = bool(data)
        return {"code": 200 if ok else 502, "msg": "success" if ok else "金十行情获取失败", "data": data}
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": {}}


@app.get("/api/jin10/calendar")
async def jin10_calendar():
    """本周财经日历（含 affect_txt 利多/利空判向与星级），缓存 10min。"""
    try:
        snap = await _jin10_snapshot(jin10.snapshot_calendar)
        data = snap.get("data", [])
        ok = bool(data)
        return {
            "code": 200 if ok else 502,
            "msg": "success" if ok else "金十日历获取失败",
            "data": data, "stale": snap.get("stale", False),
            "ts": snap.get("ts", 0), "err": snap.get("err"),
        }
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": []}


@app.get("/api/jin10/flash")
async def jin10_flash():
    """分主题金十快讯（黄金/原油/美联储/美元/地缘/美股），缓存 5min。"""
    try:
        snap = await _jin10_snapshot(jin10.snapshot_flash)
        data = snap.get("data", {})
        ok = bool(data)
        return {
            "code": 200 if ok else 502,
            "msg": "success" if ok else "金十快讯获取失败",
            "data": data, "stale": snap.get("stale", False),
            "ts": snap.get("ts", 0), "err": snap.get("err"),
        }
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": {}}


@app.get("/api/jin10/gold_news")
async def jin10_gold_news(force: int = 0):
    """黄金消息面： 强相关基本面流（CPI/非农/美联储利率/官员讲话/避险地缘等），
    含利多利空标注 + 本周黄金高影响数据事件。缓存 4min，?force=1 强制刷新。"""
    try:
        payload = await _jin10_snapshot(lambda: jin10.snapshot_gold_news(force=bool(force)))
        events = payload.get("events", [])
        data_events = payload.get("data_events", [])
        ok = bool(events) or bool(data_events)
        return {
            "code": 200 if ok else 502,
            "msg": "success" if ok else "黄金消息面获取失败",
            "data": {
                "events": events,
                "data_events": data_events,
                "fetched_at": payload.get("fetched_at", ""),
                "stale": payload.get("stale", False),
                "err": payload.get("err"),
            },
        }
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": {}}


# ==================== 整月  消息面日历 ====================
_MONTH_CACHE = {}
_MONTH_LOCK = threading.Lock()
_MONTH_TTL = 600  # 10min


def _month_cal_sync(year: int, month: int):
    """同步取某月整月日历（排期推算 + 金十当前周实时合并），带 10min 缓存。"""
    today = datetime.now().date()
    ck = f"{year}-{month:02d}"
    now_ts = int(time.time())
    with _MONTH_LOCK:
        hit = _MONTH_CACHE.get(ck)
        if hit and now_ts - hit["ts"] < _MONTH_TTL and hit["today"] == today.isoformat():
            return hit["data"]
    try:
        cal = jin10.get_calendar_week()          # 当前周真实行
    except Exception:
        cal = []
    data = month_cal.month_calendar(year, month, jin10_rows=cal, today=today)
    with _MONTH_LOCK:
        _MONTH_CACHE[ck] = {"ts": now_ts, "today": today.isoformat(), "data": data}
    return data


@app.get("/api/jin10/month_cal")
async def jin10_month_cal(month: str = ""):
    """整月  消息面日历。month=YYYY-MM（默认当前月）。缓存 10min。"""
    try:
        if not month:
            now = datetime.now()
            year, mon = now.year, now.month
        else:
            year, mon = int(month[:4]), int(month[5:7])
            if not (2000 <= year <= 2100 and 1 <= mon <= 12):
                raise ValueError("month 格式应为 YYYY-MM")
        data = await _jin10_snapshot(lambda: _month_cal_sync(year, mon))
        return {"code": 200, "msg": "success", "data": data}
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": {}}
@app.post("/api/psych/record")
def psych_record(payload: dict):
    """保存一条交易心理记录（pre/in/post）。"""
    return add_record(payload)


@app.get("/api/psych/records")
def psych_records(scenario: str = None, limit: int = 200):
    return list_records(scenario, limit)


@app.get("/api/psych/stats")
def psych_stats():
    return get_stats()


@app.delete("/api/psych/records/{rid}")
def psych_delete(rid: str):
    return delete_record(rid)


@app.get("/review")
async def review_page():
    return FileResponse(
        "web/review.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/realtime")
async def realtime_page():
    return FileResponse(
        "web/realtime.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/realtime/klines")
async def realtime_klines(
    symbol: str = "",
    interval: str = "1m",
    limit: int = 1000,
    response: Response = None,
):
    """实时 K线代理：浏览器经本路由访问 Binance fapi，避开跨域/网络问题。"""
    import requests
    # 关键：禁用浏览器缓存，否则轮询的 GET 会被缓存，图表"冻住"无法实时更新
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    symbol = (symbol or "").upper().strip()
    if not symbol:
        return {"code": 400, "msg": "symbol 不能为空", "data": []}
    if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "1d"):
        return {"code": 400, "msg": "不支持的周期", "data": []}
    if limit <= 0 or limit > 1500:
        limit = 1000

    url = f"{FAPI_KLINES}?symbol={symbol}&interval={interval}&limit={limit}"
    proxies = data_sync.PROXIES

    def _get():
        return requests.get(url, proxies=proxies, timeout=15)

    try:
        resp = await asyncio.to_thread(_get)
        if resp.status_code != 200:
            return {"code": resp.status_code, "msg": f"Binance 返回 {resp.status_code}: {resp.text[:200]}", "data": []}
        data = resp.json()
        return {"code": 200, "msg": "success", "data": data}
    except Exception as e:
        return {"code": 502, "msg": f"代理访问 Binance 失败: {type(e).__name__}: {e}", "data": []}


# =============================================================
#  每日交易计划（直接价格接口基址 BINANCE_FAPI_BASE ，无 PAXG+12 偏移）
# 全新独立路径 /xau + /api/xau/plan + /api/xau/backtest
# 复用 data_sync.PROXIES + requests，与 /api/realtime/klines 同链路
# =============================================================
@app.get("/xau")
async def xau_page():
    """ 每日交易计划页面（HTML 内联常量，避开 .html 被同步工具改写）。"""
    from pages import xau_report_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _fapi_fetch(url: str):
    """注入 xau_report 的 fetch_fn：复用项目内 PROXIES + requests。"""
    import requests
    proxies = data_sync.PROXIES
    resp = requests.get(url, proxies=proxies, timeout=15)
    resp.raise_for_status()
    return resp.json()


@app.get("/api/xau/plan")
async def api_xau_plan(asof: str = None, response: Response = None):
    """asof: 'YYYY-MM-DD HH:MM' 北京时；缺省 = 当前 BJ 09:00 切"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from core import xau_report as xr
    out = xr.api_plan(asof, fetch_fn=_fapi_fetch)
    if out.get("code") != 200 and "error" not in out:
        response.status_code = 502
    return out


@app.get("/api/xau/backtest")
async def api_xau_backtest(start: str = "2026-08-07", end: str = "2026-09-04", response: Response = None):
    """start/end: 'YYYY-MM-DD' 北京时"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from core import xau_report as xr
    out = xr.api_backtest(start, end, fetch_fn=_fapi_fetch)
    if out.get("code") == 500:
        response.status_code = 500
    return out


@app.get("/api/xau/report")
async def api_xau_report(asof: str = None, response: Response = None):
    """生成 AI 分析师每日交易计划报告（Markdown）。

    数据源： fapi（突破跟随计划）+ TwelveData（DXY 合成 + EURUSD/GBPUSD/AUDUSD）。
    大模型：config.BAILIAN_MODEL（qwen3.7-max-2026-06-08）。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from core import xau_report as xr
    from data import xau_macro as xm
    from core import daily_report_ai as dra

    plan_out = xr.api_plan(asof, fetch_fn=_fapi_fetch)
    if plan_out.get("code") != 200 or not plan_out.get("plan"):
        return {"code": plan_out.get("code", 502), "error": plan_out.get("error", "计划生成失败"),
                "markdown": None}
    plan = plan_out["plan"]
    warns = plan_out.get("warns", [])
    source = plan_out.get("source", "")
    asof_str = plan_out.get("asof_str", asof or "")

    # 宏观数据（TwelveData；自带 15 分钟缓存 + 限流保护，失败返回 ok=False 不抛异常）
    try:
        macro = xm.fetch_macro()
    except Exception as e:
        macro = {"ok": False, "note": f"宏观数据异常: {type(e).__name__}: {e}"}

    # 消息面（金十；独立聚合，任一源失败只丢消息面段，主流程照常出报告）
    news = None
    try:
        from data import xau_news as xn
        news = await asyncio.to_thread(xn.compute_news_facts)
    except Exception as e:
        news = {"ok": False, "text": f"（消息面不可用：{type(e).__name__}: {e}）"}

    markdown = await asyncio.to_thread(dra.generate, plan, warns, macro, source=source,
                                       asof_str=asof_str, news=news)
    return {
        "code": 200,
        "asof_str": asof_str,
        "source": source,
        "macro": macro,
        "plan_summary": {
            "cur": plan.get("cur"),
            "bias": plan.get("bias"),
            "pdh": (plan.get("prev_day") or {}).get("high"),
            "pdl": (plan.get("prev_day") or {}).get("low"),
            "primary_side": (plan.get("primary") or {}).get("side"),
        },
        "markdown": markdown,
    }


# =============================================================
# 实时阶段闸门（ABCDEF）· 该不该开 / 用哪套 / 开多大
# 复用 _fapi_fetch（PROXIES + requests）取 （强制，不回退现货）；xau_stage 失败时直接 502
# =============================================================
@app.get("/api/xau/stage")
async def api_xau_stage(response: Response = None):
    """实时 ABCDEF 阶段判定 + 开仓决策（JSON）。"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from core import xau_stage as xs
    out = xs.api_stage(fetch_fn=_fapi_fetch)
    if out.get("code") != 200:
        response.status_code = 502
    return out


@app.get("/api/xau/stage_report")
async def api_xau_stage_report(response: Response = None):
    """生成 ABCDEF 阶段闸门 AI 报告（Markdown）。"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from core import xau_stage as xs
    out = await asyncio.to_thread(xs.api_stage_report, _fapi_fetch)
    if out.get("code") != 200:
        response.status_code = 502
    return out


# =============================================================
#  思维导图 · 知识库教学智能体（纯检索，不接行情 / 不参与交易决策）
# 页面: GET /mindmap  （旧路径 /xau/mindmap 保留 307 跳转）
# 接口: GET  /api/xau/mindmap/modules
#       GET  /api/xau/mindmap/module?mid=M03
#       POST /api/xau/mindmap/chat  {"q": "...", "top_k": 6}
# =============================================================
@app.get("/mindmap")
async def xau_mindmap_page():
    """思维导图知识库智能体页面（HTML 内联常量）。"""
    from pages import xau_mindmap_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/xau/mindmap")
async def xau_mindmap_page_legacy():
    """旧路径兼容：307 跳转到 /mindmap。"""
    return RedirectResponse(url="/mindmap", status_code=307)


@app.get("/api/xau/mindmap/modules")
async def api_xau_mindmap_modules(response: Response = None):
    """思维导图 14 个模块清单（侧边栏用）。"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    from core import xau_mindmap as xm
    try:
        return {"code": 200, "msg": "ok", "data": xm.list_modules()}
    except Exception as e:
        response.status_code = 500
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": []}


@app.get("/api/xau/mindmap/module")
async def api_xau_mindmap_module(mid: str, response: Response = None):
    """单模块全部规则原文。mid 形如 M03。"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    from core import xau_mindmap as xm
    d = xm.get_module(mid.upper())
    if not d:
        response.status_code = 404
        return {"code": 404, "msg": f"未找到模块 {mid}", "data": {}}
    return {"code": 200, "msg": "ok", "data": d}


@app.post("/api/xau/mindmap/chat")
async def api_xau_mindmap_chat(payload: dict, response: Response = None):
    """知识库问答：BM25 检索 → LLM 生成（失败回退确定性模板）。

    铁律：只允许基于知识库回答，严禁输出交易信号 / 方向建议。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    from core import xau_mindmap as xm
    q = (payload or {}).get("q", "").strip()
    if not q:
        response.status_code = 400
        return {"code": 400, "msg": "q 不能为空", "data": {}}
    top_k = int((payload or {}).get("top_k", 6) or 6)
    top_k = max(1, min(top_k, 20))
    try:
        out = await asyncio.to_thread(xm.chat, q, top_k=top_k)
        return {"code": 200, "msg": "ok", "data": out}
    except Exception as e:
        response.status_code = 500
        return {"code": 500, "msg": f"{type(e).__name__}: {e}", "data": {}}


@app.post("/api/xau/mindmap/market")
async def api_xau_mindmap_market(payload: dict, response: Response = None):
    """行情对话（AI 分析师 · 实验模块）。

    body: {"q": "问题", "facts_only": true/false, "top_k": 6}
      facts_only=true  -> 只返回客观盘面事实，不调 LLM
      facts_only=false -> 事实 + 思维导图规则 -> LLM 出方向/进场/止损/止盈

    隔离约定：只读行情 + 只读知识库，不写信号库、不触发下单、不接入 TRAE 链路。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    from core import xau_mindmap_market as xmm
    body = payload or {}
    q = (body.get("q") or "").strip()
    facts_only = bool(body.get("facts_only"))
    with_news = body.get("with_news", True)   # 默认结合金十消息面

    if facts_only:
        try:
            f = await asyncio.to_thread(xmm.compute_facts, _fapi_fetch)
        except Exception as e:
            response.status_code = 502
            return {"code": 502, "msg": f"行情取数失败: {type(e).__name__}: {e}", "data": {}}
        return {"code": 200, "msg": "ok",
                "data": {"mode": "facts", "facts": f, "facts_text": xmm.format_facts(f),
                         "answer": None, "sources": [], "latency_ms": 0}}

    try:
        top_k = max(1, min(int(body.get("top_k", 6) or 6), 20))
    except Exception:
        top_k = 6
    out = await asyncio.to_thread(xmm.market_chat, q, _fapi_fetch, top_k=top_k, with_news=with_news)
    if out.get("code") == 502:
        response.status_code = 502
    elif out.get("code") == 500:
        response.status_code = 500
    elif out.get("code") == 503:
        response.status_code = 200   # 缺 Key 不是服务端错误，前端会提示
    return out


@app.get("/api/kline/review")
async def get_review_kline(
    startTime: str,
    endTime: str = None,
    interval: str = "1m",
):
    if interval not in TABLE_MAP:
        return {"code": 400, "msg": "不支持的周期", "data": [], "truncated": False}

    start_dt = parse_date_str(startTime)
    if not start_dt:
        return {"code": 400, "msg": "起始时间格式错误", "data": [], "truncated": False}

    if not endTime:
        end_dt = start_dt + timedelta(days=1)
    else:
        end_dt = parse_date_str(endTime)
        if not end_dt:
            return {"code": 400, "msg": "结束时间格式错误", "data": [], "truncated": False}

    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    now = datetime.now()
    if start_dt > now:
        return {"code": 400, "msg": "不可查询未来时间", "data": [], "truncated": False}

    start_ts = datetime_to_ts(start_dt)
    end_ts = datetime_to_ts(end_dt)
    data, truncated = await run_query(TABLE_MAP[interval], start_ts, end_ts)

    if not data:
        return {"code": 204, "msg": "暂无数据", "data": [], "truncated": False}

    msg = f"数据量过大，已截断至前{MAX_ROWS}条，请缩小查询范围" if truncated else "success"
    return {"code": 200, "msg": msg, "data": data, "truncated": truncated}


@app.get("/api/kline/fastrange")
def get_fast_range(typ: str):
    now = datetime.now()
    if typ == "3d":
        s = now - timedelta(days=3)
    elif typ == "1w":
        s = now - timedelta(weeks=1)
    elif typ == "1m":
        s = now - timedelta(days=30)
    elif typ == "3m":
        s = now - timedelta(days=90)
    elif typ == "6m":
        s = now - timedelta(days=180)
    else:
        return {"code": 400, "msg": "参数错误"}
    return {
        "code": 200,
        "startTime": s.strftime("%Y-%m-%d"),
        "endTime": now.strftime("%Y-%m-%d"),
    }


# ==================== 数据同步 API ====================
@app.post("/api/sync/db")
def sync_db():
    """同步数据库：建/校验 4 张 kline_*m 表（同步执行，秒级返回）"""
    if data_sync.get_status()["running"]:
        return {"code": 429, "msg": "已有同步任务在运行，请稍后再试"}
    try:
        info = data_sync.ensure_tables()
        return {"code": 200, "msg": "数据库表结构就绪", "data": info}
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}


@app.post("/api/sync/data")
def sync_data():
    """同步数据：从 Binance 增量抓 4 个周期 K线（后台线程）"""
    if data_sync.get_status()["running"]:
        return {"code": 429, "msg": "已有同步任务在运行，请查看状态面板"}
    t = threading.Thread(target=data_sync.run_fetch_all_bg, daemon=True)
    t.start()
    return {"code": 200, "msg": "已启动后台同步任务，请查看右上角状态面板", "running": True}


@app.get("/api/sync/status")
def sync_status():
    """轮询同步状态和最新日志"""
    return {"code": 200, "data": data_sync.get_status()}


# ==================== 每日交易计划（新增模块） ====================
@app.get("/trade")
async def trade_page():
    # 全新路径 /trade，完全干净的 Vue 模板（与 dailyplan_template.py 解耦），从根上避开 Chrome 的旧 /dailyplan 缓存。
    from pages.trade_template import HTML
    import time as _t
    return Response(
        content=HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "ETag": 'W/"trade-%d"' % int(_t.time()),
            "Last-Modified": _t.strftime("%a, %d %b %Y %H:%M:%S GMT", _t.gmtime()),
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/dailyplan")
async def dailyplan_legacy_redirect():
    # 强制 302 跳到 /trade，避免 Chrome 命中旧缓存。即便浏览器还记着 /dailyplan 的旧 HTML，
    # 遇到 302 也会按 Location 头重新发请求到 /trade，命中全新的 Vue 模板。
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/trade", status_code=302,
                           headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@app.get("/dailyplan_page", response_class=Response)
async def dailyplan_old_template_removed():
    body = "<!doctype html><meta charset=utf-8><h1>已迁移</h1><p>该模板已删除，请访问 <a href='/trade'>/trade</a>。</p>"
    return Response(content=body, media_type="text/html; charset=utf-8", status_code=410,
                    headers={"Cache-Control": "no-store"})


def _parse_asof(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except Exception:
            continue
    return None


@app.get("/api/dailyplan/plan")
async def api_dailyplan_plan(asof: str = None):
    """生成交易计划（v2 突破跟随）。asof 缺省=当前时刻。"""
    dt_ = _parse_asof(asof) if asof else datetime.now()
    if dt_ is None:
        return {"code": 400, "msg": "时间格式错误，示例 2026-09-07 09:00"}
    # 输入按北京时间解释 -> UTC 毫秒（-8h）。不可直接 (dt-epoch).total_seconds()，
    # 那样会把北京时间当 UTC，整体多出 8 小时。
    asof_ms = daily_plan.to_ms_bj(dt_.year, dt_.month, dt_.day, dt_.hour, dt_.minute)

    # 预热窗口：asof 前 70 天（够算 ATR14 / SMA10 / 20日摆动）
    start = asof_ms - 70 * 86400000
    end = asof_ms + 2 * 86400000
    try:
        bars = daily_plan.load_bars(start, end)
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}
    if not bars:
        return {"code": 204, "msg": "无行情数据"}

    plan, sim = daily_plan.run_day_v2(bars, asof_ms)
    if not plan.get("ok"):
        return {"code": 204, "msg": plan.get("reason", "无法生成计划")}

    # 数据边界警告
    warns = []
    last_ct = bars[-1]["close_time"]
    if asof_ms - last_ct > 3600_000:
        warns.append({"level": "bad", "t": "数据滞后",
                      "m": f"本地数据止于 {daily_plan.bj(last_ct).strftime('%Y-%m-%d %H:%M')}，"
                           f"晚于决策时点所需。请先在数据同步页补充行情。"})
    pd_day = plan["prev_day"]["day"]
    try:
        wd = datetime.strptime(pd_day, "%Y-%m-%d").weekday()
        if wd >= 5:
            warns.append({"level": "bad", "t": "周末薄盘",
                          "m": f"前一交易日 {pd_day} 是周末，真实  休市但加密盘照常交易，"
                               f"PDH/PDL 来自薄流动性，实盘请以周五收盘区间复核。"})
    except Exception:
        pass
    if plan.get("too_close"):
        warns.append({"level": "", "t": "区间过窄",
                      "m": "PDH/PDL 与现价距离均小于 0.05 ATR，突破信号的信噪比很低，建议当日观望。"})

    # 图表数据：asof 前 3 天 5m
    kl_bars = [b for b in bars if b["close_time"] <= asof_ms][-864:]
    klines = [{"t": daily_plan.bj(b["open_time"]).strftime("%m-%d %H:%M"),
               "o": b["open"], "c": b["close"], "l": b["low"], "h": b["high"]} for b in kl_bars]

    return {"code": 200, "plan": plan, "sim": sim, "klines": klines, "warns": warns}


@app.get("/api/dailyplan/backtest")
async def api_dailyplan_backtest(start: str = "2026-02-01", end: str = "2026-09-04"):
    """v2 walk-forward 回测"""
    try:
        sd = datetime.strptime(start, "%Y-%m-%d")
        ed = datetime.strptime(end, "%Y-%m-%d")
    except Exception:
        return {"code": 400, "msg": "日期格式错误"}
    try:
        bars = daily_plan.load_bars(
            daily_plan.to_ms_bj(sd.year, sd.month, sd.day) - 70 * 86400000,
            daily_plan.to_ms_bj(ed.year, ed.month, ed.day) + 2 * 86400000)
        recs = daily_plan.backtest_range_v2(bars, (sd.year, sd.month, sd.day),
                                            (ed.year, ed.month, ed.day), 9, 0)
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}
    if not recs:
        return {"code": 204, "msg": "无回测数据"}

    s = daily_plan.summarize(recs)
    # 月度
    from collections import defaultdict
    bym = defaultdict(list)
    recent = []
    for r in recs:
        for t in r["trades"]:
            if t.get("status") != "成交":
                continue
            bym[r["trade_day"][:7]].append(t["net_r"])
            recent.append({"day": r["trade_day"], "side": t["side"], "fill": t["fill"],
                           "exit_reason": t["exit_reason"], "gross_r": t["gross_r"],
                           "cost_r": t["cost_r"], "net_r": t["net_r"], "pnl_u": t["pnl_u"]})
    monthly = [{"m": k, "r": round(sum(v) / len(v), 3), "tot": round(sum(v), 2), "n": len(v)}
               for k, v in sorted(bym.items())]
    return {"code": 200, **s, "monthly": monthly, "recent": recent[-15:][::-1]}


# ---------- 每日计划 · AI 分析师报告 ----------
@app.get("/api/dailyplan/report")
async def api_dailyplan_report(asof: str = None, model: str = None):
    """基于当日结构化行情 + 突破跟随计划，调用大模型生成  每日交易计划报告（Markdown）。"""
    dt_ = _parse_asof(asof) if asof else datetime.now()
    if dt_ is None:
        return {"code": 400, "msg": "时间格式错误，示例 2026-09-07 09:00"}
    asof_ms = daily_plan.to_ms_bj(dt_.year, dt_.month, dt_.day, dt_.hour, dt_.minute)

    start = asof_ms - 70 * 86400000
    end = asof_ms + 2 * 86400000
    try:
        bars = daily_plan.load_bars(start, end)
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}
    if not bars:
        return {"code": 204, "msg": "无行情数据"}

    plan, sim = daily_plan.run_day_v2(bars, asof_ms)
    if not plan.get("ok"):
        return {"code": 204, "msg": plan.get("reason", "无法生成计划")}

    # 复用与 /api/dailyplan/plan 一致的预警逻辑
    warns = []
    last_ct = bars[-1]["close_time"]
    if asof_ms - last_ct > 3600_000:
        warns.append({"level": "bad", "t": "数据滞后",
                      "m": f"本地数据止于 {daily_plan.bj(last_ct).strftime('%Y-%m-%d %H:%M')}，"
                           f"晚于决策时点所需。请先在数据同步页补充行情。"})
    pd_day = plan["prev_day"]["day"]
    try:
        wd = datetime.strptime(pd_day, "%Y-%m-%d").weekday()
        if wd >= 5:
            warns.append({"level": "bad", "t": "周末薄盘",
                          "m": f"前一交易日 {pd_day} 是周末，真实  休市但加密盘照常交易，"
                               f"PDH/PDL 来自薄流动性，实盘请以周五收盘区间复核。"})
    except Exception:
        pass
    if plan.get("too_close"):
        warns.append({"level": "", "t": "区间过窄",
                      "m": "PDH/PDL 与现价距离均小于 0.05 ATR，突破信号信噪比很低，建议当日观望。"})

    try:
        from core import daily_report_ai
        report = await asyncio.to_thread(daily_report_ai.generate, bars, asof_ms, plan, warns, model=model)
    except Exception as e:
        return {"code": 500, "msg": f"{type(e).__name__}: {e}"}

    if report.startswith("[AI 生成失败]"):
        return {"code": 502, "msg": report}
    return {"code": 200, "asof": plan.get("asof_str"), "report": report}


# =============================================================
# 乌圆狩猎区 · 档位图（官方口径锚定；人工给 S / 四线）
# 全新路径 /wuyuan + /api/wuyuan/ladder
# 引擎 = wuyuan_core（纯计算：无网络、无第三方依赖）
# 红线：**不提供任何"系统猜腿"入口**（0.0 档 / S 已证不可预测）；
#       现价走既有 fapi 链路（，零偏移），仅用于显示"距档位多少点"，
#       并显式标注为期货参考价，不参与任何档位计算。
# =============================================================
@app.get("/wuyuan")
async def wuyuan_page():
    """乌圆狩猎区档位图页面（HTML 内联常量，避开 .html 被外部工具改写）。"""
    from pages import wuyuan_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _wuyuan_live():
    """取 fapi  最新价（期货参考价）。返回 (dict|None, 失败原因|None)。"""
    try:
        url = FAPI_KLINES + "?symbol=&interval=1m&limit=2"
        rows = _fapi_fetch(url)
        if not rows:
            return None, "fapi 返回空数组"
        return {
            "px": float(rows[-1][4]),
            "ts": int(rows[-1][0]),
            "source": f"{BINANCE_FAPI_BASE or '价格接口基址'}  1m",
            "note": "期货参考价 · 与官方现货口径存在基差（实测 −98 ~ +24 点）",
        }, None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _wuyuan_daily():
    """取自研腿所需的日线 + 当日开盘价。

    返回 (daily, open_px, today_open_ts, err)。
    - daily：**只含已收盘日线**（用 close_time 判定），升序
    - open_px：当日开盘价（= 100.0 档，官方口径）
    取数失败时 daily=None 并把原因写进 err —— 调用方**明确报错，绝不猜**。
    """
    import time as _t
    try:
        n = __import__("wuyuan_core").AUTO_LEG_LOOKBACK + 5
        url = (FAPI_KLINES + "?symbol="
               "&interval=1d&limit=%d" % n)
        rows = _fapi_fetch(url)
        if not rows:
            return None, None, None, "fapi 返回空数组（日线不可得）"
        now_ms = int(_t.time() * 1000)
        # 按 close_time (r[6]) 切分：已收盘 vs 当日未收盘
        closed = [r for r in rows if int(r[6]) < now_ms]
        opened = [r for r in rows if int(r[6]) >= now_ms]
        if not closed:
            return None, None, None, "没有已收盘日线（fapi 只返回了 %d 根）" % len(rows)
        daily = [{"high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
                 for r in closed]
        # 当日开盘价：优先用未收盘那根的 open；若全已收盘（极端情况）用最后一根 open
        today = opened[-1] if opened else rows[-1]
        open_px = float(today[1])
        return daily, open_px, int(today[0]), None
    except Exception as e:
        return None, None, None, "%s: %s" % (type(e).__name__, e)


@app.get("/api/wuyuan/ladder")
async def api_wuyuan_ladder(open_px: float = None, live: int = 1,
                            offset: float = None, response: Response = None):
    """乌圆狩猎区档位表（JSON）—— **自研腿为唯一入口**。

    系统自己取日线、自己算腿端与方向、自己出档位，**不需要任何人工输入**。
    `open_px` 可省略（缺省由服务端取当日开盘价）；仅在需要人工覆盖时才传。

    ⚠ 自研腿不是已验证策略（六门槛 5 FAIL）。返回体必带
       tag/verdict/tradable/auto_warnings，调用方必须原样展示，不得隐去。
    ⚠ 取数失败一律明确报错（502），**绝不猜一个 S 出来**。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from core import wuyuan_core as wc

    daily, auto_open, ts, err = _wuyuan_daily()
    if daily is None:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "mode": "auto_leg", "engine": wc.ENGINE_VERSION,
                "ok": False, "error": "取数失败：%s ⇒ 不猜腿，请稍后重试。" % err}

    if open_px is None:
        open_px = auto_open

    try:
        ar = wc.auto_leg(open_px, daily, offset=offset or 0.0,
                         source=" 1d（已收盘）")
    except Exception as e:
        return {"code": 400, "error": "%s: %s" % (type(e).__name__, e)}

    if not ar.get("ok"):
        return {"code": 200, "mode": "auto_leg", "engine": wc.ENGINE_VERSION,
                "ok": False, "reason": ar.get("reason"),
                "auto": {k: ar.get(k) for k in (
                    "rule", "lookback", "direction", "direction_cn", "open_px",
                    "P0", "S", "R", "r_bp", "min_r_bp", "cost_floor_bp",
                    "offset", "prev_close", "tag", "verdict")},
                "open_ts": ts,
                "auto_warnings": list(wc.AUTO_LEG_WARNINGS),
                "hint": "自研腿判定当日无结构（这是规则的一部分，不是故障）。"
                        "结构太窄或跳空越过近 %d 日极值时会发生。" % ar.get("lookback", 5)}

    warnings = []
    live_info = None
    if live:
        live_info, why = _wuyuan_live()
        if live_info is None:
            warnings.append("现价不可用（%s）⇒ 档位表照常返回，距离列以狩猎区中值为基准。" % why)

    out = wc.annotate(ar["ladder"], live_px=(live_info or {}).get("px"))
    out["code"] = 200
    out["ok"] = True
    out["mode"] = "auto_leg"
    out["engine"] = wc.ENGINE_VERSION
    out["inv"] = None
    out["open_ts"] = ts
    out["auto"] = {k: ar.get(k) for k in (
        "rule", "lookback", "r_bp", "min_r_bp", "cost_floor_bp", "tradable",
        "trade_note", "offset", "prev_close", "P0", "tag", "verdict")}
    out["auto_warnings"] = list(wc.AUTO_LEG_WARNINGS)
    out["live"] = live_info
    out["warnings"] = warnings
    out["discipline"] = list(wc.DISCIPLINE)
    return out


# =============================================================
# 狩猎区 v2（/huntv2 + /api/huntv2/ladder）— 与 /wuyuan 并存，不改 /wuyuan 任何代码
# 引擎 = hz_engine(build 正解几何) + hz_signal(S_MODEL_FROZEN 冻结回归) + huntv2_core(编排)
# 红线：取数失败一律 502 明确报错，**绝不猜 S**；现价为 fapi  期货参考价，仅显示距离不参与计算
# =============================================================
@app.get("/huntv2")
async def huntv2_page():
    """狩猎区 v2 页面（HTML 内联常量，避开 .html 被外部工具改写）。"""
    from pages import huntv2_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/huntv2/ladder")
def api_huntv2_ladder(live: int = 1, response: Response = None):
    """狩猎区 v2 档位表（JSON）—— 系统自取日线、顺势方向、冻结回归 S、build 正解几何。

    ⚠ 取数失败一律 502 明确报错（绝不猜 S）。
    ⚠ 数据可取但今日无信号（方向临界 / 趋势过滤 / 波动过滤）→ 200 + ok:False + reason。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    from huntzone import huntv2_core as hc

    rows, err, source = hc.fetch_daily_1d()
    if rows is None:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False,
                "error": "取数失败：%s ⇒ 不猜 S，请稍后重试。" % err,
                "source": source}

    comp = hc.compute_ladder(rows, source=source)
    if not comp["ok"]:
        return {"code": 200, "ok": False, "reason": comp["reason"],
                "warnings": [], "mode": "self_sufficient",
                "note": "档位几何可信；S 为冻结回归预测（±21.95 点 LOO MAE），低置信度，按区间使用。"}

    live_info = None
    if live:
        live_info, why = _wuyuan_live()
        # 现价不可用非致命：档位照常返回，距离列以狩猎区中值为基准
    return hc.build_response(comp, live_info)


# =============================================================
# 狩猎区画廊（/huntzone-gallery + /api/huntzone-gallery/slides + /api/huntzone-gallery/day）
# 纯新增，复用 huntzone_gallery_core（零修改既有引擎/页面）。
# 红线：取数失败一律 502 明确报错，绝不猜 S；严格零未来函数。
# =============================================================
@app.get("/huntzone-gallery")
async def huntzone_gallery_page():
    """狩猎区画廊页面（HTML 内联常量，避开 .html 被外部工具改写）。"""
    from pages import huntzone_gallery_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/huntzone-gallery/slides")
def api_huntzone_gallery_slides(trigger: int = 20, start: str = None,
                                      end: str = None, symbol: str = "",
                                      response: Response = None):
    """画廊多日 slide 列表（JSON）。

    默认 = 最近 30 个有信号日；可指定 start/end 闭区间逐日枚举。
    ⚠ 取数失败（fapi/local 不可得）一律 502 明确报错，绝不猜 S。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    trigger = max(8, min(26, int(trigger)))
    try:
        from huntzone import huntzone_gallery_core as gc
        out = gc.build_gallery_range(start=start, end=end, trigger=trigger, symbol=symbol)
    except Exception as e:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False,
                "error": "取数失败：%s ⇒ 不猜 S，请稍后重试。" % e}
    return out


@app.get("/api/huntzone-gallery/day")
def api_huntzone_gallery_day(date: str, trigger: int = 20,
                                   symbol: str = "",
                                   response: Response = None):
    """单日 1m 细部（JSON）。供画廊「看 1m 细部」按需拉取，不参与轮播预载。"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    trigger = max(8, min(26, int(trigger)))
    try:
        from huntzone import huntzone_gallery_core as gc
        out = gc.build_gallery_day(date, trigger=trigger, symbol=symbol, with_1m=True)
    except Exception as e:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False,
                "error": "取数失败：%s ⇒ 不猜 S，请稍后重试。" % e}
    return out


# =============================================================
# 狩猎区每日效果图（/huntzone-daily + /api/huntzone-daily/data）
# 纯新增。最简单版本：30m K线 + 9档 + 狩猎区色带 + 方向。无持仓/事件/P&L。
# =============================================================
@app.get("/huntzone-daily")
async def huntzone_daily_page():
    """狩猎区每日效果图页面（HTML 内联常量）。"""
    from pages import huntzone_daily_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/huntzone-daily/data")
def api_huntzone_daily_data(date: str, symbol: str = "",
                                  response: Response = None):
    """狩猎区每日效果图数据（JSON）。

    只返回 30m K线 + 9档 + zone + 方向；无持仓/事件/P&L。
    ⚠ 取数失败一律 502，绝不猜 S。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    try:
        from huntzone import huntzone_daily_core as dc
        out = dc.build_daily_view(date, symbol=symbol)
    except Exception as e:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False,
                "error": "取数失败：%s ⇒ 不猜 S，请稍后重试。" % e}
    return out


# =============================================================
# 多日狩猎区复盘工具（/huntzone-review + /api/huntzone-review/data）
# 纯新增。30m K线 + 多日连续狩猎区色带 + 日界分隔 + 聚焦日 9 档 + 范围切换 + 滑动条。
# 复用 hunting_system 逻辑（hz_engine / hz_signal / huntv2_core 同一数据源）。
# =============================================================
@app.get("/huntzone-review")
async def huntzone_review_page():
    """多日狩猎区复盘页面（HTML 内联常量）。"""
    from pages import huntzone_review_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# =============================================================
# 白银 XAGUSD 狩猎区复盘（/huntzone-review-xag + /api/huntzone-review-xag/data）
# 纯新增。复用 /huntzone-review 原逻辑（hz_engine.build + S_MODEL_FROZEN + gen_signal），
# 数据改走 Binance fapi XAGUSDT（日线 1d + 30m），支持 manual_S 覆盖（白银自适应 S）。
# 红线：取数失败一律 502 明确报错，绝不猜 S；严格零未来函数。
# =============================================================
@app.get("/huntzone-review-xag")
async def huntzone_review_xag_page():
    """白银 XAGUSD 狩猎区复盘页面（HTML 内联常量）。"""
    from pages import huntzone_review_xag_template as tpl
    return Response(
        content=tpl.HTML,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "Surrogate-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/huntzone-review-xag/data")
def api_huntzone_review_xag_data(start: str = None, end: str = None,
                                       symbol: str = "XAGUSDT", S: float = None,
                                       mode: str = "adaptive",
                                       response: Response = None):
    """白银多日狩猎区复盘数据（JSON）。

    返回 {ok, range, symbol, mode, panels[], missing_days[], suggested_S}。
    取数失败 → 502，绝不猜 S。
    S 优先级：S(手动) > mode='adaptive'(白银自适应，逐日因果) > mode='frozen'(原逻辑冻结模型)。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    try:
        from huntzone import huntzone_review_xag_core as xc
        out = xc.build_review_view(start, end, symbol=symbol, manual_S=S, mode=mode)
    except Exception as e:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False,
                "error": "取数失败：%s ⇒ 不猜 S，请稍后重试。" % e}
    if not out.get("ok"):
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False, "error": out.get("reason", "取数失败"),
                "suggested_S": out.get("suggested_S")}
    return out


@app.get("/api/huntzone-review/data")
def api_huntzone_review_data(start: str = None, end: str = None,
                                   symbol: str = "", response: Response = None):
    """多日狩猎区复盘数据（JSON）。

    返回 {ok, range, bars_30m, days[], missing_days[]}。
    取数失败 → 502，绝不猜 S。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    try:
        from huntzone import huntzone_review_core as rc
        out = rc.build_review_view(start, end, symbol=symbol)
    except Exception as e:
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False,
                "error": "取数失败：%s ⇒ 不猜 S，请稍后重试。" % e}
    if not out.get("ok"):
        if response is not None:
            response.status_code = 502
        return {"code": 502, "ok": False, "error": out.get("reason", "取数失败")}
    return out


if __name__ == "__main__":
    import uvicorn
    import subprocess
    import socket
    import time
    import threading
    import webbrowser

    _HOST = "127.0.0.1"
    # 默认 8000。可用环境变量 quant_review_PORT=xxxx 临时换端口。
    _PORT = int(os.environ.get("quant_review_PORT", "8000"))
    _URL = "http://%s:%d/" % (_HOST, _PORT)

    def _free_port(port):
        """一键启动前置: 结束所有已占用该端口的进程(整棵树)。

        否则若之前有过残留实例 / 另一个 uvicorn 在跑, 直接 uvicorn.run 会报
        address already in use, 或两个实例同抢 8000 导致请求被随机分流
        (表现为部分接口日志丢失)。这里统一先清干净再起, 保证唯一实例。
        """
        try:
            out = subprocess.run(["netstat", "-ano"],
                                 capture_output=True, timeout=10).stdout
        except Exception:
            return
        if not out:
            return
        text = out.decode("gbk", errors="ignore")
        pids = set()
        for line in text.splitlines():
            if (":%d " % port) in line and "LISTENING" in line:
                pids.add(int(line.split()[-1]))
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            except Exception:
                pass
        # 等端口真正释放
        for _ in range(20):
            try:
                with socket.create_connection((_HOST, port), timeout=0.3):
                    time.sleep(0.2)
            except OSError:
                return

    # 1) 停掉占用 8000 的旧实例(含 server_ctl 起的 / 残留进程), 保证唯一实例
    _free_port(_PORT)

    # 2) 后台等端口就绪后自动开浏览器 -> 真正的一键启动
    def _auto_open_browser():
        for _ in range(100):
            try:
                with socket.create_connection((_HOST, _PORT), timeout=0.3):
                    break
            except OSError:
                time.sleep(0.2)
        try:
            webbrowser.open(_URL)
        except Exception:
            pass

    threading.Thread(target=_auto_open_browser, daemon=True).start()

    print("=" * 56)
    print("  quant_review 一键启动 ->  %s" % _URL)
    print("  浏览器将自动打开; Ctrl+C 停止服务")
    print("=" * 56)

    # 3) 正式启动。不用 --reload: 这台机器上 uvicorn --reload 一改代码就崩
    #    (SystemError), 关掉最稳; 改代码后手动重跑本文件即可。
    uvicorn.run(app, host=_HOST, port=_PORT, reload=False)
