# -*- coding: utf-8 -*-
"""狩猎区 1m what-if 保本回测引擎（M1）。

纯计算内核 `simulate_zone` / `_run` / `simulate_day` / `simulate_triggers` **零 IO、可单测**；
`compute_day_levels` / `fetch_day_1m` 为取数薄封装（本地 `kline_1m` 优先 + fapi 兜底）。

严格因果、零未来函数（见 SPEC §7）：档位只用 ≤D-open 已收盘数据；模拟按 1m bar 升序前向扫描，
任何事件判定只用当前/已逝 bar，绝不引用未来 bar。

决策基线（已锁）：§11-1 强平 22:30 北京时(=UTC 14:30)、§11-2 K=1、§11-4 按报告规则重写、
§11-5 force_sl2=(b)、§11-6 ADR-4 关 `ma3`/`vol`、日边界 = UTC 自然日。
"""
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

from huntzone.hz_engine import (build, Config, norm_dir, trend_series, trend_direction,
                       trend_confirm, vol_spike_filter)
from huntzone.hz_signal import predict_S, S_MODEL_FROZEN


# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
K_USD = 1.0                     # §11-2：1 价格点 = $1·1oz；M1 反推校验后修正
TRIGGER_MIN, TRIGGER_MAX = 8, 26
DEFAULT_TRIGGER = 20
BJ = timezone(timedelta(hours=8))
UTC = timezone.utc
# 北京 22:30 = UTC 14:30，距 UTC 00:00（日开盘）14.5h
_FORCE_CLOSE_OFFSET_MS = 14 * 3600 * 1000 + 30 * 60 * 1000

ZONE_TAGS = ("zone_a", "zone_mid", "zone_b")


# ----------------------------------------------------------------------------
# 时间工具
# ----------------------------------------------------------------------------
def _bj_time(ots_ms: int) -> str:
    return datetime.fromtimestamp(ots_ms / 1000, tz=BJ).strftime("%H:%M")


