# -*- coding: utf-8 -*-
"""
Binance 行情适配器（新增模块，不改动 backtest.py / main.py 现有运行逻辑）

职责：
- fetch_klines_binance: 从 Binance fapi 分页拉取 1m K线，归一化为回测引擎字段
  （open_time/open_price/high_price/low_price/close_price/close_time，均为数值）。
- run_backtest_binance: 按 symbol 分组拉取 → 调 run_backtest(bars=, source='binance')
  → 多品种结果合并为与 /api/backtest 相同 schema。

点差偏移修正（核心）：沿用 backtest.run_backtest 既有的 delta 整体平移逻辑，
Binance 源下把对齐容差降到 tick（≈必平移），实现"入场对齐到 Binance 同刻 open 价、
TP/SL 同加 Δ=M−entry 的不利滑点损耗"。
"""
import time
from datetime import datetime, timedelta

import requests
from data.data_sync import PROXIES, PRICE_OFFSET, MAX_RETRIES, RETRY_DELAY
from core.backtest import run_backtest, parse_signal_time

from config import FAPI_KLINES as FUTURES_KLINES_URL  # 价格接口基址
PAGE_LIMIT = 1500  # fapi 单次最大条数


def _symbol_to_binance(sym):
    """信号表 symbol → (Binance 合约 symbol, 价格偏移)。
    - 含 PAXG → PAXGUSDT，偏移 PRICE_OFFSET(12.0)（对齐信号表 PAXG 报价口径）
    - 含 XAU  → ，偏移 0（ 也走  接口）
    - 其他/空 → 默认 ，偏移 0
    """
    s = (sym or "").upper()
    if "PAXG" in s:
        return "PAXGUSDT", PRICE_OFFSET
    if "XAU" in s:
        return "", 0.0
    return "", 0.0


def _get_with_retry(url, timeout=15):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, proxies=PROXIES, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if 400 <= resp.status_code < 500:
                # 参数/符号错误不重试
                return []
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    return []


def fetch_klines_binance(symbol, interval, start_ms, end_ms):
    """分页拉取 [start_ms, end_ms] 的 K线，归一化为回测引擎字段。
    返回 list[dict]: open_time, open_price, high_price, low_price, close_price, close_time
    """
    bn_sym, offset = _symbol_to_binance(symbol)
    bars = []
    cur = int(start_ms)
    end = int(end_ms)
    pages = 0
    while True:
        url = (f"{FUTURES_KLINES_URL}?symbol={bn_sym}&interval={interval}"
               f"&startTime={cur}&endTime={end}&limit={PAGE_LIMIT}")
        raw = _get_with_retry(url)
        if not raw:
            break
        for k in raw:
            bars.append({
                "open_time": int(k[0]),
                "open_price": float(k[1]) + offset,
                "high_price": float(k[2]) + offset,
                "low_price": float(k[3]) + offset,
                "close_price": float(k[4]) + offset,
                "close_time": int(k[6]),
            })
        pages += 1
        last_ct = bars[-1]["close_time"]
        # 已覆盖到窗口末端，或超过保护页数 → 停止
        if last_ct >= end or pages > 5000:
            break
        nxt = last_ct + 1
        if nxt <= cur:
            break
        cur = nxt
    return bars


def _window(signals_raw, review_end):
    """复用 run_backtest 的时间窗约定：start=最早信号日 7:00，
    end=reviewEnd日23:00 或 末信号日+1天 23:00。返回 (start_ms, end_ms)。"""
    times = [parse_signal_time(r.get('signal_time')) for r in signals_raw]
    times = [t for t in times if t]
    if not times:
        return None, None
    min_ts = min(times)
    max_ts = max(times)
    min_dt = datetime.fromtimestamp(min_ts / 1000)
    if review_end:
        re_ts = parse_signal_time(review_end)
        if re_ts:
            end_dt = datetime.fromtimestamp(re_ts / 1000)
        else:
            max_dt = datetime.fromtimestamp(max_ts / 1000)
            end_dt = max_dt + timedelta(days=1)
    else:
        max_dt = datetime.fromtimestamp(max_ts / 1000)
        end_dt = max_dt + timedelta(days=1)
    start_dt = datetime(min_dt.year, min_dt.month, min_dt.day, 7, 0)
    end_dt = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 0)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


