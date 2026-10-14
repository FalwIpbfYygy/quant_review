# -*- coding: utf-8 -*-
"""
消息面聚合模块（新增，不改动 jin10.py / month_cal.py 既有逻辑）

职责：把 /mindmap 行情对话 与 /xau 每日报告 需要的「金十消息面」聚合成一段
可直接注入 LLM prompt 的文本。四大数据源各自独立 try/except，任一源挂了只丢
对应段，主流程（技术面 + 规则 / 宏观）照常出方案——绝不因为消息面失败而整段崩。

数据源（均已在 jin10.py / month_cal.py 实现，本模块只做聚合与渲染）：
  1. jin10.snapshot_quotes()      —— 6 品种现货实时行情（金十现货 ，仅作美元强弱参考）
  2. jin10.snapshot_calendar()    —— 本周财经日历真实行（含 affect_txt 利多利空判向、实况/前值/预期）
  3. month_cal.month_calendar()   —— 整月  消息面日历（schedule 排期 + 金十当周实时合并）
  4. jin10.snapshot_gold_news()   —— 黄金强相关实时消息流（按 ★/利多利空已过滤）

铁律（注入提示词时一并写进 SYSTEM，防 AI 乱编/混算）：
  - 价格口径隔离：金十现货  与 Binance 永续  有基差；消息面价格只用于判断
    美元强弱 / 风险偏好，所有交易点位一律取自 Binance 事实，严禁混算。
  - 时效：每条消息面带北京时间戳；已公布按「已公布」、未公布按「待公布」，不得颠倒。
  - 缺失就明说「消息面不可用」，禁止编造事件或数值。
"""

# 直跑兜底：作为脚本直接运行时，把项目根目录加入 sys.path
if __package__ in (None, ""):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time
import datetime
from datetime import date, timedelta, datetime as _dt

from data import jin10
from core import month_cal

# ── 聚合参数（标准档） ──
NEWS_LOOKBACK_H = 24          # 实时消息流截取窗口（小时）
WINDOW_DAYS = 3               # 未来数据窗口天数
MIN_STAR = 3                  # 数据窗口 / 高影响日历的最低星级
TOP_NEWS = 30                 # 实时消息流最多条数

# 实时行情只取这几个（其余与黄金联动弱，省 token）
QUOTE_CODES = ["", "XAGUSD", "USOIL", "UKOIL", "EURUSD", "USDJPY"]


def compute_news_facts(force: bool = False) -> dict:
    """聚合金十消息面。任一源失败不影响其余。返回结构化 dict（含 text 渲染段）。"""
    t0 = time.time()
    out = {
        "ok": False,
        "err": None,
        "quotes": None,
        "data_window": [],
        "high_impact_week": [],
        "news_top": [],
        "text": "",
        "latency_ms": 0,
    }
    errs = []

    # 1) 实时行情（现货，仅作美元强弱 / 风险偏好参考）
    try:
        q = jin10.snapshot_quotes(QUOTE_CODES)
        if q:
            out["quotes"] = q
    except Exception as e:
        errs.append("quotes:%s" % e)

    # 2) 本周财经日历（真实行，★>=MIN_STAR）
    try:
        cal = jin10.snapshot_calendar()
        rows = cal.get("data") or []
        hi = []
        for r in rows:
            if (r.get("star") or 0) >= MIN_STAR:
                hi.append({
                    "pub_time": r.get("pub_time", ""),
                    "title": r.get("title", ""),
                    "star": r.get("star") or 0,
                    "affect_txt": r.get("affect_txt", "") or "",
                    "actual": r.get("actual"),
                    "consensus": r.get("consensus"),
                    "previous": r.get("previous"),
                })
        out["high_impact_week"] = hi
    except Exception as e:
        errs.append("calendar:%s" % e)

    # 3) 未来 WINDOW_DAYS 天数据窗口（month_cal：schedule 排期 + 金十当周实时合并）
    try:
        today = date.today()
        cal_rows = (jin10.snapshot_calendar().get("data") or [])
        mc = month_cal.month_calendar(today.year, today.month,
                                      jin10_rows=cal_rows, today=today)
        win = []
        for wk in mc.get("weeks", []):
            for e in wk.get("events", []):
                try:
                    d = date.fromisoformat(e["date"])
                except Exception:
                    continue
                dd = (d - today).days
                if 0 <= dd <= WINDOW_DAYS and (e.get("star") or 0) >= MIN_STAR:
                    win.append(e)
        out["data_window"] = win
    except Exception as e:
        errs.append("month_cal:%s" % e)

    # 4) 实时消息流（近 NEWS_LOOKBACK_H 小时，黄金强相关 top TOP_NEWS）
    try:
        gn = jin10.snapshot_gold_news(force=force)
        events = gn.get("events") or []
        now = _dt.now()
        recent = [e for e in events
                  if e.get("ts") and (now - e["ts"]).total_seconds() <= NEWS_LOOKBACK_H * 3600]
        recent.sort(key=lambda e: e["ts"], reverse=True)
        out["news_top"] = recent[:TOP_NEWS]
    except Exception as e:
        errs.append("gold_news:%s" % e)

    out["ok"] = any([out["quotes"], out["high_impact_week"],
                     out["data_window"], out["news_top"]])
    out["err"] = "; ".join(errs) if errs else None
    out["text"] = format_news_facts(out)
    out["latency_ms"] = int((time.time() - t0) * 1000)
    return out


