# rs_test_paxg.py — v5 冻结修复回归测试（Tessa 测试计划 G1-G6 / L1-L2 / B1-B2）
# 运行：python rs_test_paxg.py
import sys, copy
import rs_backtest_paxg as P
from rs_data import resample_htf
from collections import Counter

base = P.get_5m(P.CONFIG["SYMBOL"], (2024, 1, 1), (2026, 10, 3), P.CACHE_5M)
ltf5 = base
mtf = resample_htf(base, 15); htf = resample_htf(base, 60); htf4 = resample_htf(base, 240)

pass_n = 0; fail_n = 0
def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1; print(f"  ✅ PASS  {name}  {detail}")
    else:
        fail_n += 1; print(f"  ❌ FAIL  {name}  {detail}")

def run(cfg_override=None, **kw):
    cfg = copy.deepcopy(P.CONFIG)
    if cfg_override:
        cfg.update(cfg_override)
    tr, _ = P.run_backtest(mtf, htf, htf4, ltf5, cfg=cfg, **kw)
    return tr

def rev_count(tr, d):
    return sum(1 for t in tr if t["direction"] == d and t["exit_reason"] == "REV")

def net(tr, d):
    return sum(t["pnl_points"] for t in tr if t["direction"] == d)

print("=== 回归闸门（防回退，2024+ 窗口，289499 根 5m）===")
# 基线浮动（SHORT 开）
base_fl = run({"REV_REF_FROZEN": False, "PAXG_SHORT_ENABLED": True})
# 双冻结（SHORT 开）
dual = run({"REV_REF_FROZEN": True, "PAXG_SHORT_ENABLED": True})
# 仅冻结 LONG（SHORT 开，浮动）
onlyL = run({"REV_REF_FROZEN": False, "PAXG_SHORT_ENABLED": True},
            rev_trH_frozen_long=True, rev_trH_frozen_short=False)
# 仅冻结 SHORT（SHORT 开，浮动）
onlyS = run({"REV_REF_FROZEN": False, "PAXG_SHORT_ENABLED": True},
            rev_trH_frozen_short=True, rev_trH_frozen_long=False)

# G1 双冻结主效果：SHORT REV==1 且 LONG REV==1（基线 12/16）
check("G1 双冻结 SHORT REV==1", rev_count(dual, "SHORT") == 1, f"实得 {rev_count(dual,'SHORT')}")
check("G1 双冻结 LONG REV==1", rev_count(dual, "LONG") == 1, f"实得 {rev_count(dual,'LONG')}")
# G2 冻结不恶化 LONG：LONG 净 ≥ +140
check("G2 双冻结 LONG 净≥+140", net(dual, "LONG") >= 140, f"实得 {net(dual,'LONG'):.1f}")
# G3 SHORT 方向隔离：冻结 SHORT 参考位对 SHORT 净盈亏影响 ≤ 2pt
check("G3 SHORT 净不受冻结影响(≤2pt)", abs(net(dual,'SHORT') - net(base_fl,'SHORT')) <= 2,
      f"dual={net(dual,'SHORT'):.1f} base={net(base_fl,'SHORT'):.1f}")
# G4 信号数稳定：双冻结 n==78（基线 79，仅退出原因迁移）
check("G4 双冻结 n==78", len(dual) == 78, f"实得 {len(dual)}")
# G5 仅冻结 LONG：SHORT REV==12 不变；LONG REV==1
check("G5 仅冻结LONG→SHORT REV==12", rev_count(onlyL, "SHORT") == 12, f"实得 {rev_count(onlyL,'SHORT')}")
check("G5 仅冻结LONG→LONG REV==1", rev_count(onlyL, "LONG") == 1, f"实得 {rev_count(onlyL,'LONG')}")
# G6 仅冻结 SHORT：LONG REV==16 不变；SHORT REV==1
check("G6 仅冻结SHORT→LONG REV==16", rev_count(onlyS, "LONG") == 16, f"实得 {rev_count(onlyS,'LONG')}")
check("G6 仅冻结SHORT→SHORT REV==1", rev_count(onlyS, "SHORT") == 1, f"实得 {rev_count(onlyS,'SHORT')}")

print("\n=== 零未来函数强化（LONG-only 冻结 + 默认 SHORT 关）===")
off = run({"REV_REF_FROZEN": True, "PAXG_SHORT_ENABLED": False})
bad_la = P._assert_no_lookahead(mtf, htf, htf4, ltf5, off)
check("L1/L2 零未来函数自检 PASS", bad_la == 0, f"超前处数={bad_la}")
# 默认（CONFIG）应为 LONG-only 冻结：n==45, 无 SHORT
check("L3 默认config=仅LONG冻结 n==45", len(off) == 45, f"实得 {len(off)}")
check("L3 默认config 无SHORT交易", all(t["direction"] == "LONG" for t in off))

print("\n=== 边界/安全 ===")
# B1 rev_buffer 门槛：双冻结+缓冲0.3 的 REV 数 ≤ 无缓冲
dual_buf = run({"REV_REF_FROZEN": True, "PAXG_SHORT_ENABLED": True, "rev_buffer": 0.3})
check("B1 缓冲≤无缓冲REV数", rev_count(dual_buf, "SHORT") + rev_count(dual_buf, "LONG")
      <= rev_count(dual, "SHORT") + rev_count(dual, "LONG"),
      f"buf={rev_count(dual_buf,'SHORT')+rev_count(dual_buf,'LONG')} nobuf={rev_count(dual,'SHORT')+rev_count(dual,'LONG')}")
# B2 config_hash 随决策变化
h0 = P.config_hash()
P.CONFIG["REV_REF_FROZEN"] = False
h1 = P.config_hash()
P.CONFIG["REV_REF_FROZEN"] = True   # 还原
check("B2 决策入CONFIG→config_hash变化", h0 != h1)

print(f"\n=== 测试汇总：PASS={pass_n}  FAIL={fail_n} ===")
sys.exit(1 if fail_n else 0)
