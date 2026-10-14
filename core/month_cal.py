# -*- coding: utf-8 -*-
"""
整月  消息面日历生成器（新增模块，不改动既有 main.py / jin10.py 逻辑）

目标：给定某一年-月，输出该自然月的  强相关消息面事件日历（按周分组）。

数据双源（绝不混淆，逐条带 source 标注）：
  1. schedule  定期排期推算 —— 依据美联储/BLS 官方已公布的 2026 年度固定排期锚点，
     把 FOMC / 非农 / CPI / PPI / PCE / GDP / 零售 / JOLTS / 初请(每周四) /
     ISM PMI(月初) / 密歇根消费者信心 等推演到指定月份。带时间(已换算北京时间)与星级。
  2. jin10     金十实时 —— 当请求月份与「当前自然周」重叠时，用 list_calendar 的
     真实行(actual/consensus/previous/star/affect_txt)覆盖/补充，已发生事件标「已公布」，
     当周未来事件标「待公布」。

准确性声明：schedule 行来自官方 2026 排期规律推导，逐条 source=schedule；
jin10 行为金十当前周实时数据，source=jin10。凡非本周的事件无法从金十 MCP 实时
获取（list_calendar 仅返回当前自然周且不接受参数），一律只给排期推算并注明口径。
"""
import os
import json
import re
from datetime import datetime, timedelta, date

# ── 时区换算：ET -> 北京(+12/13)。夏令时(3月中~11月初)北京=ET+12，否则+13。 ──
# 简化：美国多数数据 8:30 ET / 10:00 ET / 14:00 ET；直接给北京固定时刻，见下方常量。

# ============ 黄金利空/利多方向 + 星级（用于排期行的注释） ============
GOLD_BULLISH_HINT = "通常利空美元→利多黄金"
GOLD_BEARISH_HINT = "通胀强→加息预期→利空黄金(需看读数)"
# 下面仅为"市场关注方向"提示，不做预测。

# ============ 官方 2026 排期锚点（美联储 + BLS，web 校验，2026-09-04 核对） ============
# FOMC 决议日（北京次日 02:00）；* 为含 SEP/点阵图的季度会议
FOMC_2026 = {
    "2026-09-16": {"star": 5, "sep": True,  "label": "FOMC 利率决议(9/15-16会议)+SEP点阵图"},
    "2026-10-28": {"star": 5, "sep": False, "label": "FOMC 利率决议(10/27-28会议)"},
    "2026-12-09": {"star": 5, "sep": True,  "label": "FOMC 利率决议(12/8-9会议)+SEP点阵图"},
}
# FOMC 决议后次日 02:30 主席记者会；会议前约 2 周发布褐皮书(Beige Book)
FOMC_PRESS_2026 = {
    "2026-09-16": "美联储主席沃什新闻发布会(决议后02:30)",
    "2026-10-28": "美联储主席沃什新闻发布会(决议后02:30)",
    "2026-12-09": "美联储主席沃什新闻发布会(决议后02:30)",
}