def _utc_date(ots_ms: int) -> str:
    return datetime.fromtimestamp(ots_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _date_to_open_ms(date: str) -> int:
    y, m, d = map(int, date.split("-"))
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


# ----------------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------------
@dataclass
class Event:
    tag: str
    type: str
    time: str          # "HH:MM" 北京时
    ts_ms: int         # UTC 毫秒（图表 x 轴）
    price: float
    note: str


@dataclass
class ZoneResult:
    tag: str
    filled: bool
    entry: float
    events: List[Event] = field(default_factory=list)
    realized_points: float = 0.0
    exit_type: str = "none"


Bar = Tuple[int, float, float, float, float]   # (open_time_ms, o, h, l, c)


# ----------------------------------------------------------------------------
# 单区有限状态机
# ----------------------------------------------------------------------------
class _ZoneState:
    """单区生命周期：IDLE → FILLED → {TP1_DONE → BE_ARMED} → EXIT_*。

    trigger=None 表示 origin（不启用保本，无 be_arm/be_out）。
    每根 bar 判定顺序（同根冲突 SL 优先）：STOP > TP1 > TP2 > BE_ARM > BE_OUT。
    """

    def __init__(self, tag: str, entry: float, direction: str,
                 lad: dict, trigger: Optional[int]):
        self.tag = tag
        self.entry = entry
        self.short = (norm_dir(direction) == "short")
        self.lad = lad
        self.trigger = trigger                       # None => 无保本（origin）
        self.t1 = lad.get("t1")                       # 目标①=昨收；special_gap 时 None
        self.stop_price = lad["stop"]
        self.exh1 = lad["exh1"]
        self.filled = False
        self.state = "IDLE"
        self.stop_level = self.stop_price             # be_arm 前=原始 stop；be_arm 后=entry
        self.remaining = 1.0                          # tp1 后剩 0.5
        self.realized = 0.0
        self.exit_type = "none"
        self.done = False
        self.events: List[Event] = []

    def _signed(self, p: float) -> float:
        """按方向符号化的点位盈亏（short: entry−p；long: p−entry）。"""
        return (self.entry - p) if self.short else (p - self.entry)

    def step(self, bar: Bar) -> None:
        ots, o, h, l, c = bar
        # ---- 未成交：limit 挂单 ----
        if not self.filled:
            if self.short:
                if h >= self.entry:
                    self.filled = True
                    self.state = "FILLED"
                    self.events.append(Event(self.tag, "fill", _bj_time(ots), ots, self.entry,
                                             "limit 成交（bar H=%.2f≥挂单 %.2f）" % (h, self.entry)))
                else:
                    return
            else:
                if l <= self.entry:
                    self.filled = True
                    self.state = "FILLED"
                    self.events.append(Event(self.tag, "fill", _bj_time(ots), ots, self.entry,
                                             "limit 成交（bar L=%.2f≤挂单 %.2f）" % (l, self.entry)))
                else:
                    return
        # ---- 已成交：按优先级检查退出（SL 优先） ----
        # 1) STOP（BE_ARMED 之前用原始 stop；之后 stop_level=entry，等同 be_out）
        if self.state in ("FILLED", "TP1_DONE"):
            stop_hit = (h >= self.stop_level) if self.short else (l <= self.stop_level)
            if stop_hit:
                self.realized += self.remaining * self._signed(self.stop_level)
                self.events.append(Event(self.tag, "stop", _bj_time(ots), ots, self.stop_level, "触及止损"))
                self.exit_type = "stop"
                self.done = True
                return
        # 2) TP1（目标①=昨收，平 50%）；剩余仓 stop 维持原始直到 be_arm
        if self.state == "FILLED" and self.t1 is not None:
            tp1_hit = (l <= self.t1) if self.short else (h >= self.t1)
            if tp1_hit:
                self.realized += 0.5 * self._signed(self.t1)
                self.remaining = 0.5
                self.state = "TP1_DONE"
                self.events.append(Event(self.tag, "tp1", _bj_time(ots), ots, self.t1, "目标①平50%"))
        # 3) TP2（衰竭① exh1，平剩余）
        if self.state in ("FILLED", "TP1_DONE") and self.remaining > 0:
            tp2_hit = (l <= self.exh1) if self.short else (h >= self.exh1)
            if tp2_hit:
                self.realized += self.remaining * self._signed(self.exh1)
                self.events.append(Event(self.tag, "tp2", _bj_time(ots), ots, self.exh1, "衰竭①平余"))
                self.exit_type = "tp2"
                self.done = True
                return
        # 4) BE_ARM（仅 TP1_DONE 后，浮动盈利≥trigger；trigger=None 即 origin 不触发）
        if self.state == "TP1_DONE" and self.trigger is not None:
            be_arm_hit = (l <= self.entry - self.trigger) if self.short else (h >= self.entry + self.trigger)
            if be_arm_hit:
                self.stop_level = self.entry           # 止损移至入场（保本）
                self.state = "BE_ARMED"
                self.events.append(Event(self.tag, "be_arm", _bj_time(ots), ots, self.entry,
                                         "盈利达%d点→保本激活(止损移至入场)" % self.trigger))
        # 5) BE_OUT（仅 BE_ARMED 后，回撤至 entry）
        if self.state == "BE_ARMED":
            be_out_hit = (h >= self.entry) if self.short else (l <= self.entry)
            if be_out_hit:
                self.realized += self.remaining * self._signed(self.entry)   # = 0
                self.events.append(Event(self.tag, "be_out", _bj_time(ots), ots, self.entry,
                                         "回撤至入场→保本出场(0盈亏)"))
                self.exit_type = "be_out"
                self.done = True
                return

    def force_close(self, bar: Bar, etype: str, force_close_ms: int) -> None:
        """收盘强平（force22）或 2 次止损幸存腿强平（force_sl2）。"""
        ots, o, h, l, c = bar
        self.realized += self.remaining * self._signed(c)
        if etype == "force22":
            tstr, tms = "22:30", force_close_ms
        else:
            tstr, tms = _bj_time(ots), ots
        self.events.append(Event(self.tag, etype, tstr, tms, c,
                                 "22:30 强平" if etype == "force22" else "2次硬止损→幸存腿强平"))
        self.exit_type = etype
        self.done = True


# ----------------------------------------------------------------------------
# 核心：单 trigger 模拟（trigger=None = origin 无保本）
# ----------------------------------------------------------------------------
def _run(lad: dict, bars: List[Bar], trigger: Optional[int],
         symbol: str = "") -> dict:
    if not bars:
        return {"realized_usd": 0.0,
                "zones": {"zone_a": 0.0, "zone_mid": 0.0, "zone_b": 0.0},
                "events": [], "outcome": "持平（缺数据）", "missing": True,
                "direction": lad.get("direction") if lad else ""}
    day_open_ms = bars[0][0]
    force_close_ms = day_open_ms + _FORCE_CLOSE_OFFSET_MS
    direction = lad["direction"]
    short = (norm_dir(direction) == "short")
    # 档位→挂单价映射（已对参考报告 200 日逐日核对，非对称）：
    #   做空：zone_a=zone_hi(最高挂单，价格上行首触) / zone_mid / zone_b=zone_lo(最低)；
    #   做多：反向 zone_a=zone_lo / zone_mid / zone_b=zone_hi。zone_mid 居中不变。
    if short:
        entry_map = {"zone_a": lad["zone_hi"], "zone_mid": lad["zone_mid"], "zone_b": lad["zone_lo"]}
    else:
        entry_map = {"zone_a": lad["zone_lo"], "zone_mid": lad["zone_mid"], "zone_b": lad["zone_hi"]}

    states = [_ZoneState(t, entry_map[t], direction, lad, trigger) for t in ZONE_TAGS]

    last_bar = bars[0]
    for bar in bars:
        last_bar = bar
        if bar[0] > force_close_ms:
            break
        for st in states:
            if st.done:
                continue
            st.step(bar)
        # force_sl2=(b)：任 2 区硬止损 → 幸存活仓腿当根强平。
        # 必须在整根 bar 的各区判定【结束后】统计：同根三区共享止损时，
        # 第 3 区也在本根触发 stop，不应被误判为 force_sl2（参考报告 200 日 force_sl2=0）。
        hard_stops = sum(1 for st in states if st.exit_type == "stop")
        if hard_stops >= 2:
            for s2 in states:
                if not s2.done and s2.filled:     # 仅已成交未退出者；未成交腿无仓位不强制
                    s2.force_close(bar, "force_sl2", force_close_ms)

    # 收盘强平（已成交但未 exit 的区）
    for st in states:
        if st.filled and not st.done:
            st.force_close(last_bar, "force22", force_close_ms)

    zones_usd = {t: round(st.realized * K_USD, 4) for t, st in zip(ZONE_TAGS, states)}
    all_events: List[Event] = []
    for st in states:
        all_events.extend(st.events)
    total_points = sum(st.realized for st in states)
    total_usd = round(total_points * K_USD, 4)
    outcome = "盈利" if total_points > 1e-9 else ("亏损" if total_points < -1e-9 else "持平")
    return {"realized_usd": total_usd, "zones": zones_usd, "events": all_events,
            "outcome": outcome, "missing": False, "direction": direction}


# ----------------------------------------------------------------------------
# 公共 API
# ----------------------------------------------------------------------------
def simulate_day(lad: dict, bars: List[Bar], trigger: int = DEFAULT_TRIGGER,
                 symbol: str = "") -> dict:
    """单日三区 what-if 回测（单 trigger）。返回 origin + be[trigger] 聚合 dict。"""
    date = _utc_date(bars[0][0]) if bars else ""
    origin = _run(lad, bars, None, symbol)
    be = _run(lad, bars, trigger, symbol)
    return {
        "date": date,
        "direction": lad.get("direction"),
        "missing": origin.get("missing", False),
        "origin": {"realized_usd": origin["realized_usd"], "zones": origin["zones"]},
        "be": {str(trigger): {"realized_usd": be["realized_usd"], "zones": be["zones"]}},
        "outcome": origin["outcome"],
        "events_all": be["events"],
        "origin_events": origin["events"],
    }


def simulate_triggers(lad: dict, bars: List[Bar], triggers: Optional[List[int]] = None,
                      symbol: str = "") -> dict:
    """循环 trigger∈[8..26]，返回 {trigger: simulate_day 等价聚合}（供 range 聚合）。"""
    if triggers is None:
        triggers = list(range(TRIGGER_MIN, TRIGGER_MAX + 1))
    date = _utc_date(bars[0][0]) if bars else ""
    origin = _run(lad, bars, None, symbol)
    be = {t: _run(lad, bars, t, symbol) for t in triggers}
    return {
        "date": date,
        "direction": lad.get("direction"),
        "missing": origin.get("missing", False),
        "origin": {"realized_usd": origin["realized_usd"], "zones": origin["zones"]},
        "be": {str(t): {"realized_usd": be[t]["realized_usd"], "zones": be[t]["zones"]}
               for t in triggers},
        "outcome": origin["outcome"],
        "events_all": be[DEFAULT_TRIGGER]["events"],
        "origin_events": origin["events"],
    }


# ----------------------------------------------------------------------------
# 取数薄封装（唯一触网/触 DB 处；单测不覆盖，由用户在服务器执行）
# ----------------------------------------------------------------------------
def compute_day_levels(date: str, symbol: str = "") -> Optional[dict]:
    """给定 UTC 自然日，返回档位 dict(lad) 或 None（d==0 无信号）。ADR-4：关 ma3/vol。"""
    from huntzone.huntv2_core import fetch_daily_1d
    rows, err, source = fetch_daily_1d(symbol, limit=90)
    if err or not rows:
        return None
    d_open_ms = _date_to_open_ms(date)
    day_bars = []
    for r in rows:
        ts = int(r[0])
        if ts <= d_open_ms:                       # 含 D 当日（已收盘）
            day_bars.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    day_bars = sorted(day_bars, key=lambda b: b[0])
    if len(day_bars) < 7:
        return None
    today = day_bars[-1]
    prev_bar = day_bars[-2]
    prev_history = day_bars[:-1]
    # ADR-4：关闭 ma3 趋势确认与 vol 波动过滤，仅 SMA10 顺势符号 + 冻结 S
    cfg = Config(trend_period=10, trend_mode="sma", trend_filter="", vol_filter=0.0)
    ma = trend_series(prev_history, cfg.trend_period, cfg.trend_mode)
    prev_close = prev_bar[4]
    d = trend_direction(prev_close, ma[-1])
    if d == 0:
        return None
    if cfg.trend_filter == "ma3" and not trend_confirm(prev_history, d):
        return None
    if cfg.vol_filter and vol_spike_filter(prev_history, cfg.vol_filter, cfg.vol_look):
        return None
    direction = "short" if d == -1 else "long"
    S, _b1, _p1 = predict_S(S_MODEL_FROZEN, prev_bar)
    lad = build(today[1], S, direction, prev_close=prev_close)
    lad["mae"] = S_MODEL_FROZEN["loo_mae"]
    lad["daily_source"] = source
    return lad


def fetch_day_1m(date: str, symbol: str = ""):
    """取该日 1m 柱。返回 (bars, source, missing)。窗口 [UTC D 00:00, D+1 00:00)。

    本地 kline_1m 优先（sre 实测为 PAXGUSDT+12、已 XAU 量纲，直接当  用）；
    本地空/异常 → 回退 fapi；皆空 → missing=True。
    """
    from data.db import query_kline
    from config import TABLE_MAP
    d_open_ms = _date_to_open_ms(date)
    end_ms = d_open_ms + 86400000               # 次日 00:00
    try:
        rows, _ = query_kline(TABLE_MAP["1m"], d_open_ms, end_ms - 1)
        if rows:
            bars = [(int(r["open_time"]), float(r["open_price"]), float(r["high_price"]),
                     float(r["low_price"]), float(r["close_price"])) for r in rows]
            bars = sorted(bars, key=lambda b: b[0])
            if bars:
                return bars, "local", False
    except Exception:
        pass
    try:
        from data.binance_src import fetch_klines_binance
        rows = fetch_klines_binance(symbol, "1m", d_open_ms, end_ms)
        if rows:
            bars = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]
            bars = sorted(bars, key=lambda b: b[0])
            if bars:
                return bars, "fapi", False
    except Exception:
        pass
    return [], "missing", True


__all__ = ["K_USD", "TRIGGER_MIN", "TRIGGER_MAX", "DEFAULT_TRIGGER",
           "Event", "ZoneResult", "compute_day_levels", "fetch_day_1m",
           "simulate_day", "simulate_triggers", "_run"]
