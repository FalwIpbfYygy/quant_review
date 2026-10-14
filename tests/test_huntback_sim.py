# -*- coding: utf-8 -*-
"""huntback_sim.py 单元测试（M1）。

纯计算内核测试，使用合成 1m 柱 + hz_engine.build 生成的真实几何，零网络/零 DB。
运行：pytest tests/test_huntback_sim.py -q   （按用户纪律在服务器/本地由用户执行）

几何口径（已对参考报告 200 日逐日核对）：
  short: zone_a=zoneHi(最高挂单), zone_mid, zone_b=zoneLo(最低)
  long : zone_a=zoneLo(最低挂单), zone_mid, zone_b=zoneHi(最高)
  三区独立持仓，每区各自 fill/stop/tp1/tp2/be_arm/be_out，单日 P&L = 三区之和。
"""
import pytest

from huntzone.hz_engine import build
from huntzone import huntback_sim as H


# ---------------------------------------------------------------------------
# 夹具：合成档位 + 1m 柱
# ---------------------------------------------------------------------------
BASE = 1735689600000  # 2026-01-01 UTC 00:00（= 北京 08:00）


def _lad(direction="short", open_px=2000.0, S=100.0, prev_close=1980.0):
    """用真实 build 生成几何，保证 zone_hi/lo/mid/stop/exh1/t1 正确。"""
    return build(open_px, S, direction, prev_close=prev_close)


def _bar(t_min, o, h, l, c):
    return (BASE + t_min * 60000, o, h, l, c)


# short 几何（open=2000,S=100,prev=1980）：
#   zone_a=2061.8(zoneHi)  zone_mid=2050.0  zone_b=2038.2(zoneLo)  stop=2080.9  exh1=1938.2  t1=1980
# long  几何：
#   zone_a=1938.2(zoneLo)  zone_mid=1950.0  zone_b=1961.8(zoneHi)  stop=1919.1  exh1=2061.8  t1=1980
SHORT = dict(za=2061.8, zm=2050.0, zb=2038.2, stop=2080.9, exh1=1938.2, t1=1980.0)
LONG = dict(za=1938.2, zm=1950.0, zb=1961.8, stop=1919.1, exh1=2061.8, t1=1980.0)


def _events_by_zone(res):
    out = {}
    for e in res["events"]:
        out.setdefault(e.tag, []).append(e)
    return out


# ---------------------------------------------------------------------------
# 1. fill（limit 成交）+ 收盘强平
# ---------------------------------------------------------------------------
def test_fill_short():
    # short: zone_b=2038.2 最低挂单最先成交；h=2045 仅够 zone_b，未及 zone_mid=2050
    lad = _lad()
    bars = [_bar(0, 2040, 2045, 2035, 2040)]
    res = H._run(lad, bars, 20)
    ev = _events_by_zone(res)
    assert "zone_b" in ev and ev["zone_b"][0].type == "fill"
    assert ev["zone_b"][0].price == pytest.approx(SHORT["zb"])
    assert ev["zone_b"][-1].type == "force22"
    # 仅 zone_b 成交，realized = entry - close = 2038.2 - 2040 = -1.8
    assert res["realized_usd"] == pytest.approx(-1.8, abs=1e-6)
    assert res["outcome"] == "亏损"


# ---------------------------------------------------------------------------
# 2. stop（硬止损，三区全损）
# ---------------------------------------------------------------------------
def test_stop_short():
    lad = _lad()
    bars = [
        _bar(0, 2060, 2070, 2055, 2065),        # h>=zone_a → 三区全 fill
        _bar(1, 2085, 2090, 2080, 2085),        # h>=stop(2080.9) → 三区全 stop
    ]
    res = H._run(lad, bars, 20)
    stops = [e for e in res["events"] if e.type == "stop"]
    assert len(stops) == 3                      # 三区各一次硬止损
    # za=-(2061.8-2080.9) zm=-(2050-2080.9) zb=-(2038.2-2080.9) = -19.1-30.9-42.7
    assert res["realized_usd"] == pytest.approx(-92.7, abs=1e-6)
    assert res["outcome"] == "亏损"