# BLS 就业报告（非农/失业率/时薪），8:30 ET = 北京 20:30
NONFARM_2026 = {
    "2026-09-04": {"star": 5, "label": "美国8月非农就业人口+失业率+平均时薪"},
    "2026-10-02": {"star": 5, "label": "美国9月非农就业人口+失业率+平均时薪"},
    "2026-11-06": {"star": 5, "label": "美国10月非农就业人口+失业率+平均时薪"},
    "2026-12-04": {"star": 5, "label": "美国11月非农就业人口+失业率+平均时薪"},
}
# CPI，8:30 ET = 北京 20:30
CPI_2026 = {
    "2026-09-11": {"star": 5, "label": "美国8月 CPI(消费者物价指数)"},
    "2026-10-14": {"star": 5, "label": "美国9月 CPI(消费者物价指数)"},
    "2026-11-10": {"star": 5, "label": "美国10月 CPI(消费者物价指数)"},
    "2026-12-10": {"star": 5, "label": "美国11月 CPI(消费者物价指数)"},
}
# PPI，8:30 ET = 北京 20:30
PPI_2026 = {
    "2026-09-10": {"star": 3, "label": "美国8月 PPI(生产者物价指数)"},
    "2026-10-15": {"star": 3, "label": "美国9月 PPI(生产者物价指数)"},
    "2026-11-13": {"star": 3, "label": "美国10月 PPI(生产者物价指数)"},
    "2026-12-11": {"star": 3, "label": "美国11月 PPI(生产者物价指数)"},
}
# PCE（PCE物价 + 个人收支），由 BEA 发布
PCE_2026 = {
    "2026-09-30": {"star": 4, "label": "美国8月 PCE物价指数+个人收支"},
    "2026-10-29": {"star": 4, "label": "美国9月 PCE物价指数+个人收支"},
    "2026-11-25": {"star": 4, "label": "美国10月 PCE物价指数+个人收支"},
    "2026-12-22": {"star": 4, "label": "美国11月 PCE物价指数+个人收支"},
}
# GDP（BEA）
GDP_2026 = {
    "2026-09-30": {"star": 3, "label": "美国Q2 GDP终值"},
    "2026-10-29": {"star": 3, "label": "美国Q3 GDP初值"},
    "2026-12-22": {"star": 3, "label": "美国Q3 GDP终值"},
}
# 零售销售（Census）
RETAIL_2026 = {
    "2026-09-16": {"star": 3, "label": "美国8月零售销售月率"},
    "2026-10-15": {"star": 3, "label": "美国9月零售销售月率"},
    "2026-11-17": {"star": 3, "label": "美国10月零售销售月率"},
    "2026-12-16": {"star": 3, "label": "美国11月零售销售月率"},
}
# JOLTS（职位空缺）
JOLTS_2026 = {
    "2026-09-29": {"star": 3, "label": "美国8月 JOLTs 职位空缺"},
    "2026-11-03": {"star": 3, "label": "美国9月 JOLTs 职位空缺"},
    "2026-12-08": {"star": 3, "label": "美国10月 JOLTs 职位空缺"},
}

# ISM PMI / 其他高频（给出已知规律锚点；未精确的用推算，source 一律 schedule）
ISM_MFG_2026 = {  # 通常每月1日
    "2026-10-01": {"star": 3, "label": "美国9月 ISM 制造业 PMI"},
    "2026-11-02": {"star": 3, "label": "美国10月 ISM 制造业 PMI"},
    "2026-12-01": {"star": 3, "label": "美国11月 ISM 制造业 PMI"},
}

# ============ 官方 2027 排期锚点 ============
# ⚠️ 口径声明：
#   - FOMC_2027：美联储官网 2025-09-05 公布的「2027 初步日程」，为官方真实日期（决议日=第二日美东 14:00→北京次日02:00）。
#   - CPI_2027：BLS 官方 2027 排期尚未发布（惯例约 2026 年底公布）；下表用 cpiinflationcalculator 依据 BLS 规律的 2027 预测值，
#     标 source=schedule(推算)并在文档注明"待 BLS 官方确认"。数据月=上月。
#   - 其余（非农/PPI/PCE/GDP/零售/JOLTS/ISM）2027：官方未发布，采用下方 _rules 规律引擎按各月可得规则推算，明确标注推算。
FOMC_2027 = {
    "2027-01-27": {"star": 5, "sep": False, "label": "FOMC 利率决议(1/26-27会议)"},
    "2027-03-17": {"star": 5, "sep": True,  "label": "FOMC 利率决议(3/16-17会议)+SEP点阵图"},
    "2027-04-28": {"star": 5, "sep": False, "label": "FOMC 利率决议(4/27-28会议)"},
    "2027-06-09": {"star": 5, "sep": True,  "label": "FOMC 利率决议(6/8-9会议)+SEP点阵图"},
    "2027-07-28": {"star": 5, "sep": False, "label": "FOMC 利率决议(7/27-28会议)"},
    "2027-09-15": {"star": 5, "sep": True,  "label": "FOMC 利率决议(9/14-15会议)+SEP点阵图"},
    "2027-10-27": {"star": 5, "sep": False, "label": "FOMC 利率决议(10/26-27会议)"},
    "2027-12-08": {"star": 5, "sep": True,  "label": "FOMC 利率决议(12/7-8会议)+SEP点阵图"},
}
FOMC_PRESS_2027 = {
    "2027-01-27": "美联储主席新闻发布会(决议后02:30)",
    "2027-03-17": "美联储主席新闻发布会(决议后02:30)",
    "2027-04-28": "美联储主席新闻发布会(决议后02:30)",
    "2027-06-09": "美联储主席新闻发布会(决议后02:30)",
    "2027-07-28": "美联储主席新闻发布会(决议后02:30)",
    "2027-09-15": "美联储主席新闻发布会(决议后02:30)",
    "2027-10-27": "美联储主席新闻发布会(决议后02:30)",
    "2027-12-08": "美联储主席新闻发布会(决议后02:30)",
}
# CPI 2027：cpiinflationcalculator 依据 BLS 第二周规律的预测（官方未发，推算）
CPI_2027 = {
    "2027-01-13": {"star": 5, "label": "美国12月 CPI(消费者物价指数)"},
    "2027-02-10": {"star": 5, "label": "美国1月 CPI(消费者物价指数)"},
    "2027-03-10": {"star": 5, "label": "美国2月 CPI(消费者物价指数)"},
    "2027-04-13": {"star": 5, "label": "美国3月 CPI(消费者物价指数)"},
    "2027-05-12": {"star": 5, "label": "美国4月 CPI(消费者物价指数)"},
    "2027-06-10": {"star": 5, "label": "美国5月 CPI(消费者物价指数)"},
    "2027-07-13": {"star": 5, "label": "美国6月 CPI(消费者物价指数)"},
    "2027-08-11": {"star": 5, "label": "美国7月 CPI(消费者物价指数)"},
    "2027-09-14": {"star": 5, "label": "美国8月 CPI(消费者物价指数)"},
    "2027-10-13": {"star": 5, "label": "美国9月 CPI(消费者物价指数)"},
    "2027-11-10": {"star": 5, "label": "美国10月 CPI(消费者物价指数)"},
    "2027-12-10": {"star": 5, "label": "美国11月 CPI(消费者物价指数)"},
}