def run_backtest_binance(signals_raw, lot=0.01, start_capital=200.0, spread_pips=30.0, review_end=None):
    start_ms, end_ms = _window(signals_raw, review_end)
    if start_ms is None:
        return {'code': 400, 'msg': '无有效信号时间', 'skipped': []}

    # 按 symbol 分组（无 symbol 默认 ）
    groups = {}
    for row in signals_raw:
        if parse_signal_time(row.get('signal_time')) is None:
            continue
        sym = (row.get('symbol') or '').strip() or ''
        groups.setdefault(sym, []).append(row)

    results = []
    for sym, rows in groups.items():
        bars = fetch_klines_binance(sym, '1m', start_ms, end_ms)
        if not bars:
            results.append({
                'code': 204, 'msg': f'{sym} 无行情数据',
                'skipped': [{'row': i, 'reason': f'{sym} 无 Binance 行情'} for i in range(len(rows))],
                'trades': [], 'strategy_stats': [], 'best_rr': [], 'equity': [],
                'data_range': None, 'summary': None,
            })
            continue
        r = run_backtest(rows, lot, start_capital, spread_pips, review_end,
                         bars=bars, source='binance')
        results.append(r)

    valid = [r for r in results if r.get('code') == 200 and r.get('trades')]
    if not valid:
        return {'code': 204, 'msg': 'Binance 无可用行情/信号', 'skipped': []}
    if len(valid) == 1:
        out = dict(valid[0])
        out['source'] = 'binance'
        if out.get('summary'):
            out['summary']['align_tol'] = 'tick'
        return out
    return merge_backtest_results([v for v in valid], start_capital)


def merge_backtest_results(results, start_capital):
    """合并多品种 run_backtest 结果，复用与 run_backtest step 8 完全一致的聚合算法。"""
    trades = []
    for r in results:
        trades.extend(r.get('trades', []))

    # 策略统计合并（按形态）：直接从合并后的 trades 重算，与 run_backtest step 6 一致
    stats = {}
    for t in trades:
        if not t.get('closed'):
            continue
        p = t['pattern']
        st = stats.setdefault(p, {'n': 0, 'wins': 0, 'losses': 0, 'pnl_sum': 0.0,
                                  'rr_list': [], 'r_list': [], 'win_pnl': 0.0, 'loss_pnl': 0.0})
        st['n'] += 1
        pnl = t.get('pnl_u') or 0.0
        st['pnl_sum'] += pnl
        if pnl > 0:
            st['wins'] += 1
            st['win_pnl'] += pnl
        else:
            st['losses'] += 1
            st['loss_pnl'] += (-pnl)
        if t.get('pnl_r') is not None:
            st['r_list'].append(t['pnl_r'])
        if t.get('sl') is not None:
            tp = t.get('tp2') if t.get('tp2') is not None else t.get('tp1')
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

    # 最优盈亏比合并（按 pattern 去重，保留首个）
    best_rr_map = {}
    for r in results:
        for b in r.get('best_rr', []):
            best_rr_map.setdefault(b['pattern'], b)
    best_rr = list(best_rr_map.values())

    # 资金曲线重算（与 run_backtest step 8 一致）
    points = []
    for t in trades:
        if t.get('closed') and t.get('pnl_u') is not None:
            try:
                ct_ms = int(datetime.strptime(t['close_time'], '%Y-%m-%d %H:%M').timestamp() * 1000)
            except Exception:
                ct_ms = 0
            points.append((ct_ms, 'close', t['idx'], t['pnl_u']))
        for snap in (t.get('snapshots') or []):
            points.append((snap['ts'], 'snap', t['idx'], snap['pnl']))
    points.sort(key=lambda x: x[0])
    closed_sum = 0.0
    unreal = {}
    equity_series = []
    for ts, kind, idx, pnl in points:
        if kind == 'close':
            closed_sum += pnl
            unreal.pop(idx, None)
        else:
            unreal[idx] = pnl
        eq = round(start_capital + closed_sum + sum(unreal.values()), 2)
        equity_series.append({
            'ts': ts,
            'date': datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M') if ts else '',
            'equity': eq,
            'closed_sum': round(closed_sum, 2),
            'unrealized': round(sum(unreal.values()), 2),
        })
    seen = {}
    for pt in equity_series:
        seen[pt['ts']] = pt
    equity_series = list(seen.values())
    equity_series.sort(key=lambda x: x['ts'])

    eq_vals = [pt['equity'] for pt in equity_series] if equity_series else [start_capital]
    end_equity = eq_vals[-1]
    max_eq = max(eq_vals)
    min_eq = min(eq_vals)
    max_dd = round((max_eq - min_eq) / max_eq, 3) if max_eq > 0 else 0
    breach = sum(1 for v in eq_vals if v < 0)
    closed_count = sum(1 for t in trades if t.get('closed'))
    open_count = sum(1 for t in trades if not t.get('closed'))

    return {
        'code': 200, 'msg': 'success',
        'skipped': [], 'truncated': False,
        'data_range': valid_first(results).get('data_range'),
        'trades': trades,
        'strategy_stats': strategy_stats,
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
            'aligned_count': closed_count,
            'align_tol': 'tick',
        },
        'source': 'binance',
    }


def valid_first(results):
    for r in results:
        if r.get('code') == 200 and r.get('trades'):
            return r
    return {}
