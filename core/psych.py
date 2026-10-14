"""交易心理模块「心锚 · Composure」后端（v1：纯记录起步，本地 JSON 存储）。

设计原则（与现有系统一致，纯加法，不动回测/信号逻辑）：
- 数据落本地 JSON（psych_data/psych.json），不依赖 MySQL。
- 仅提供 增/查/删/统计 四个原子能力，复杂计算（情绪税、纪律分）留前端或后续版本。
- 所有写入走原子替换（写临时文件再 os.replace），避免并发写损坏。

记录结构（前端自由组织，后端只保证 scenario 合法 + 附带 id/created_at）：
  { scenario: 'pre'|'in'|'post', pre?: {...}, in?: {...}, post?: {...} }
"""
import os
import json
import time
import threading
from datetime import datetime

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psych_data")
_DATA_FILE = os.path.join(_DATA_DIR, "psych.json")
_LOCK = threading.Lock()
_VALID_SCENARIOS = ("pre", "in", "post")


def _ensure():
    os.makedirs(_DATA_DIR, exist_ok=True)
    if not os.path.exists(_DATA_FILE):
        with open(_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"records": []}, f, ensure_ascii=False)


def _load():
    _ensure()
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"records": []}


def _save(data):
    _ensure()
    tmp = _DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _DATA_FILE)


def add_record(payload: dict):
    """保存一条心理记录。payload 需含 scenario。返回 {code,msg,id,record}。"""
    if not isinstance(payload, dict):
        return {"code": 400, "msg": "payload 必须是对象"}
    scenario = payload.get("scenario")
    if scenario not in _VALID_SCENARIOS:
        return {"code": 400, "msg": "scenario 必须是 pre / in / post 之一"}
    with _LOCK:
        data = _load()
        rec = dict(payload)
        rec["id"] = int(time.time() * 1000)
        rec["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["records"].append(rec)
        _save(data)
    return {"code": 200, "msg": "已保存", "id": rec["id"], "record": rec}


def list_records(scenario=None, limit=200):
    """列出记录（倒序）。可按 scenario 过滤。"""
    with _LOCK:
        data = _load()
    recs = data.get("records", [])
    if scenario:
        recs = [r for r in recs if r.get("scenario") == scenario]
    recs = sorted(recs, key=lambda r: r.get("created_at", ""), reverse=True)
    total = len(recs)
    if limit and limit > 0:
        recs = recs[:limit]
    return {"code": 200, "records": recs, "total": total}


def delete_record(rid):
    """按 id 删除一条记录。"""
    with _LOCK:
        data = _load()
        before = len(data.get("records", []))
        data["records"] = [r for r in data.get("records", []) if str(r.get("id")) != str(rid)]
        after = len(data["records"])
        if before == after:
            return {"code": 404, "ok": False, "msg": "记录不存在"}
        _save(data)
    return {"code": 200, "ok": True}


def get_stats():
    """聚合统计：支撑「手痒少赚 Y u」「情绪税」「纪律分均值」等展示。"""
    with _LOCK:
        data = _load()
    recs = data.get("records", [])
    stats = {
        "total": len(recs),
        "by_scenario": {"pre": 0, "in": 0, "post": 0},
        "discipline_avg": None,
        "premature_close": 0,
        "missed_profit_sum": 0.0,
        "urge_total": 0,
        "top_emotions": {},
    }
    disc = []
    emotions = {}
    for r in recs:
        sc = r.get("scenario")
        if sc in stats["by_scenario"]:
            stats["by_scenario"][sc] += 1
        if sc == "post":
            post = r.get("post", {}) or {}
            ds = post.get("discipline_score")
            if isinstance(ds, (int, float)):
                disc.append(ds)
            if post.get("premature_close"):
                stats["premature_close"] += 1
            mp = post.get("missed_profit")
            if isinstance(mp, (int, float)):
                stats["missed_profit_sum"] += mp
            em = post.get("emotion")
            if em:
                emotions[em] = emotions.get(em, 0) + 1
        if sc == "in":
            ue = (r.get("in", {}) or {}).get("urge_events") or []
            stats["urge_total"] += len(ue)
    if disc:
        stats["discipline_avg"] = round(sum(disc) / len(disc), 2)
    stats["missed_profit_sum"] = round(stats["missed_profit_sum"], 2)
    stats["top_emotions"] = dict(sorted(emotions.items(), key=lambda x: -x[1])[:5])
    return {"code": 200, "stats": stats}
