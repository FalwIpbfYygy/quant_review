import os
import time
import pymysql
import requests
from datetime import datetime
from utils import timer
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

# 抓取周期配置
# INTERVALS = ["1m"]
INTERVALS = ["1m", "5m", "15m", "30m"]

START_DATE = datetime(2026, 1, 1, 0, 0, 0)   # UTC起始时间
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

# ============ 写入模式开关【重要】 ============
# True = UPSERT 存在就更新(实时监控使用，刷新未收盘K线)
# False = INSERT IGNORE 只新增不覆盖(一次性历史回填使用)
USE_UPSERT = True


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
        # 存在冲突自动更新全部行情字段
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
        # 历史回填模式：冲突直接忽略
        full_sql = base_sql.replace("INSERT INTO", "INSERT IGNORE INTO")

    try:
        cursor.executemany(full_sql, data_list)
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
    print(f"写入模式: {'UPSERT(更新重复K线)' if USE_UPSERT else 'INSERT IGNORE(仅新增)'}")
    print(f"{'='*50}")

    page = 1
    while True:
        raw = fetch_klines_with_retry(interval, current_start)
        if not raw:
            print(f"  [警告] 未获取到数据，可能网络异常或已无新数据，终止该周期")
            break

        first_ts = raw[0][0]
        last_ts = raw[-1][0]
        first_time = datetime.utcfromtimestamp(first_ts / 1000).strftime('%Y-%m-%d %H:%M')
        last_time = datetime.utcfromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M')
        print(f"  第 {page} 页: {first_time} ~ {last_time} UTC, 共 {len(raw)} 条")

        parsed = parse_and_convert(raw)
        for i in range(0, len(parsed), BATCH_SIZE):
            batch = parsed[i:i+BATCH_SIZE]
            affected = insert_batch(cursor, table_name, batch)
            total_inserted += affected
            conn.commit()
            print(f"    → 本批影响行数 {affected} (累计 {total_inserted})")

        last_close = raw[-1][6]
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        is_near_now = (now_ms - last_close) < 300000   # 5分钟

        if is_near_now:
            print(f"  最后一条数据距今不足5分钟，已接近实时，结束抓取")
            break

        new_start = last_close + 1
        if new_start == current_start:
            print("  起始时间未变化，跳出循环防止死循环")
            break
        current_start = new_start
        page += 1
        time.sleep(0.3)

    cursor.close()
    conn.close()
    print(f"周期 {interval} 完成，总共影响 {total_inserted} 条记录")


@timer
def main():
    print("===== K线历史数据拉取开始 =====")
    print(f"交易对: {SYMBOL} 价格偏移 +{PRICE_OFFSET}")
    print(f"抓取周期: {INTERVALS}")
    print(f"起始UTC时间: {START_DATE.strftime('%Y-%m-%d %H:%M:%S')}")

    for interval in INTERVALS:
        fetch_and_store_interval(interval)

    print("\n✅ 所有周期数据拉取完成！")


if __name__ == "__main__":
    main()