# ---------------------------------------------------------------------------
# 3. tp1 + tp2（origin 模式，关保本以隔离）
# ---------------------------------------------------------------------------
def test_tp1_tp2_origin():
    lad = _lad()
    bars = [
        _bar(0, 2060, 2070, 2055, 2065),        # 三区全 fill
        _bar(1, 2000, 2005, 1975, 1985),        # l<=t1(1980) → 三区 tp1(平50%)
        _bar(2, 1980, 1985, 1930, 1940),        # l<=exh1(1938.2) → 三区 tp2(平余50%)
    ]
    res = H._run(lad, bars, None)               # trigger=None => origin
    types = [e.type for e in res["events"]]
    assert types.count("fill") == 3
    assert types.count("tp1") == 3
    assert types.count("tp2") == 3
    # za=0.5*(2061.8-1980)+0.5*(2061.8-1938.2)=102.7
    # zm=0.5*(2050-1980)+0.5*(2050-1938.2)=90.9
    # zb=0.5*(2038.2-1980)+0.5*(2038.2-1938.2)=79.1  => 272.7
    assert res["realized_usd"] == pytest.approx(272.7, abs=1e-6)
    assert res["outcome"] == "盈利"


# ---------------------------------------------------------------------------
# 4. tp1 + be_arm + be_out（保本，trigger=20）
# ---------------------------------------------------------------------------
def test_tp1_be_arm_be_out():
    lad = _lad()
    bars = [
        _bar(0, 2065, 2075, 2060, 2065),        # 三区全 fill
        _bar(1, 2000, 2005, 1970, 1985),        # tp1(l<=1980) + be_arm(l<=entry-20)
        _bar(2, 2060, 2070, 2055, 2065),        # h>=entry → be_out(0盈亏)
    ]
    res = H._run(lad, bars, 20)
    ev = _events_by_zone(res)
    for tag in ("zone_a", "zone_mid", "zone_b"):
        seq = [e.type for e in ev[tag]]
        assert seq == ["fill", "tp1", "be_arm", "be_out"], tag
    # be_out 盈亏=0，仅 tp1 贡献：0.5*(entry-t1) 三区之和
    # za=0.5*81.8=40.9  zm=0.5*70=35  zb=0.5*58.2=29.1  => 105.0
    assert res["realized_usd"] == pytest.approx(105.0, abs=1e-6)
    assert res["outcome"] == "盈利"


