# paxg_fetch.py — 拉取 PAXGUSDT 现货 5m 全历史（后台运行）
import os, datetime as dt
import paxg_data as P

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rs_cache_PAXGUSDT_5m.csv")
START = (2020, 8, 28)   # PAXGUSDT 现货最早可用
END   = (2026, 10, 3)   # 含至今

print(f"[FETCH] 起点 {START} 终点 {END}")
rows = P.get_5m("PAXGUSDT", START, END, CACHE)
print(f"[FETCH] 完成：{len(rows)} 根 5m")
print(f"[FETCH] 区间 {P.beijing_str(rows[0]['open_time'])} ~ {P.beijing_str(rows[-1]['open_time'])}")
