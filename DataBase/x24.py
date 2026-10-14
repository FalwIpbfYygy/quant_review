'''''




'''

import os
import time
import pymysql
import requests
from datetime import datetime

# ==================== 代理配置（默认直连，按需启用） ====================
# 本地出网需代理 → 设环境变量 KLINE_PROXY / HTTP_PROXY / HTTPS_PROXY；留空=直连。
_proxy = os.environ.get("KLINE_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
if _proxy:
    os.environ["HTTP_PROXY"] = _proxy
    os.environ["HTTPS_PROXY"] = _proxy

# ==================== 数据库配置（来自环境变量，不留明文） ====================
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "")

# ==================== 数据源配置 ====================
SYMBOL = "PAXGUSDT"
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from config import SPOT_KLINES as BINANCE_URL  # 现货API
PRICE_OFFSET = 12.0

INTERVALS = ["1m"]
# INTERVALS = ["1m", "5m", "15m", "30m"]

START_DATE = datetime(2026, 5, 14, 16, 0, 0)   # UTC
LIMIT = 1000              # ✅ 改为合法最大值
BATCH_SIZE = 500
MAX_RETRIES = 5
RETRY_DELAY = 2

TABLE_MAP = {
    "1m": "kline_1m",
    # "5m": "kline_5m",
    # "15m": "kline_15m",
    # "30m": "kline_30m",
}


def get_db_conn():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        autocommit=False
    )


def fetch_klines_with_retry(interval, start_ms):
    url = f"{BINANCE_URL}?symbol={SYMBOL}&interval={interval}&startTime={start_ms}&limit={LIMIT}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url,)
            if resp.status_code == 200:
                # 请求成功打印
                print(f"  请求成功 (尝试 {attempt}/{MAX_RETRIES})")
                return resp.json()
            else:
                print(f"  请求失败 (尝试 {attempt}/{MAX_RETRIES})，状态码: {resp.status_code}")
        except Exception as e:
            print(f"  请求异常 (尝试 {attempt}/{MAX_RETRIES}): {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
    return []


def parse_and_convert(raw_data):
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


def insert_batch(cursor, table_name, data_list):
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
    try:
        cursor.executemany(sql, data_list)
        return cursor.rowcount
    except Exception as e:
        print(f"  批量插入失败: {e}")
        return 0


def fetch_and_store_interval(interval):
    table_name = TABLE_MAP[interval]
    start_ts = int(START_DATE.timestamp() * 1000)
    total_inserted = 0
    current_start = start_ts
    conn = get_db_conn()
    cursor = conn.cursor()

    print(f"\n{'='*50}")
    print(f"开始处理周期: {interval} -> 表 {table_name}")
    print(f"起始时间: {START_DATE.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*50}")

    page = 1
    while True:
        raw = fetch_klines_with_retry(interval, current_start)
        if not raw:
            print(f"  [警告] 未获取到数据，可能网络异常或已无新数据，终止该周期")
            break

        # 显示拉取范围
        first_ts = raw[0][0]
        last_ts = raw[-1][0]
        first_time = datetime.utcfromtimestamp(first_ts / 1000).strftime('%Y-%m-%d %H:%M')
        last_time = datetime.utcfromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M')
        print(f"  第 {page} 页: {first_time} ~ {last_time} UTC, 共 {len(raw)} 条")

        parsed = parse_and_convert(raw)
        for i in range(0, len(parsed), BATCH_SIZE):
            batch = parsed[i:i+BATCH_SIZE]
            inserted = insert_batch(cursor, table_name, batch)
            total_inserted += inserted
            conn.commit()
            print(f"    → 本批插入 {inserted} 条 (累计 {total_inserted})")

        # ✅ 修复后的退出判断：
        # 条件1：如果返回条数 < LIMIT，可能是数据已结束，但还要检查最后一条是否接近当前时间
        # 条件2：如果最后一条 close_time 距当前时间 < 5 分钟，则认为已到最新
        last_close = raw[-1][6]   # close_time (毫秒)
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        is_near_now = (now_ms - last_close) < 300000   # 5分钟

        if len(raw) < LIMIT:
            if is_near_now:
                print(f"  返回数据不足 {LIMIT} 条且最后一条距今不足5分钟，已拉取至最新，结束")
                break
            else:
                # 虽然条数不足，但时间还没到最新，可能是因为该段时间数据确实稀疏（比如大周期），但应该继续请求
                # 对于 1m/5m 等高频，如果不足，通常就是真的结束了，但为了保险，我们继续请求
                # 但为避免死循环，如果 current_start 没有变化，则 break
                pass

        # 如果 last_close 距离当前时间 < 5 分钟，结束
        if is_near_now:
            print(f"  最后一条数据距今不足5分钟，已接近实时，结束")
            break

        # 更新起始时间（避免重复）
        new_start = last_close + 1
        if new_start == current_start:
            print("  起始时间未变化，跳出循环防止死循环")
            break
        current_start = new_start
        page += 1
        time.sleep(0.3)

    cursor.close()
    conn.close()
    print(f"周期 {interval} 完成，共插入 {total_inserted} 条记录")


def main():
    print("=====  多周期历史数据拉取开始 =====")
    print(f"数据源: {SYMBOL} + {PRICE_OFFSET} = ")
    print(f"周期: {INTERVALS}")
    print(f"起始日期: {START_DATE.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    for interval in INTERVALS:
        fetch_and_store_interval(interval)

    print("\n所有周期数据拉取完成！")


if __name__ == "__main__":
    main()