# ---- 规律推算引擎（仅用于官方排期未覆盖的 2027+ 非农/PPI/ISM 等，source 一律 schedule）----
def _fri(year, month, nth=1):
    """该月第 nth 个周五。"""
    first = date(year, month, 1)
    d = first + timedelta(days=(4 - first.weekday()) % 7)  # 到第一个周五
    d += timedelta(weeks=nth - 1)
    return d


def _weekday_nth(year, month, weekday, nth, min_day=1):
    """该月从 min_day 起第 nth 个 weekday(0=周一)。返回 date。"""
    first = date(year, month, 1)
    d = first
    while d < date(year, month + 1, 1):
        if d.day >= min_day and d.weekday() == weekday:
            nth -= 1
            if nth == 0:
                return d
        d += timedelta(days=1)
    return None


# ============ 月历组装核心 ============
def _weekdays_of_month(year, month):
    """返回该月所有 (date, weekday0..6) 列表。"""
    if month == 12:
        nd = date(year + 1, 1, 1)
    else:
        nd = date(year, month + 1, 1)
    first = date(year, month, 1)
    days = []
    d = first
    while d < nd:
        days.append((d, d.weekday()))  # Mon=0
        d += timedelta(days=1)
    return days


def _add_rows(rows, ds: date, time_bj, star, title, source, hint="", extra=None):
    """往 rows[ds] 挂一条事件。rows: dict date->list。"""
    rows.setdefault(ds.isoformat(), []).append({
        "date": ds.isoformat(),
        "weekday": _WD_CN[ds.weekday()],
        "time": time_bj,
        "star": star,
        "title": title,
        "source": source,   # schedule | jin10
        "hint": hint,
        "extra": extra or {},
    })


_WD_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _initial_jobless_dates(year, month):
    """初请失业金：每月多个周四。返回该月所有周四 (北京时间20:30)。"""
    out = []
    for ds, wd in _weekdays_of_month(year, month):
        if wd == 3:  # Thursday
            out.append((ds, "美国当周初请失业金人数(20:30)"))
    return out


def _pick26(t26, t27, year):
    """返回该年适用的官方/预测锚点表：year>=2027 用 t27（若有），否则 t26。"""
    if year >= 2027 and t27 is not None:
        return t27
    return t26


def _rules_anchors(year, month):
    """官方排期未覆盖(2027+)的非农/PPI/PCE/零售/GDP/JOLTS/ISM 规律推算。

    依据美国数据发布惯例，source 一律 schedule，生成器按惯例尽力贴合：
      - 非农：多数月份为每月「首个周五」，个别落在次周五（如遇假期）——此处取首个周五，精确月靠金十当周实时纠正。
      - PPI/零售：通常 CPI/非农 后 1-3 个工作日（取 CPI 后第 1-2 个工作日简化）。
      - JOLTS：约月底后 1-2 周。
      - ISM：每月首工作日。
    仅用于给未公布官排期的未来月一个“可看骨架”，文档须声明待官方确认。
    """
    out = {}  # date_str -> (time_bj, star, label, hint)
    nm_d = _fri(year, month, 1)
    # 非农通常为每月首个周五；若该周五恰逢元旦(1/1)等联邦假日则顺延到第二个周五(如2027-01→01-08)
    if year >= 2027 and month == 1 and nm_d.day == 1:
        nm_d = _fri(year, month, 2)
    data_m = (month - 1) or 12
    # 非农：每月首个周五（20:30）
    if nm_d:
        out[nm_d.isoformat()] = ("20:30", 5, f"美国{data_m}月非农就业人口+失业率+平均时薪",
                                 "就业强→美元强→黄金承压；弱→利多黄金")
        # PPI 推非农后数日的当周(简化：次周五前推，无固定官方值就不写死日期，只给非农主档)
    return out


