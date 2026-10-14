# -*- coding: utf-8 -*-
"""
数据同步模块（从 scripts/x26_parse_close_time.py 提炼）
- 同步数据库：建/校验 4 张 kline_*m 表
- 同步数据：从 Binance 抓 PAXGUSDT K线（+12 偏移），按 close_time 增量入 MySQL
"""
import os
import time
import threading
import pymysql
import requests
from datetime import datetime
from config import DB_HOST, DB_USER, DB_PASS, DB_NAME, TABLE_MAP, BINANCE_SPOT_BASE, PROXIES


# ==================== 数据源配置（与 scripts/x26_parse_close_time.py 一致） ====================
SYMBOL = "PAXGUSDT"
BINANCE_URL = BINANCE_SPOT_BASE + "/api/v3/klines"
PRICE_OFFSET = 12.0
INTERVALS = ["1m", "5m", "15m", "30m"]
FALLBACK_START_DATE = datetime(2026, 1, 1, 0, 0, 0)
LIMIT = 1000
BATCH_SIZE = 500
MAX_RETRIES = 5
RETRY_DELAY = 2
# PROXIES 统一来自 config（默认直连，本地代理在 .env 设 KLINE_PROXY）


# ==================== 全局进度容器（线程安全） ====================
_state = {
    "running": False,
    "task": None,            # "db" / "data" / None
    "logs": [],              # [{time, level, msg}, ...] 最新300条
    "summary": None,         # 任务完成后的汇总
    "started_at": None,
    "finished_at": None,
}
_lock = threading.Lock()


def _log(level: str, msg: str):
    with _lock:
        _state["logs"].append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,  # info / ok / warn / err
            "msg": msg,
        })
        if len(_state["logs"]) > 300:
            _state["logs"] = _state["logs"][-300:]


def get_status() -> dict:
    with _lock:
        return {
            "running": _state["running"],
            "task": _state["task"],
            "logs": list(_state["logs"]),
            "summary": _state.get("summary"),
            "started_at": _state.get("started_at"),
            "finished_at": _state.get("finished_at"),
        }


def _reset():
    with _lock:
        _state["running"] = True
        _state["task"] = None
        _state["logs"] = []
        _state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _state["finished_at"] = None
        _state["summary"] = None


def _finish(summary: dict):
    with _lock:
        _state["running"] = False
        _state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _state["summary"] = summary


def _new_conn():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )


