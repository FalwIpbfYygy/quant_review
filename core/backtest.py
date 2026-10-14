"""
信号复盘回测引擎（新增模块，不改动原有代码）

口径（来自 PRD，已与用户确认）：
- 行情：复用 db.query_kline('1m', ...) 的 1 分钟 K 线，字段 open_time/open_price/high_price/low_price/close_price/close_time（毫秒）。
- 时区假设：db 的时间戳与用户信号时间同处「本地时区（北京时间）」，全程用系统本地时区解释，保证对齐。
- 手数：固定 lot（默认 0.01 手）。：1 美金波动 = lot*100 u；点差 30 pips = 0.30 美金/手 → 单笔成本 = spread_pips * lot u（单边开仓，平仓不重复扣）。
- 分仓（模式 B）：TP1 平 50% 并移保本，剩余 50% 看 TP2；SL 先于 TP1 则全亏；TP1 后回撤到 entry 保本离场；无 TP2 则 TP1 平半后剩余移保本。
- 同根冲突：SL 与 TP 同根穿越默认 SL 优先（保守）。
- 未平仓跨日：每日 23:00 快照按当日收盘价算浮动盈亏计入资金曲线，标记【未平仓】，不计入胜率/盈亏比/R 统计；次日继续，下个 23:00 重算。
"""
from datetime import datetime, timedelta
from bisect import bisect_right
from data.db import query_kline
from config import TABLE_MAP

LOT_OZ = 100  # 1 标准手 = 100 oz
ALIGN_TOL = 3.0  # 价格对齐容差（点）：|数据库现价 - 表格入场| 超过此值才整体平移对齐


# ---------------- 交易时段（亚/欧/美盘，北京时间，区分夏令时/冬令时） ----------------
def _is_dst(month):
    """夏令时判定（量化系统锚定口径）：3–11 月为夏令时（欧美盘开盘提前 1 小时），
    11 月–次年 3 月为冬令时（延后 1 小时）。"""
    return 3 <= month <= 11


def classify_session(ts_ms):
    """按北京时间将毫秒时间戳归类到交易时段（区分夏令时/冬令时，保证每笔唯一归属，全天无缝覆盖）。

    - 夏令时（3–11 月，欧美盘开盘提前 1 小时）：
        亚盘 08:00–15:00、欧盘 15:00–20:00、美盘 20:00–次日08:00
    - 冬令时（11 月–次年 3 月，延后 1 小时）：
        亚盘 08:00–16:00、欧盘 16:00–21:00、美盘 21:00–次日08:00
    """
    dt = datetime.fromtimestamp(ts_ms / 1000)
    dst = _is_dst(dt.month)
    h = dt.hour
    asia_end = 15 if dst else 16
    euro_start = 15 if dst else 16
    euro_end = 20 if dst else 21
    if 8 <= h < asia_end:
        return '亚盘'
    if euro_start <= h < euro_end:
        return '欧盘'
    return '美盘'


# ---------------- 解析工具 ----------------
def parse_signal_time(s):
    s = (s or '').strip()
    if not s:
        return None
    fmts = ["%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
    for f in fmts:
        try:
            return int(datetime.strptime(s, f).timestamp() * 1000)
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s.replace('/', '-').replace(' ', 'T'))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def parse_num(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '')
    if s in ('', '-', '—', 'nan', 'None'):
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_dir(v):
    s = (v or '').strip().lower()
    if s in ('做多', '多', 'long', 'buy', '多单'):
        return 'long'
    if s in ('做空', '空', 'short', 'sell', '空单'):
        return 'short'
    return None


def _infer_tick(signals_raw):
    """从信号表 entry 的小数位推导价格精度：返回 (tick, max_dec)。
    tick = 10^-max_dec（无小数则 1.0）；max_dec 用于四舍五入位数。"""
    max_dec = 0
    for row in signals_raw:
        v = row.get('entry')
        if v is None:
            continue
        s = str(v).strip()
        if '.' in s:
            dec = len(s.split('.')[1])
            if dec > max_dec:
                max_dec = dec
    tick = 10 ** (-max_dec) if max_dec > 0 else 1.0
    return tick, max_dec