def format_news_facts(f: dict) -> str:
    """把聚合结果渲染成可注入 LLM 的紧凑文本段。"""
    L = []

    q = f.get("quotes") or {}
    if q:
        L.append("【实时行情（金十现货，仅作美元强弱 / 风险偏好参考，点位不用于交易）】")
        for code, qq in q.items():
            if not isinstance(qq, dict):
                continue
            name = qq.get("name") or code
            close = qq.get("close")
            if close is None:
                continue
            s = "  %s(%s)：%s" % (name, code, close)
            chg = qq.get("chg_pct")
            if chg is None:
                chg = qq.get("chg")
            if chg is not None:
                try:
                    s += "  涨跌 %s%%" % round(float(chg), 2)
                except Exception:
                    pass
            L.append(s)

    dw = f.get("data_window") or []
    if dw:
        L.append("【未来 %d 天数据窗口（★≥%d，北京时间）】" % (WINDOW_DAYS, MIN_STAR))
        for e in dw:
            ex = e.get("extra") or {}
            extra = ""
            if ex.get("state"):
                extra += " [%s]" % ex["state"]
            if ex.get("actual") not in (None, ""):
                extra += " 实况 %s" % ex["actual"]
            if ex.get("consensus") not in (None, ""):
                extra += " 预期 %s" % ex["consensus"]
            if ex.get("previous") not in (None, ""):
                extra += " 前值 %s" % ex["previous"]
            if e.get("affect_txt"):
                extra += " 影响:%s" % e["affect_txt"]
            L.append("  %s %s ★%s %s%s" % (
                e.get("date", ""), e.get("time", ""), e.get("star", ""),
                e.get("title", ""), extra))

    hi = f.get("high_impact_week") or []
    if hi:
        L.append("【本周高影响数据事件表（金十实时，★≥%d）】" % MIN_STAR)
        for r in hi:
            ex = []
            if r.get("actual"):
                ex.append("实况%s" % r["actual"])
            if r.get("consensus"):
                ex.append("预期%s" % r["consensus"])
            if r.get("previous"):
                ex.append("前值%s" % r["previous"])
            if r.get("affect_txt"):
                ex.append("影响%s" % r["affect_txt"])
            L.append("  %s ★%s %s%s" % (
                r.get("pub_time", ""), r.get("star", ""),
                r.get("title", ""), (" (" + ", ".join(ex) + ")") if ex else ""))

    nt = f.get("news_top") or []
    if nt:
        L.append("【实时消息流（近 %d 小时，黄金强相关 top%d，金十）】" % (NEWS_LOOKBACK_H, len(nt)))
        for e in nt:
            aff = e.get("affect") or ""
            tag = " [%s]" % aff if aff else ""
            L.append("  %s%s %s" % (e.get("time", ""), tag, e.get("content", "")))

    return "\n".join(L)


if __name__ == "__main__":
    f = compute_news_facts(force=True)
    print("[自检] ok=%s err=%s 耗时 %dms" % (f["ok"], f["err"], f["latency_ms"]))
    print("  quotes=%d data_window=%d high_impact_week=%d news_top=%d" % (
        len(f["quotes"] or {}), len(f["data_window"]),
        len(f["high_impact_week"]), len(f["news_top"])))
    print("─" * 60)
    print(f["text"][:1600])
