import pymysql
from dbutils.pooled_db import PooledDB
from config import DB_HOST, DB_USER, DB_PASS, DB_NAME

MAX_ROWS = 10000

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = PooledDB(
            creator=pymysql,
            maxconnections=5,
            mincached=2,
            maxcached=5,
            blocking=True,
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    return _pool


def query_kline(table_name, start_ts, end_ts):
    """
    查询历史K线，返回 (rows, truncated)
    - rows: K线数据列表
    - truncated: 是否因超过 MAX_ROWS 被截断
    """
    conn = _get_pool().connection()
    cur = conn.cursor()
    try:
        sql = """
        SELECT open_time, open_price, high_price, low_price, close_price, volume, close_time
        FROM `{}`
        WHERE open_time >= %s AND open_time <= %s
        AND open_price IS NOT NULL
        AND close_price IS NOT NULL
        ORDER BY open_time ASC
        LIMIT %s
        """.format(table_name)
        cur.execute(sql, (start_ts, end_ts, MAX_ROWS + 1))
        rows = cur.fetchall()
        truncated = len(rows) > MAX_ROWS
        if truncated:
            rows = rows[:MAX_ROWS]
        return rows, truncated
    finally:
        cur.close()
        conn.close()