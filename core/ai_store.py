"""
AI 复盘报告历史库（本地 JSON 持久化，不依赖 MySQL）

- 每次 /review 页面生成 AI 复盘报告后，由 main.py 自动调用 save() 入库。
- 一条记录包含：生成时间、AI 报告全文、回测摘要(含现算的整体胜率/总盈亏)、
  策略统计、原始信号表(精简)、涉及品种。
- 列表接口直接返回全部记录（含报告全文，本地使用足够）。
"""
import os
import json
import uuid
import threading
from datetime import datetime

_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_history.json")
_lock = threading.Lock()


def _load():
    if not os.path.exists(_HISTORY_FILE):
        return []
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_all(records):
    tmp = _HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _HISTORY_FILE)


def _derive_meta(result):
    """从动笔 trades 现算整体胜率与总盈亏（summary 里没有这两个字段）。"""
    trades = result.get("trades", []) or []
    closed = [t for t in trades if t.get("closed")]
    wins = sum(1 for t in closed if (t.get("pnl_u") or 0) > 0)
    n_closed = len(closed)
    total_pnl = round(sum((t.get("pnl_u") or 0) for t in closed), 2)
    win_rate = round(wins / n_closed, 3) if n_closed else 0
    return win_rate, total_pnl


def _build_rec(report, result, rid=None, conversation=None):
    """构造一条记录 dict；rid 给定时用作 id（用于 upsert 同 id）。"""
    win_rate, total_pnl = _derive_meta(result or {})
    summary = (result or {}).get("summary", {}) or {}
    data_range = (result or {}).get("data_range", {}) or {}
    trades = (result or {}).get("trades", []) or []
    signals = [{
        "signal_time": t.get("signal_time"),
        "symbol": t.get("symbol"),
        "interval": t.get("interval"),
        "pattern": t.get("pattern"),
        "direction": t.get("direction"),
        "entry": t.get("entry"),
        "sl": t.get("sl"),
        "tp1": t.get("tp1"),
        "tp2": t.get("tp2"),
        "result": t.get("result"),
        "pnl_u": t.get("pnl_u"),
    } for t in trades]
    symbols = sorted({s.get("symbol") for s in signals if s.get("symbol")})
    now = datetime.now()
    return {
        "id": rid if rid else now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "created_ts": int(now.timestamp() * 1000),
        "report": report if report is not None else "",
        "preview": ((report or "").strip().replace("\n", " ")[:140]),
        "data_range": data_range,
        "summary": {**summary, "win_rate": win_rate, "total_pnl": total_pnl},
        "strategy_stats": (result or {}).get("strategy_stats", []),
        "symbols": symbols,
        "signals": signals,
        "conversation": conversation,  # 新增：多轮对话（不含 system），None 表示单报告
        "type": "chat" if conversation is not None else "summary",
    }


def save(report=None, result=None, conversation=None, rid=None):
    """保存/更新一条 AI 复盘记录，返回记录 dict。

    - 旧调用 save(report, result) 行为不变：新增一条 summary 记录。
    - 传 rid 时按 id upsert：存在则更新 conversation（不改动报告/摘要），不存在则以 rid 为 id 新增
      （首轮对话建会话时即落到已存在的 summary 记录上）。
    """
    with _lock:
        records = _load()
        if rid is not None:
            for rec in records:
                if rec.get("id") == rid:
                    rec["conversation"] = conversation
                    rec["type"] = "chat"
                    _save_all(records)
                    return rec
            # 记录不存在 → 以 rid 为 id 新增
            rec = _build_rec(report, result, rid=rid, conversation=conversation)
            records.append(rec)
            _save_all(records)
            return rec
        rec = _build_rec(report, result, conversation=conversation)
        records.append(rec)
        _save_all(records)
        return rec


def get(rid):
    """按 id 读取单条记录（供会话重建）。"""
    with _lock:
        records = _load()
    for r in records:
        if r.get("id") == rid:
            return r
    return None


def list_all():
    with _lock:
        records = _load()
    records.sort(key=lambda r: r.get("created_ts", 0), reverse=True)
    return records


def delete(rid):
    with _lock:
        records = _load()
        new = [r for r in records if r.get("id") != rid]
        if len(new) == len(records):
            return False
        _save_all(new)
        return True


