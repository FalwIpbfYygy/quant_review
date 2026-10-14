# -*- coding: utf-8 -*-
"""
参数化  整月消息面日历文档生成器（自包含，不依赖 FastAPI 服务）。

用法：
    python gen_month_doc.py --month 2026-10        # 指定年月
    python gen_month_doc.py                          # 默认下一个月
    python gen_month_doc.py --all 2026              # 生成某年 1-12 月全部

数据：
  - 排期推算 = month_cal.build_schedule_month()（官方排期锚点，source=schedule）
  - 金十实时 = jin10.get_calendar_week()（当前自然周真实行，source=jin10，
    仅当该月与当前周重叠时才有实质合并；否则本月为纯排期）
  - 行情头   = jin10.get_quotes([''])

输出：D:/quant_review/outputs/YYYY-MM_日历.md
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, json, argparse, calendar
from datetime import datetime, timedelta, date

# 使 D:/quant_review 可被 import（month_cal / jin10 在同目录）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

from core import month_cal
from data import jin10

_WD_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ★ 高优先级“月度焦点”识别：决定要不要自动写进“核心逻辑”与加高亮
_ANCHOR = {
    "FOMC": "利率决议/点阵图 → 定黄金中长期方向",
    "非农": "就业 → 定加息/降息预期 → 直击黄金",
    "CPI": "通胀核心前哨 → 影响利率定价",
    "PPI": "上游通胀，预演 CPI",
    "PCE": "美联储官方通胀锚",
    "GDP": "增长动能",
    "零售": "消费动能",
    "失业率": "就业强弱 → 利率预期",
}
# 高优先级关键词（含任意即进“月度焦点路径”）
_ANCHOR_KW = list(_ANCHOR.keys())


def _month_pivot(year, month, back=0):
    """默认取“下一个月”；back=1 时取上一个月（供复盘）。"""
    d = date(year, month, 1)
    # 目标 = 今天所在月的下 back 个月
    for _ in range(back + 1):
        ny, nm = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        d = date(ny, nm, 1)
    return d.year, d.month


def _star(n):
    n = max(0, min(5, n or 0))
    return "★" * n + "☆" * (5 - n)


import re as _re
def _title_disp(title):
    """🇺🇸/国别标识：美系主线加美国国旗；去掉标题里冗余的 (20:30) 尾巴。"""
    title = _re.sub(r"\(\d{2}:\d{2}\)$", "", title)
    if title.startswith("🇺🇸") or title.startswith("美国"):
        return title if title.startswith("🇺🇸") else "🇺🇸 " + title
    return title


def _state_badge(ev):
    if ev.get("source") == "jin10":
        st = (ev.get("extra") or {}).get("state", "")
        if st == "已公布":
            return "🟥金十实时·已公布", "jin"
        return "🟥金十实时·待公布", "jin"
    return "⬜排期推算", "sched"


def _act_cell(ev):
    ex = ev.get("extra") or {}
    st = ex.get("state", "")
    if st == "已公布":
        actual, prev = ex.get("actual"), ex.get("previous")
        affect = ex.get("affect_txt", "")
        ai = "🔴" if affect == "利空" else "🟢" if affect == "利多" else "⚪"
        return f"{ai}实际 **{actual}** · 前值 {prev}"
    if st == "待公布":
        return f"⏳预期 {ex.get('consensus')} · 前值 {ex.get('previous')}"
    return "—"


def _is_anchor(ev):
    return any(k in ev["title"] for k in _ANCHOR_KW)


def build_doc(year, month):
    """生成某月文档，返回 (out_path, summary_str)。"""
    today = date.today()
    # 金十当前周实时行（可能为空字符串列表；供合并）
    try:
        jrows = jin10.get_calendar_week()
    except Exception as e:
        print(f"[warn] jin10.get_calendar_week 失败({e})，本月将只用排期推算")
        jrows = []
    cal = month_cal.month_calendar(year, month, jin10_rows=jrows, today=today)

    # 行情头
    try:
        q = (jin10.get_quotes([""]) or {}).get("", {})
    except Exception as e:
        print(f"[warn] 取行情失败({e})")
        q = {}
    close, chg, high, low = q.get("close"), q.get("ups_percent"), q.get("high"), q.get("low")
    close = close or "—"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    cn_y = f"{year}年{month}月"
    L = []
    L.append(f"# 🔴 {cn_y}  重大事件时间线\n\n")
    L.append(f"实时行情：现货黄金现价 **${close}**（{chg}%，高低 {high}/{low}），"
             f"文档生成于 {now_str}（数据源：金十 MCP + 美国宏观官方排期锚点）\n\n")
    L.append("> 数据双源：🟥 **金十实时** = 当前自然周财经日历真实行（含实际值/前值/预期/利多利空）；"
             "⬜ **排期推算** = 美联储/BLS/商务部官方排期锚点推演（FOMC/非农/CPI/PPI/PCE/GDP/零售/JOLTS/ISM/初请）。"
             "跨周事件金十 MCP 不返回，故以排期推算为准。\n\n")

    # 逐周分节（周一开头，week_start 落当月则为当月周；跨月周并入上一节避免空章节）
    weeks = cal.get("weeks", [])
    # 收集每节的焦点行
    section_rows = []   # (sec_header, sub, [rows])
    cur_header = None
    cur_events = []
    for wk in weeks:
        ws = wk["week_start"]
        # 章节归属：week_start 在当月的 → 开新节；否则（上月末周）并入上一节
        if cur_header is not None and ws[:7] != "%04d-%02d" % (year, month):
            # 跨月周（week_start 落在上月）→ 并入当前节
            for e in wk["events"]:
                cur_events.append(e)
            continue
        if cur_header is not None:
            section_rows.append((cur_header, cur_events))
        # 计算本章日期范围显示
        ws_date = date.fromisoformat(ws)
        ws_cn = f"{ws_date.month}月{ws_date.day}日"
        we_date = ws_date + timedelta(days=6)
        # 若周末超出当月，截到月末
        last = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else \
            date(year, month + 1, 1) - timedelta(days=1)
        we_disp = min(we_date, last)
        # 计算包含该周开头的最小“第几周”标签
        first_monday = date(year, month, 1) - timedelta(days=date(year, month, 1).weekday())
        wk_num = (ws_date - first_monday).days // 7 + 1
        cur_header = (ws, wk_num, f"{ws_cn}–{we_disp.month}月{we_disp.day}日")
        cur_events = list(wk["events"])
    if cur_header is not None:
        section_rows.append((cur_header, cur_events))

    # 统计
    total = sum(len(e) for _, e in section_rows)
    src_stat = {}
    for _, evs in section_rows:
        for e in evs:
            src_stat[e.get("source", "?")] = src_stat.get(e.get("source", "?"), 0) + 1

    # 焦点路径：所有 anchor 行按时间排序
    anchor_events = []
    for _, evs in section_rows:
        for e in evs:
            if _is_anchor(e):
                anchor_events.append(e)
    anchor_events.sort(key=lambda x: (x["date"], x["time"]))
    top_anchor = [e for e in anchor_events if e.get("star", 0) >= 4]

    # 主体表
    for idx, (head, evs) in enumerate(section_rows, start=1):
        ws, wk_num, rng = head
        star5 = sum(1 for e in evs if e.get("star", 0) == 5)
        L.append(f"## 📅 第{wk_num}周 · {rng}（共{len(evs)}项，含5★{star5}项）\n\n")
        L.append("| 日期 | 时间 | 事件 | 重要性 | 来源/状态 | 实况 / 预期 |\n")
        L.append("|---|---|---|---|---|---|\n")
        for e in evs:
            d = date.fromisoformat(e["date"])
            md = f"{d.month}月{d.day}日（{_WD_CN[d.weekday()][1:]}）"
            sb, _ = _state_badge(e)
            L.append(f"| {md} | {e['time']} | {_title_disp(e['title'])} | {_star(e['star'])} | {sb} | {_act_cell(e)} |\n")
        # 本节约重点（star5 主线）
        foc = [e for e in evs if e.get("star", 0) >= 5]
        if foc:
            tips = []
            for e in foc:
                hint = e.get("hint") or ""
                k = next((k for k in _ANCHOR_KW if k in e["title"]), "")
                why = _ANCHOR.get(k, hint)
                if why:
                    tips.append(f"🔑 **{e['title']}**（{e['date'][5:]} {e['time']}）—— {why}")
            if tips:
                L.append("\n")
                for t in tips:
                    L.append(f"> {t}\n")
        L.append("\n")

    # 本月核心焦点路径（自动）
    L.append("## 📊 本月核心关注路径\n\n")
    if top_anchor:
        L.append("```\n")
        prev_d = None
        for e in top_anchor:
            mm, dd = e["date"][5:7], e["date"][8:10]
            tag = "　" if prev_d == (mm, dd) else ""
            L.append(f"{int(mm)}月{int(dd)}日{tag} {e['title']}（{e['time']}）\n")
            prev_d = (mm, dd)
        L.append("```\n\n")
        L.append("> 依次落地的 5★/4★ 主线事件将接力影响 ："
                 "数据读数好于预期→加息预期升温→美元强→黄金承压；低于预期→利多黄金。"
                 "最终以美联储措辞与点阵图为中长期基准。\n\n")
    else:
        L.append("> 本月暂无 FOMC/非农/CPI 等高星主线事件（以每周初请/区域数据为主），"
                 "黄金大概率随美元与避险情绪波动，需结合消息面快讯实时跟踪。\n\n")

    # 数据口径
    L.append("---\n\n")
    L.append("## 📚 数据口径与来源（务必读）\n\n")
    L.append(f"- 🟥 **金十实时**（{src_stat.get('jin10', 0)}项）：金十数据 MCP `list_calendar` 当前自然周真实行。"
             f"仅覆盖与当前周重叠的日期；已发生项带 actual/前值。\n")
    L.append(f"- ⬜ **排期推算**（{src_stat.get('schedule', 0)}项）：美联储 FOMC 日程 + BLS/商务部官方排期锚点"
             f"（非农/CPI/PPI/PCE/GDP/零售/JOLTS/ISM），已换算北京时刻；初请按每周四补齐。\n")
    L.append("- 金十 `list_calendar` **不接受参数、只返回当前自然周**，故未来周/月的事件无法从金十实时获得，"
             "只能按官方排期锚点推演并标注 ⬜。当目标月进入“当前自然周”时，金十实时会自动刷新覆盖。\n")
    L.append(f"- 本日历目标月：{cn_y}；生成时刻 {now_str}；如需历史复盘，金十实时会保留已公布 actual 供回溯。\n")
    L.append("- 本页为交易辅助工具，非投资建议；数据仅供决策参考，实盘风险自负。\n")

    out_path = os.path.join(OUT_DIR, f"{year:04d}-{month:02d}_日历.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(L)
    return out_path, total, src_stat


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYYY-MM")
    ap.add_argument("--all", type=int, default=None, help="生成某年1-12月全部")
    ap.add_argument("--back", type=int, default=0, help="相对下月再往前N个月(复盘用 back=1 表示上月)")
    a = ap.parse_args()

    if a.all:
        for m in range(1, 13):
            p, total, ss = build_doc(a.all, m)
            print(f"✅ {a.all}-{m:02d}: {p}  total={total} src={ss}")
    else:
        if a.month:
            y, m = int(a.month[:4]), int(a.month[5:7])
        else:
            y, m = _month_pivot(date.today().year, date.today().month, a.back)
        p, total, ss = build_doc(y, m)
        print(f"✅ {y}-{m:02d}: {p}  total={total} src={ss}")