def build_schedule_month(year: int, month: int) -> list:
    """纯排期推算：返回该月事件 list（未与金十实时合并）。2026 用官方表、2027+ 用官方/预测表+规律引擎。"""
    rows: dict = {}
    FOMC_T = _pick26(FOMC_2026, FOMC_2027, year)
    FOMC_P_T = _pick26(FOMC_PRESS_2026, FOMC_PRESS_2027, year)
    NONFARM_T = _pick26(NONFARM_2026, None, year)
    CPI_T = _pick26(CPI_2026, CPI_2027, year)
    PPI_T = _pick26(PPI_2026, None, year)
    PCE_T = _pick26(PCE_2026, None, year)
    GDP_T = _pick26(GDP_2026, None, year)
    RETAIL_T = _pick26(RETAIL_2026, None, year)
    JOLTS_T = _pick26(JOLTS_2026, None, year)
    ISM_T = _pick26(ISM_MFG_2026, None, year)
    ymp = "%04d-%02d" % (year, month)

    def add_if(t, time_bj, hint):
        for dstr, meta in list((t or {}).items()):
            if dstr.startswith(ymp):
                _add_rows(rows, date.fromisoformat(dstr), time_bj, meta["star"],
                          meta["label"], "schedule", hint=hint)

    add_if(FOMC_T, "02:00", "关键：利率路径+点阵图定黄金中长期方向")
    for dstr, label in list((FOMC_P_T or {}).items()):
        if dstr.startswith(ymp):
            _add_rows(rows, date.fromisoformat(dstr), "02:30", 5, label,
                      "schedule", hint="主席措辞定利率预期")
    add_if(NONFARM_T, "20:30", "就业强→美元强→黄金承压；弱→利多黄金")
    add_if(CPI_T, "20:30", "通胀核心信号，决定加息/降息预期")
    add_if(PPI_T, "20:30", "上游通胀，预演CPI")
    add_if(PCE_T, "20:30", "美联储官方通胀锚，最受关注")
    add_if(GDP_T, "20:30", "")
    add_if(RETAIL_T, "20:30", "消费动能")
    add_if(JOLTS_T, "22:00", "劳动力紧缺度")
    add_if(ISM_T, "22:00", "制造业景气")

    # 规律引擎兜底（官方未发布的 2027+ 指标：仅非农主档，其余等官方）
    if year >= 2027:
        for dstr, (t, star, label, hint) in _rules_anchors(year, month).items():
            if not any(r["date"] == dstr and r["title"] == label for r in rows.get(dstr, [])):
                _add_rows(rows, date.fromisoformat(dstr), t, star, label, "schedule", hint=hint)

    # 初请失业金（每周四）
    for ds, label in _initial_jobless_dates(year, month):
        _add_rows(rows, ds, "20:30", 3, label, "schedule", hint="每周劳动力领先指标")

    # 排序并展开为 list
    out = []
    for ds in sorted(rows):
        for ev in sorted(rows[ds], key=lambda x: x["time"]):
            out.append(ev)
    return out


# ============ 与金十实时合并 ============