# ==================== 建表 ====================
def ensure_tables() -> dict:
    """4 张 kline_*m 表（如不存在则建，统一宽表+复合唯一键）"""
    tables = []
    conn = _new_conn()
    try:
        cur = conn.cursor()
        for iv in INTERVALS:
            table_name = TABLE_MAP[iv]
            sql = f"""
            CREATE TABLE IF NOT EXISTS `{table_name}` (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL DEFAULT '',
                open_time BIGINT NOT NULL,
                open_price DECIMAL(20, 8) NOT NULL,
                high_price DECIMAL(20, 8) NOT NULL,
                low_price DECIMAL(20, 8) NOT NULL,
                close_price DECIMAL(20, 8) NOT NULL,
                volume DECIMAL(30, 12) NOT NULL DEFAULT 0,
                close_time BIGINT NOT NULL,
                quote_volume DECIMAL(30, 12) NULL,
                trades INT NULL,
                taker_buy_base DECIMAL(30, 12) NULL,
                taker_buy_quote DECIMAL(30, 12) NULL,
                ignore_field BIGINT NULL,
                UNIQUE KEY uk_close_time (close_time, symbol),
                INDEX idx_open_time (open_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
            cur.execute(sql)
            conn.commit()
            tables.append(table_name)
            _log("ok", f"✓ 已确认表 `{table_name}` 就绪")
    finally:
        conn.close()
    return {"tables": tables}


# ==================== 抓取 + 入库 ====================
def _get_last_db_time(cur, table_name: str) -> int:
    cur.execute(f"SELECT close_time FROM `{table_name}` ORDER BY close_time DESC LIMIT 1")
    res = cur.fetchone()
    return int(res[0]) if res else 0


def _fetch_with_retry(interval: str, start_ms: int):
    url = f"{BINANCE_URL}?symbol={SYMBOL}&interval={interval}&startTime={start_ms}&limit={LIMIT}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=10, proxies=PROXIES)
            if resp.status_code == 200:
                _log("ok", f"  [{interval}] 请求成功（尝试 {attempt}/{MAX_RETRIES}）")
                return resp.json()
            _log("warn", f"  [{interval}] HTTP {resp.status_code}（尝试 {attempt}/{MAX_RETRIES}）")
        except Exception as e:
            _log("warn", f"  [{interval}] 异常（尝试 {attempt}/{MAX_RETRIES}）: {str(e)[:80]}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
    return []


def _parse_and_convert(raw_data):
    result = []
    for k in raw_data:
        result.append({
            "symbol": SYMBOL,
            "open_time": int(k[0]),
            "open_price": float(k[1]) + PRICE_OFFSET,
            "high_price": float(k[2]) + PRICE_OFFSET,
            "low_price": float(k[3]) + PRICE_OFFSET,
            "close_price": float(k[4]) + PRICE_OFFSET,
            "volume": float(k[5]),
            "close_time": int(k[6]),
            "quote_volume": float(k[7]) if k[7] else None,
            "trades": int(k[8]) if k[8] else None,
            "taker_buy_base": float(k[9]) if k[9] else None,
            "taker_buy_quote": float(k[10]) if k[10] else None,
            "ignore_field": int(k[11]) if k[11] else 0,
        })
    return result


def _insert_batch(cur, table_name: str, data_list) -> int:
    if not data_list:
        return 0
    sql = f"""
    INSERT IGNORE INTO `{table_name}` (
        symbol, open_time, open_price, high_price, low_price,
        close_price, volume, close_time, quote_volume,
        trades, taker_buy_base, taker_buy_quote, ignore_field
    ) VALUES (
        %(symbol)s, %(open_time)s, %(open_price)s, %(high_price)s,
        %(low_price)s, %(close_price)s, %(volume)s, %(close_time)s,
        %(quote_volume)s, %(trades)s, %(taker_buy_base)s,
        %(taker_buy_quote)s, %(ignore_field)s
    )
    """
    cur.executemany(sql, data_list)
    return cur.rowcount


def _fetch_and_store_interval(interval: str) -> int:
    table_name = TABLE_MAP[interval]
    conn = _new_conn()
    total = 0
    try:
        cur = conn.cursor()
        last_db_ts = _get_last_db_time(cur, table_name)
        if last_db_ts > 0:
            current_start = last_db_ts + 1
            _log("info", f"【增量模式】{table_name} 最后时间戳: {last_db_ts}")
        else:
            current_start = int(FALLBACK_START_DATE.timestamp() * 1000)
            _log("info", f"【全量回填】{table_name} 为空，从 {FALLBACK_START_DATE} 开始")

        _log("info", f"{'=' * 30} 周期 {interval} -> {table_name} {'=' * 30}")
        page = 1
        while True:
            raw = _fetch_with_retry(interval, current_start)
            if not raw:
                _log("info", f"  [结束] {interval} 无更多数据")
                break

            first_ts = raw[0][0]
            last_ts = raw[-1][0]
            first_t = datetime.utcfromtimestamp(first_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
            last_t = datetime.utcfromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
            _log("info", f"  第{page}页 | {first_t} ~ {last_t} | {len(raw)}条")

            parsed = _parse_and_convert(raw)
            for i in range(0, len(parsed), BATCH_SIZE):
                batch = parsed[i:i + BATCH_SIZE]
                try:
                    affected = _insert_batch(cur, table_name, batch)
                    conn.commit()
                    total += affected
                except Exception as e:
                    conn.rollback()
                    _log("err", f"  批量入库失败: {e}")

            # 追到最新就停
            last_close = raw[-1][6]
            now_ms = int(datetime.utcnow().timestamp() * 1000)
            if (now_ms - last_close) < 300000:
                _log("info", f"  [完结] {interval} 已追到最新行情")
                break

            new_start = last_close + 1
            if new_start == current_start:
                _log("warn", "  [防死循环] 时间无更新，跳出")
                break
            current_start = new_start
            page += 1
            time.sleep(0.3)

        _log("ok", f"✅ 周期 {interval} 完成，累计入库 {total} 条")
        return total
    finally:
        conn.close()


# ==================== 后台入口 ====================
def run_ensure_tables_bg():
    """后台：建表（秒完）"""
    if _state["running"]:
        _log("warn", "已有任务在跑，跳过本次建表请求")
        return
    _reset()
    _state["task"] = "db"
    _log("info", "🚀 开始同步数据库（建表）...")
    try:
        info = ensure_tables()
        _log("info", f"✅ 数据库同步完成：{', '.join(info['tables'])}")
        _finish({"db": info})
    except Exception as e:
        _log("err", f"❌ 同步数据库失败：{type(e).__name__}: {e}")
        _finish({"error": f"{type(e).__name__}: {e}"})


def run_fetch_all_bg():
    """后台：抓取 4 个周期的最新数据，先确保表存在"""
    if _state["running"]:
        _log("warn", "已有任务在跑，跳过本次抓取请求")
        return
    _reset()
    _state["task"] = "data"
    _log("info", f"🚀 开始同步数据（{', '.join(INTERVALS)}，抓币安 {SYMBOL}）...")
    summary = {}
    try:
        # 先建表
        ensure_tables()
        # 再抓数据
        for iv in INTERVALS:
            n = _fetch_and_store_interval(iv)
            summary[iv] = n
        _log("info", f"🎉 全部周期同步完成：{summary}")
        _finish({"data": summary})
    except Exception as e:
        _log("err", f"❌ 同步数据失败：{type(e).__name__}: {e}")
        _finish({"error": f"{type(e).__name__}: {e}"})