def _bar_at(bars_sorted, open_times, ts):
    """返回包含 ts 的那根 1m K 线（open_time <= ts < open_time+60000）；
    若 ts 落在两根之间，取时间最近的一根；无数据返回 None。"""
    if not bars_sorted:
        return None
    i = bisect_right(open_times, ts)
    if i > 0:
        b = bars_sorted[i - 1]
        if b['open_time'] <= ts < b['open_time'] + 60000:
            return b
        if i < len(bars_sorted):
            nxt = bars_sorted[i]
            return b if (ts - b['open_time']) <= (nxt['open_time'] - ts) else nxt
        return b
    return bars_sorted[0]


# ---------------- 单笔回测 ----------------
def backtest_one(sig, bars, open_times, eod_list):
    """
    对单笔信号做逐根扫描回测。
    返回 dict：结果、触发价/时、净盈亏u、R倍数、未平仓每日快照。
    """
    direction = sig['direction']
    entry = sig['entry']
    sl = sig['sl']
    tp1 = sig['tp1']
    tp2 = sig['tp2']
    lot = sig['lot']
    spread_u = sig['spread_pips'] * lot  # 单边开仓成本 u

    # 起始索引：信号时间后第一根
    start_idx = bisect_right(open_times, sig['ts'])

    risk_u = (abs(entry - sl) * lot * LOT_OZ) if sl is not None else 0.0  # 1R 亏损 u

    state = {'phase': 'open', 'snapshots': []}  # open -> tp1done -> closed
    eod_idx = 0
    prev_close = None
    result = None
    close_price = None
    close_ts = None
    net_pnl = None

    def unrealized(price):
        # 当前未平仓部分的浮动盈亏（不含点差）
        if state['phase'] == 'open':
            if direction == 'long':
                return (price - entry) * lot * LOT_OZ
            else:
                return (entry - price) * lot * LOT_OZ
        elif state['phase'] == 'tp1done':
            # 批1 已实现，批2 移保本（entry）
            b1 = (tp1 - entry) * 0.5 * lot * LOT_OZ if direction == 'long' else (entry - tp1) * 0.5 * lot * LOT_OZ
            if direction == 'long':
                b2 = (price - entry) * 0.5 * lot * LOT_OZ
            else:
                b2 = (entry - price) * 0.5 * lot * LOT_OZ
            return b1 + b2
        return 0.0

    i = start_idx
    n = len(bars)
    while i < n:
        bar = bars[i]
        lo = bar['low_price']
        hi = bar['high_price']
        close = bar['close_price']
        ct = bar['close_time']

        # 每日 23:00 快照（未平仓时）
        while eod_idx < len(eod_list) and ct > eod_list[eod_idx]:
            if state['phase'] != 'closed':
                snap_price = prev_close if prev_close is not None else close
                state['snapshots'].append({
                    'ts': eod_list[eod_idx],
                    'pnl': round(unrealized(snap_price), 2),
                })
            eod_idx += 1

        if state['phase'] == 'closed':
            i += 1
            prev_close = close
            continue

        # 初始阶段命中判定必须区分方向：
        # 做多 SL 在入场下方(lo<=sl)、TP 在上方(hi>=tp)；
        # 做空 SL 在入场上方(hi>=sl)、TP 在下方(lo<=tp)。
        if direction == 'long':
            hit_sl = (lo <= sl) if sl is not None else False
            hit_tp1 = (hi >= tp1) if tp1 is not None else False
            hit_tp2 = (hi >= tp2) if tp2 is not None else False
        else:  # short
            hit_sl = (hi >= sl) if sl is not None else False
            hit_tp1 = (lo <= tp1) if tp1 is not None else False
            hit_tp2 = (lo <= tp2) if tp2 is not None else False

        if state['phase'] == 'open':
            if hit_sl and (hit_tp1 or hit_tp2):
                # 同根冲突，SL 优先（保守）
                result = 'SL'
                close_price, close_ts = sl, ct
                net_pnl = -(abs(entry - sl) * lot * LOT_OZ) - spread_u
                state['phase'] = 'closed'
                break
            if hit_sl:
                result = 'SL'
                close_price, close_ts = sl, ct
                net_pnl = -(abs(entry - sl) * lot * LOT_OZ) - spread_u
                state['phase'] = 'closed'
                break
            if hit_tp1:
                # 平批1，移保本
                b1 = (tp1 - entry) * 0.5 * lot * LOT_OZ if direction == 'long' else (entry - tp1) * 0.5 * lot * LOT_OZ
                state['phase'] = 'tp1done'
                state['batch1_pnl'] = b1
                if tp2 is None:
                    # 无 TP2：批2 移保本，继续扫直到回撤保本或结束
                    pass
                # 继续扫描批2
                i += 1
                prev_close = close
                continue
            # 未触发，继续
            i += 1
            prev_close = close
            continue

        elif state['phase'] == 'tp1done':
            # 批2 止损已移到 entry（保本）
            if direction == 'long':
                hit_be = lo <= entry       # 回撤到保本
                hit_tp2b = hi >= tp2 if tp2 is not None else False
            else:
                hit_be = hi >= entry
                hit_tp2b = lo <= tp2 if tp2 is not None else False

            if tp2 is not None and hit_tp2b and not hit_be:
                b2 = (tp2 - entry) * 0.5 * lot * LOT_OZ if direction == 'long' else (entry - tp2) * 0.5 * lot * LOT_OZ
                result = 'TP2'
                close_price, close_ts = tp2, ct
                net_pnl = state['batch1_pnl'] + b2 - spread_u
                state['phase'] = 'closed'
                break
            if hit_be:
                # 保本离场
                result = 'TP1(保本)'
                close_price, close_ts = entry, ct
                net_pnl = state['batch1_pnl'] - spread_u
                state['phase'] = 'closed'
                break
            if tp2 is not None and hit_tp2b and hit_be:
                # 同根冲突：保本优先（保守，不贪）
                result = 'TP1(保本)'
                close_price, close_ts = entry, ct
                net_pnl = state['batch1_pnl'] - spread_u
                state['phase'] = 'closed'
                break
            # 继续
            i += 1
            prev_close = close
            continue

    # 扫描结束仍未平仓
    if state['phase'] != 'closed':
        # 末尾快照 + 按末根收盘价结算（标记未平仓-截止）
        last = bars[-1] if bars else None
        if last is not None:
            # 所有覆盖到的 23:00 日终快照
            while eod_idx < len(eod_list) and last['close_time'] > eod_list[eod_idx]:
                state['snapshots'].append({'ts': eod_list[eod_idx], 'pnl': round(unrealized(last['close_price']), 2)})
                eod_idx += 1
            # 数据截止点快照：无论是否覆盖到 23:00，都以最后可见收盘价记录浮动盈亏，
            # 保证资金曲线反映未平仓头寸的浮动盈亏（符合「当日收盘价计入曲线」规则）。
            state['snapshots'].append({'ts': last['close_time'], 'pnl': round(unrealized(last['close_price']), 2)})
            result = '未平仓-截止'
            close_price = last['close_price']
            close_ts = last['close_time']
            net_pnl = None  # 未了结，不计入已平仓盈亏；浮盈见 snapshots
            # 计算截止浮盈（不含点差，未平仓）
            net_pnl_unreal = round(unrealized(last['close_price']), 2)
            state['phase'] = 'closed'
            return {
                'result': result, 'close_price': close_price, 'close_ts': close_ts,
                'net_pnl': None, 'pnl_r': None, 'unrealized_final': net_pnl_unreal,
                'snapshots': state['snapshots'], 'closed': False,
            }

    pnl_r = (net_pnl / risk_u) if (risk_u and net_pnl is not None) else None
    return {
        'result': result, 'close_price': close_price, 'close_ts': close_ts,
        'net_pnl': round(net_pnl, 2) if net_pnl is not None else None,
        'pnl_r': round(pnl_r, 3) if pnl_r is not None else None,
        'unrealized_final': None,
        'snapshots': state['snapshots'], 'closed': True,
    }


