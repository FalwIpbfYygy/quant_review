
import os
import time
import pymysql
import requests
from datetime import datetime
# 如有timer工具保留，没有则注释掉
# from utils import timer

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
from config import SPOT_KLINES as BINANCE_URL
PRICE_OFFSET = 12.0

# 抓取周期
INTERVALS = ["1m", "5m", "15m", "30m"]

# 首次建表无数据时的默认起始时间（兜底）
FALLBACK_START_DATE = datetime(2026, 1, 1, 0, 0, 0)

LIMIT = 1000
BATCH_SIZE = 500
MAX_RETRIES = 5
RETRY_DELAY = 2

TABLE_MAP = {
    "1m": "kline_1m",
    "5m": "kline_5m",
    "15m": "kline_15m",
    "30m": "kline_30m",
}

# True=更新未收盘K线(实时维护)  False=纯追加(复盘静态数据推荐)
USE_UPSERT = False


def get_db_conn():
    """获取数据库连接"""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        autocommit=False
    )


def get_last_db_time(table_name: str) -> int:
    """
    读取数据库当前表最后一条close_time
    :return: 时间戳ms / 空表返回0
    """
    conn = get_db_conn()
    cursor = conn.cursor()
    sql = f"SELECT close_time FROM `{table_name}` ORDER BY close_time DESC LIMIT 1"
    cursor.execute(sql)
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    if res:
        return int(res[0])
    return 0


def fetch_klines_with_retry(interval, start_ms):
    """带重试的K线请求，容错优化"""
    url = f"{BINANCE_URL}?symbol={SYMBOL}&interval={interval}&startTime={start_ms}&limit={LIMIT}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                print(f"  请求成功 (尝试 {attempt}/{MAX_RETRIES})")
                return resp.json()
            else:
                print(f"  请求失败 HTTP {resp.status_code} (尝试 {attempt}/{MAX_RETRIES})")
        except Exception as e:
            print(f"  请求异常 (尝试 {attempt}/{MAX_RETRIES}): {str(e)[:80]}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
    return []


def parse_and_convert(raw_data):
    """数据清洗转换"""
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
    """批量插入/更新数据"""
    if not data_list:
        return 0

    base_sql = f"""
        INSERT INTO `{table_name}` (
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
    if USE_UPSERT:
        full_sql = base_sql + """
        ON DUPLICATE KEY UPDATE
            open_price=VALUES(open_price),
            high_price=VALUES(high_price),
            low_price=VALUES(low_price),
            close_price=VALUES(close_price),
            volume=VALUES(volume),
            close_time=VALUES(close_time),
            quote_volume=VALUES(quote_volume),
            trades=VALUES(trades),
            taker_buy_base=VALUES(taker_buy_base),
            taker_buy_quote=VALUES(taker_buy_quote),
            ignore_field=VALUES(ignore_field)
        """
    else:
        full_sql = base_sql.replace("INSERT INTO", "INSERT IGNORE INTO")

    try:
        cursor.executemany(full_sql, data_list)
        return cursor.rowcount
    except Exception as e:
        print(f"  批量插入失败: {e}")
        return 0


def fetch_and_store_interval(interval):
    table_name = TABLE_MAP[interval]

    # 核心优化：自动读取数据库最后时间
    last_db_ts = get_last_db_time(table_name)
    if last_db_ts > 0:
        current_start = last_db_ts + 1
        print(f"\n【增量模式】表 {table_name} 最后时间戳: {last_db_ts}")
    else:
        # 空表使用兜底初始时间
        current_start = int(FALLBACK_START_DATE.timestamp() * 1000)
        print(f"\n【全量回填模式】表 {table_name} 为空，从默认时间开始")

    total_inserted = 0
    conn = get_db_conn()
    cursor = conn.cursor()

    print(f"{'='*60}")
    print(f"开始处理周期: {interval} -> {table_name}")
    print(f"写入模式: {'UPSERT更新' if USE_UPSERT else 'INSERT只读追加(复盘专用)'}")
    print(f"{'='*60}")

    page = 1
    while True:
        raw = fetch_klines_with_retry(interval, current_start)
        if not raw:
            print(f"  [结束] 无更多数据，当前周期抓取完成")
            break

        first_ts = raw[0][0]
        last_ts = raw[-1][0]
        first_time = datetime.utcfromtimestamp(first_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
        last_time = datetime.utcfromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  第{page}页 | {first_time} ~ {last_time} | 条数:{len(raw)}")

        parsed = parse_and_convert(raw)
        for i in range(0, len(parsed), BATCH_SIZE):
            batch = parsed[i:i+BATCH_SIZE]
            affected = insert_batch(cursor, table_name, batch)
            total_inserted += affected
            conn.commit()
            print(f"    批量入库成功: 本批{affected}条 | 累计{total_inserted}条")

        # 判断是否抓取到最新实时数据，结束循环
        last_close = raw[-1][6]
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        if (now_ms - last_close) < 300000:
            print(f"  [完结] 已追到最新行情，周期结束")
            break

        new_start = last_close + 1
        if new_start == current_start:
            print("  [防死循环] 时间无更新，跳出")
            break
        current_start = new_start
        page += 1
        time.sleep(0.3)

    cursor.close()
    conn.close()
    print(f"\n✅ 周期 {interval} 完成，总计入库 {total_inserted} 条K线")


# @timer
def main():
    print("===== 【全自动断点续传 K线爬取】启动 =====")
    print(f"标的: {SYMBOL} | 价格偏移: +{PRICE_OFFSET}")
    print(f"周期列表: {INTERVALS}")

    for interval in INTERVALS:
        fetch_and_store_interval(interval)

    print("\n🎉 全部周期数据抓取完毕！")


if __name__ == "__main__":
    main()