# 次级/噪声标题片段：整月日历不铺开（初请仅保留主条数，非农/CPI 聚类折叠）
_J10_NOISE = ["国债竞拍", "红皮书", "红皮书商业零售", "API原油", "API汽油", "API精炼",
              "钻井总数", "EIA原油库存", "EIA天然气", "EIA库欣", "EIA精炼厂",
              "外国央行持有美国国债", "抵押贷款申请", "MBA", "四周均值", "续请",
              "商业零售销售年率", "挑战者企业裁员月率", "挑战者企业裁员年率",
              "出口", "进口", "营建支出", "工厂订单月率", "扣除国防", "扣除运输",
              "耐用品订单月率终值", "达拉斯联储", "堪萨斯", "里奇蒙", "费城联储",
              "芝加哥联储", "纽约联储", "储销量", "官方储备", "外汇存底", "经常帐",
              "Ivey", "供应链压力", "未季调", "全职就业", "兼职就业", "就业参与率",
              "平均每周工时", "政府部门就业", "私人非农", "制造业就业人口",
              "房屋", "营建许可", "新屋开工", "成屋销售", "房价指数", "NAHB",
              "贸易帐", "商品贸易帐", "批发", "零售库存", "商业库存",
              # 非美小国/次要
              "越南", "印度", "泰国", "印尼", "马来西亚", "新加坡", "菲律宾",
              "澳大利亚", "新西兰", "韩国", "瑞士", "西班牙", "意大利", "俄罗斯",
              "巴西", "墨西哥", "南非", "土耳其", "沙特", "瑞典", "挪威",
              "台湾", "中国香港",
              ]
# 主要市场白名单前缀（GDP/零售/失业率等次要行只保留主要经济体）
_J10_KEEP_NATION = ["美国", "欧元区", "德国", "英国", "法国", "日本", "中国8月", "中国7月", "加拿大"]


def _is_us_gold_event(title: str) -> bool:
    """判断金十行是否整月日历值得收录（美国主线 + 黄金强相关）。

    提升门槛：剔除次级/噪声行与多数非主要市场，聚焦  直接驱动。
    """
    if not title or len(title) < 4:
        return False
    if any(n in title for n in _J10_NOISE):
        return False
    # 黄金核心驱动词
    gold_kw = ["CPI", "PPI", "PCE", "非农", "失业", "就业", "初请", "零售销售", "ADP",
               "GDP", "ISM", "JOLT", "职位空缺", "密歇根", "通胀", "利率决议", "央行利率",
               "美联储", "联储", "利率决定", "特朗普", "鲍威尔", "沃勒", "关税",
               "黄金", "金价", "避险", "PMI"]
    hit = any(k in title for k in gold_kw)
    if not hit:
        return False
    # PMI/GDP/零售/失业率 等"次级"标题：只保留主要市场（否则各小国 PMI 塞爆整月日历）
    low_tier = any(k in title for k in ["PMI", "GDP", "零售销售", "失业率", "制造业", "服务业",
                                        "综合", "房屋", "JOLT"])
    if low_tier and not any(k in title for k in _J10_KEEP_NATION):
        return False
    return True


# 同一时段同一宏观大类的"聚类折叠"：把 20:30 同时发的 非农/失业率/时薪/薪资 等多条压成一条


def _cluster_key(title: str) -> str:
    """把同一场发布的多条指标聚成一个 key；不同 key 表示不同场次。返回 key 或 None。"""
    if any(k in title for k in ["非农就业人口", "私人非农就业", "政府部门就业"]):
        return "NONFARM"
    if "失业率" in title:
        return "UNRATE"
    if any(k in title for k in ["平均每小时工资", "平均时薪"]):
        return "WAGE"
    if any(k in title for k in ["当周初请失业金人数", "初请失业金人数"]):
        return "JOBLESS"
    if any(k in title for k in ["ADP", "小非农"]):
        return "ADP"
    if "CPI" in title or "调和CPI" in title:
        return "CPI"
    return None