# ---------------- 最优盈亏比扫描 ----------------
def scan_best_rr(signals_subset, bars, open_times, eod_list, lot, spread_pips):
    ks = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    out = []
    best_k = None
    best_ev = None
    for k in ks:
        rs = []
        for s in signals_subset:
            entry = s['entry']
            sl = s['sl']
            direction = s['direction']
            if sl is None or entry is None:
                continue
            sldist = abs(entry - sl)
            if sldist <= 0:
                continue
            tp1 = entry + k * sldist if direction == 'long' else entry - k * sldist
            sig = dict(s)
            sig['tp1'] = tp1
            sig['tp2'] = None
            r = backtest_one(sig, bars, open_times, eod_list)
            if r['closed'] and r['pnl_r'] is not None:
                rs.append(r['pnl_r'])
        ev = sum(rs) / len(rs) if rs else 0.0
        out.append({'k': k, 'ev': round(ev, 3), 'n': len(rs)})
        if best_ev is None or ev > best_ev:
            best_ev = ev
            best_k = k
    return {'curve': out, 'best_k': best_k, 'best_ev': round(best_ev, 3) if best_ev is not None else None}


# ---------------- 主入口 ----------------
def run_backtest(signals_raw, lot=0.01, start_capital=200.0, spread_pips=30.0, review_end_str=None,
                 bars=None, source='db'):
    # 1. 解析信号
    signals = []
    skipped = []
    for idx, row in enumerate(signals_raw):
        ts = parse_signal_time(row.get('signal_time'))
        direction = parse_dir(row.get('direction'))
        entry = parse_num(row.get('entry'))
        sl = parse_num(row.get('sl'))
        tp1 = parse_num(row.get('tp1'))
        tp2 = parse_num(row.get('tp2'))
        if ts is None or direction is None or entry is None:
            skipped.append({'row': idx, 'reason': '时间/方向/入场解析失败'})
            continue
        signals.append({
            'idx': idx, 'ts': ts,
            'symbol': (row.get('symbol') or '').strip(),
            'interval': (row.get('interval') or '').strip(),
            'pattern': (row.get('pattern') or '未命名').strip(),
            'direction': direction, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
            'lot': lot, 'spread_pips': spread_pips,
        })
    if not signals:
        return {'code': 400, 'msg': '无有效信号', 'skipped': skipped}

    # 2. 数据范围
    min_day = datetime.fromtimestamp(min(s['ts'] for s in signals) / 1000)
    if review_end_str:
        end_dt = datetime.fromtimestamp(parse_signal_time(review_end_str) / 1000)
    else:
        max_day = datetime.fromtimestamp(max(s['ts'] for s in signals) / 1000)
        end_dt = max_day + timedelta(days=1)
    start_dt = datetime(min_day.year, min_day.month, min_day.day, 7, 0)
    end_dt = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 0)
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    # 3. 行情数据：Binance 源用调用方传入的 bars，DB 源走本地查询（行为不变）
    if bars is None:
        table = TABLE_MAP.get('1m')
        if not table:
            return {'code': 400, 'msg': '无 1m 表映射', 'skipped': skipped}
        bars, truncated = query_kline(table, start_ts, end_ts)
        if not bars:
            return {'code': 204, 'msg': '无行情数据', 'skipped': skipped}
        # 规范化字段类型（pymysql 价格列为 Decimal，时间戳为 int）
        for b in bars:
            b['open_time'] = int(b['open_time'])
            b['close_time'] = int(b['close_time'])
            b['open_price'] = float(b['open_price'])
            b['high_price'] = float(b['high_price'])
            b['low_price'] = float(b['low_price'])
            b['close_price'] = float(b['close_price'])
    else:
        truncated = False
        # bars 已由调用方（Binance 适配器）归一化为数值字段

    # 预构建 open_time 列表（升序）
    bars_sorted = sorted(bars, key=lambda b: b['open_time'])
    open_times = [b['open_time'] for b in bars_sorted]
    if not bars_sorted:
        return {'code': 204, 'msg': '无行情数据', 'skipped': skipped}

    # 4. 价格对齐校验：把整组价位按 delta = 同刻现价 - 表格入场 整体平移，
    #     使入场对齐到实际现价；平移保持 SL/TP 与入场的距离不变（R 倍数不变）。
    #     - DB 源：仅当 |delta| > ALIGN_TOL(3.0) 时平移（点差/报价源偏差）。
    #     - Binance 源：容差=tick（按表精度推导），只要有跨源价差就平移，吃真实不利滑点。
    tick, max_dec = _infer_tick(signals_raw)
    align_tol = tick if source == 'binance' else ALIGN_TOL
    round_dp = max_dec if source == 'binance' else 2
    aligned_count = 0
    for s in signals:
        bar = _bar_at(bars_sorted, open_times, s['ts'])
        s['orig_entry'] = s['entry']
        s['db_price'] = float(bar['open_price']) if bar is not None else None
        if bar is None:
            s['aligned'] = False
            s['align_delta'] = 0.0
            continue
        delta = round(s['db_price'] - s['entry'], round_dp)
        s['align_delta'] = delta
        if abs(delta) > align_tol:
            s['entry'] = round(s['entry'] + delta, round_dp)
            if s['sl'] is not None:
                s['sl'] = round(s['sl'] + delta, round_dp)
            if s['tp1'] is not None:
                s['tp1'] = round(s['tp1'] + delta, round_dp)
            if s['tp2'] is not None:
                s['tp2'] = round(s['tp2'] + delta, round_dp)
            s['aligned'] = True
            aligned_count += 1
        else:
            s['aligned'] = False

    # 4.5 每日 23:00 快照时间点
    eod_list = []
    d = start_dt.date()
    end_date = end_dt.date()
    while d <= end_date:
        eod = datetime(d.year, d.month, d.day, 23, 0)
        eod_list.append(int(eod.timestamp() * 1000))
        d += timedelta(days=1)

    # 5. 逐笔回测
    trades = []
    for s in signals:
        r = backtest_one(s, bars_sorted, open_times, eod_list)
        trades.append({
            'idx': s['idx'],
            'signal_time': datetime.fromtimestamp(s['ts'] / 1000).strftime('%Y-%m-%d %H:%M'),
            'session': classify_session(s['ts']),
            'symbol': s['symbol'],
            'interval': s['interval'],
            'pattern': s['pattern'],
            'direction': '做多' if s['direction'] == 'long' else '做空',
            'entry': s['entry'], 'sl': s['sl'], 'tp1': s['tp1'], 'tp2': s['tp2'],
            'orig_entry': s['orig_entry'], 'db_price': s['db_price'],
            'aligned': s['aligned'], 'align_delta': s['align_delta'],
            'result': r['result'],
            'close_time': datetime.fromtimestamp(r['close_ts'] / 1000).strftime('%Y-%m-%d %H:%M') if r['close_ts'] else None,
            'close_price': r['close_price'],
            'pnl_u': r['net_pnl'],
            'pnl_r': r['pnl_r'],
            'closed': r['closed'],
            'unrealized_final': r.get('unrealized_final'),
            'snapshots': r['snapshots'],
        })

    # 6. 策略统计（仅已了结）
    stats = {}
    for t in trades:
        if not t['closed']:
            continue
        p = t['pattern']
        st = stats.setdefault(p, {'n': 0, 'wins': 0, 'losses': 0, 'pnl_sum': 0.0,
                                  'rr_list': [], 'r_list': [], 'win_pnl': 0.0, 'loss_pnl': 0.0})
        st['n'] += 1
        pnl = t['pnl_u'] or 0.0
        st['pnl_sum'] += pnl
        if pnl > 0:
            st['wins'] += 1
            st['win_pnl'] += pnl
        else:
            st['losses'] += 1
            st['loss_pnl'] += (-pnl)
        if t['pnl_r'] is not None:
            st['r_list'].append(t['pnl_r'])
        # RR（目标/止损距离比）
        if t['sl'] is not None:
            tp = t['tp2'] if t['tp2'] is not None else t['tp1']
            if tp is not None:
                rr = abs(tp - t['entry']) / abs(t['entry'] - t['sl'])
                st['rr_list'].append(rr)
    strategy_stats = []
    for p, st in stats.items():
        ev = (sum(st['r_list']) / len(st['r_list'])) if st['r_list'] else 0.0
        pf = (st['win_pnl'] / st['loss_pnl']) if st['loss_pnl'] > 0 else (None if st['win_pnl'] == 0 else 999)
        strategy_stats.append({
            'pattern': p, 'n': st['n'], 'wins': st['wins'], 'losses': st['losses'],
            'win_rate': round(st['wins'] / st['n'], 3) if st['n'] else 0,
            'avg_rr': round(sum(st['rr_list']) / len(st['rr_list']), 2) if st['rr_list'] else None,
            'ev_r': round(ev, 3),
            'profit_factor': round(pf, 2) if pf is not None else None,
            'total_pnl': round(st['pnl_sum'], 2),
        })
    strategy_stats.sort(key=lambda x: x['pattern'])

    # 6.5 时段（亚/欧/美盘）盈利统计（仅已了结交易，未平仓不计入）
    def _blank_session():
        return {'n': 0, 'wins': 0, 'losses': 0, 'pnl_sum': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0}

    session_stats = {'亚盘': _blank_session(), '欧盘': _blank_session(), '美盘': _blank_session()}
    session_by_pattern = {}
    for t in trades:
        if not t['closed']:
            continue
        ses = t['session']
        p = t['pattern']
        pnl = t['pnl_u'] or 0.0
        d = session_stats[ses]
        d['n'] += 1
        d['pnl_sum'] += pnl
        if pnl > 0:
            d['wins'] += 1
            d['win_pnl'] += pnl
        else:
            d['losses'] += 1
            d['loss_pnl'] += (-pnl)
        sp = session_by_pattern.setdefault(
            (p, ses),
            {'pattern': p, 'session': ses, 'n': 0, 'wins': 0, 'losses': 0,
             'pnl_sum': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0},
        )
        sp['n'] += 1
        sp['pnl_sum'] += pnl
        if pnl > 0:
            sp['wins'] += 1
            sp['win_pnl'] += pnl
        else:
            sp['losses'] += 1
            sp['loss_pnl'] += (-pnl)

    def _finalize(d):
        d['win_rate'] = round(d['wins'] / d['n'], 3) if d['n'] else 0
        d['total_pnl'] = round(d['pnl_sum'], 2)
        pf = (d['win_pnl'] / d['loss_pnl']) if d['loss_pnl'] > 0 else (None if d['win_pnl'] == 0 else 999)
        d['profit_factor'] = round(pf, 2) if pf is not None else None
        d.pop('pnl_sum', None)
        d.pop('win_pnl', None)
        d.pop('loss_pnl', None)
        return d

    for ses in ('亚盘', '欧盘', '美盘'):
        _finalize(session_stats[ses])
    session_by_pattern_list = []
    for key, sp in session_by_pattern.items():
        _finalize(sp)
        session_by_pattern_list.append(sp)
    session_by_pattern_list.sort(key=lambda x: (x['pattern'], x['session']))

    # 7. 最优盈亏比扫描（按策略）
    best_rr = []
    by_pattern = {}
    for s in signals:
        by_pattern.setdefault(s['pattern'], []).append(s)
    for p, subset in by_pattern.items():
        best_rr.append({'pattern': p, **scan_best_rr(subset, bars_sorted, open_times, eod_list, lot, spread_pips)})

    # 8. 资金曲线
    points = []
    for t in trades:
        if t['closed'] and t['pnl_u'] is not None:
            points.append((int(datetime.strptime(t['close_time'], '%Y-%m-%d %H:%M').timestamp() * 1000), 'close', t['idx'], t['pnl_u']))
        for snap in t['snapshots']:
            points.append((snap['ts'], 'snap', t['idx'], snap['pnl']))
    points.sort(key=lambda x: x[0])
    closed_sum = 0.0
    unreal = {}
    equity_series = []
    last_eq = None
    for ts, kind, idx, pnl in points:
        if kind == 'close':
            closed_sum += pnl
            unreal.pop(idx, None)
        else:
            unreal[idx] = pnl
        eq = round(start_capital + closed_sum + sum(unreal.values()), 2)
        equity_series.append({
            'ts': ts,
            'date': datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M'),
            'equity': eq,
            'closed_sum': round(closed_sum, 2),
            'unrealized': round(sum(unreal.values()), 2),
        })
        last_eq = eq
    # 按 ts 去重（保留最后）
    seen = {}
    for pt in equity_series:
        seen[pt['ts']] = pt
    equity_series = list(seen.values())
    equity_series.sort(key=lambda x: x['ts'])

    # 9. 汇总
    eq_vals = [pt['equity'] for pt in equity_series] if equity_series else [start_capital]
    end_equity = eq_vals[-1]
    max_eq = max(eq_vals)
    min_eq = min(eq_vals)
    max_dd = round((max_eq - min_eq) / max_eq, 3) if max_eq > 0 else 0
    breach = sum(1 for v in eq_vals if v < 0)
    closed_count = sum(1 for t in trades if t['closed'])
    open_count = sum(1 for t in trades if not t['closed'])

    return {
        'code': 200,
        'msg': 'success',
        'skipped': skipped,
        'truncated': truncated,
        'data_range': {'start': start_dt.strftime('%Y-%m-%d %H:%M'), 'end': end_dt.strftime('%Y-%m-%d %H:%M')},
        'trades': trades,
        'strategy_stats': strategy_stats,
        'session_stats': session_stats,
        'session_by_pattern': session_by_pattern_list,
        'best_rr': best_rr,
        'equity': equity_series,
        'summary': {
            'start_capital': start_capital,
            'end_equity': round(end_equity, 2),
            'total_return': round((end_equity / start_capital - 1), 3),
            'max_drawdown': max_dd,
            'breach_count': breach,
            'closed_count': closed_count,
            'open_count': open_count,
            'total_signals': len(trades),
            'aligned_count': aligned_count,
            'align_tol': ALIGN_TOL,
        },
    }