# ---------------------------------------------------------------------------
# 5. force22（22:30 收盘强平）
# ---------------------------------------------------------------------------
def test_force22():
    lad = _lad()
    bars = [
        _bar(0, 2040, 2075, 2035, 2060),        # 三区全 fill
        _bar(1, 2050, 2060, 2045, 2055),        # 震荡，无退出
        _bar(2, 2055, 2060, 2050, 2052),        # 末根 close=2052
    ]
    res = H._run(lad, bars, 20)
    f22 = [e for e in res["events"] if e.type == "force22"]
    assert len(f22) == 3
    assert all(e.time == "22:30" for e in f22)
    # za=2061.8-2052=9.8  zm=2050-2052=-2  zb=2038.2-2052=-13.8  => -6.0
    assert res["realized_usd"] == pytest.approx(-6.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 6. force_sl2=(b)（任 2 区硬止损 → 幸存活仓腿当根强平）
# ---------------------------------------------------------------------------
def test_force_sl2():
    # (a) 报告口径实证：三区共享同一止损，同根三区同触止损 → 各记 stop，force_sl2 休眠
    #     （参考报告 200 日 force_sl2 events = 0）。故正常场景不应产生 force_sl2 事件。
    lad = _lad()
    bars = [
        _bar(0, 2065, 2070, 2060, 2065),        # h=2070≥zone_a → 三区全 fill
        _bar(1, 2085, 2095, 2080, 2090),        # h>=stop(2080.9) → 三区同根各 stop
    ]
    res = H._run(lad, bars, 20)
    stops = [e for e in res["events"] if e.type == "stop"]
    fsl2 = [e for e in res["events"] if e.type == "force_sl2"]
    assert len(stops) == 3, "同根三区同触止损应各记 stop"
    assert len(fsl2) == 0, "共享止损下 force_sl2 休眠（报告实证 0）"
    assert res["realized_usd"] == pytest.approx(-92.7, abs=1e-6)

    # (b) 分支级：force_sl2 强平数学（白盒，验证幸存腿按当根收盘强平，因共享止损下不可达故单独覆盖）
    st = H._ZoneState("zone_b", 2038.2, "short", lad, 20)
    st.filled = True
    st.state = "FILLED"
    st.force_close((BASE + 1, 2085, 2090, 2080, 2085), "force_sl2", BASE + H._FORCE_CLOSE_OFFSET_MS)
    assert st.exit_type == "force_sl2"
    assert st.realized == pytest.approx(2038.2 - 2085, abs=1e-6)  # short: entry - close


# ---------------------------------------------------------------------------
# 7. 同根冲突 SL 优先（stop 压 tp1）
# ---------------------------------------------------------------------------
def test_sl_priority():
    lad = _lad()
    # 单根同时 h>=stop(2080.9) 且 l<=t1(1980)：SL 优先，无 tp1
    bars = [_bar(0, 2040, 2100, 1970, 2050)]
    res = H._run(lad, bars, 20)
    ev = _events_by_zone(res)
    for tag in ("zone_a", "zone_mid", "zone_b"):
        seq = [e.type for e in ev[tag]]
        assert seq[0] == "fill"
        assert seq[1] == "stop"                # SL 优先
        assert "tp1" not in seq                # 不产生 tp1


# ---------------------------------------------------------------------------
# 8. 确定性 + 无未来函数
# ---------------------------------------------------------------------------
def test_determinism_and_no_future():
    lad = _lad()
    bars = [
        _bar(0, 2060, 2070, 2055, 2065),
        _bar(1, 2000, 2005, 1975, 1985),
        _bar(2, 1980, 1985, 1930, 1940),
        _bar(3, 2050, 2055, 2048, 2052),
    ]
    r1 = H._run(lad, bars, 20)
    r2 = H._run(lad, bars, 20)
    assert r1 == r2                            # 逐字节确定
    force_close_ms = BASE + H._FORCE_CLOSE_OFFSET_MS
    for e in r1["events"]:
        assert e.ts_ms <= force_close_ms       # 无引用未来 bar


# ---------------------------------------------------------------------------
# 9. K 系数（默认 1，realized_usd == Σzone * K）
# ---------------------------------------------------------------------------
def test_k_coefficient():
    assert H.K_USD == 1.0
    lad = _lad()
    bars = [
        _bar(0, 2060, 2070, 2055, 2065),
        _bar(1, 2085, 2090, 2080, 2085),        # 三区 stop
    ]
    res = H._run(lad, bars, 20)
    # K=1 ⇒ 总 USD = 三区点位之和
    assert res["realized_usd"] == pytest.approx(sum(res["zones"].values()), abs=1e-6)


# ---------------------------------------------------------------------------
# 10. 缺失 / 无成交
# ---------------------------------------------------------------------------
def test_missing_empty_bars():
    lad = _lad()
    res = H._run(lad, [], 20)
    assert res["missing"] is True
    assert res["realized_usd"] == 0.0
    assert res["outcome"] == "持平（缺数据）"


def test_no_fill_no_signal():
    lad = _lad()
    # 价格始终远低于挂单价（short 需 h>=zone_a=2061.8），永不成交
    bars = [_bar(0, 2000, 2010, 1995, 2005),
            _bar(1, 2005, 2012, 1998, 2002)]
    res = H._run(lad, bars, 20)
    assert not any(e.type == "fill" for e in res["events"])
    assert res["realized_usd"] == 0.0
    assert res["outcome"] == "持平"