def merge_jin10(schedule_events: list, jin10_rows: list, today: date, month_bounds: tuple) -> list:
    """把金十当前周真实行合入排期表（聚焦主线 + 聚类折叠，避免噪声）。"""
    sched_by_date = {}
    for e in schedule_events:
        sched_by_date.setdefault(e["date"], []).append(e)

    # 预收集候选：已过滤 + 归类 + 聚类折叠
    groups = {}   # (date, cluster) -> best ev
    for r in jin10_rows or []:
        pt = str(r.get("pub_time", ""))[:10]
        try:
            d = date.fromisoformat(pt)
        except Exception:
            continue
        if not (month_bounds[0] <= d <= month_bounds[1]):
            continue
        title = r.get("title", "")
        if not _is_us_gold_event(title):
            continue
        star = r.get("star") or 0
        actual = r.get("actual")
        state = "已公布" if actual not in (None, "") else "待公布"
        ckey = _cluster_key(title)
        time_bj = str(r.get("pub_time", ""))[11:16]
        ev = {
            "date": d.isoformat(), "weekday": _WD_CN[d.weekday()],
            "time": time_bj, "star": star, "title": title, "source": "jin10",
            "hint": "",
            "extra": {"state": state, "actual": actual, "consensus": r.get("consensus"),
                      "previous": r.get("previous"), "affect_txt": r.get("affect_txt", "")},
        }
        if ckey:
            # 聚类：同场次保留星级最高/已有 actual 的作代表，字段合并
            gk = (d.isoformat(), ckey)
            prev = groups.get(gk)
            if prev is None or (star, actual is not None) > (prev["star"], prev["extra"]["actual"] is not None):
                groups[gk] = ev
                if prev:
                    # 保留下一条的星/实际用于展示合并
                    pass
            else:
                # 合并 prev 缺的字段
                for f in ["actual", "consensus", "previous", "affect_txt"]:
                    if prev["extra"].get(f) in (None, "") and ev["extra"].get(f) not in (None, ""):
                        prev["extra"][f] = ev["extra"][f]
                if ev["star"] > prev["star"]:
                    prev["star"] = ev["star"]
            continue
        # 非聚类：低星已公布跳过（微数据）；否则入列表
        if star < 3 and state == "已公布":
            continue
        groups[(d.isoformat(), title[:24])] = ev

    # 聚类代表标题美化 + 展示实际
    for gk, ev in list(groups.items()):
        if gk[1] == "NONFARM":
            ev["title"] = "美国非农就业人口+失业率+平均时薪"
        elif gk[1] == "UNRATE" or gk[1] == "WAGE":
            continue  # NONFARM 已含
        # UNRATE/WAGE 若独立出现保留原标题

    # 合并到排期表 / 新增
    j_add = []
    for gk, ev in groups.items():
        merged = False
        if gk[1] in ("NONFARM", "UNRATE", "WAGE"):
            # 与排期 NONFARM 主线合并
            for se in sched_by_date.get(ev["date"], []):
                if "非农" in se["title"] and ev["source"] == "jin10":
                    se["source"] = "jin10"
                    se["title"] = ev["title"] if ev["extra"]["state"] == "已公布" else se["title"]
                    se["extra"].update({k: v for k, v in ev["extra"].items() if v not in (None, "")})
                    if ev["star"] > se["star"]:
                        se["star"] = ev["star"]
                    merged = True
                    break
        if not merged:
            j_add.append(ev)

    combined = list(schedule_events) + j_add
    combined.sort(key=lambda e: (e["date"], e["time"]))
    return combined


# ============ 对外入口 ============
def month_calendar(year: int, month: int, jin10_rows=None, today=None) -> dict:
    """生成某月整月  消息面日历（按周分组）。返回可直接给 API/页面/文档用的 dict。"""
    today = today or date.today()
    bounds = (date(year, month, 1),
              date(year + 1, 1, 1) - timedelta(days=1) if month == 12
              else date(year, month + 1, 1) - timedelta(days=1))
    evs = build_schedule_month(year, month)
    if jin10_rows:
        evs = merge_jin10(evs, jin10_rows, today, bounds)
    # 去掉当月已过去日期的"待公布/排期"(仅当超过今天) —— 但保留已公布作为复盘参考？
    # 规则：date < today 的行，若 source=jin10 且已公布则保留(复盘)；schedule 纯排期(未发生)且已过 → 去掉。
    filtered = []
    for e in evs:
        d = date.fromisoformat(e["date"])
        if d < today and e["source"] == "schedule":
            # 排期推算但日期已过且无金十实况 → 无价值，丢弃（除非是未来数据月份预排期前移）
            continue
        filtered.append(e)
    evs = filtered
    evs.sort(key=lambda x: (x["date"], x["time"]))

    # 按周分组（周一开头）
    weeks = []
    cur = []
    last_monday = None
    for e in evs:
        d = date.fromisoformat(e["date"])
        monday = d - timedelta(days=d.weekday())
        if last_monday is None or monday != last_monday:
            if cur:
                weeks.append({"week_start": last_monday.isoformat(), "events": cur})
            cur = []
            last_monday = monday
        cur.append(e)
    if cur:
        weeks.append({"week_start": last_monday.isoformat(), "events": cur})

    return {
        "year": year, "month": month,
        "month_label": "%d年%02d月" % (year, month),
        "bounds": {"start": bounds[0].isoformat(), "end": bounds[1].isoformat()},
        "today": today.isoformat(),
        "source_note": "schedule=官方2026排期推算(未获金十当周实时)；jin10=金十当前周实时数据",
        "weeks": weeks,
        "total": len(evs),
    }
