# rs_diag_short_rev.py
# 诊断：SHORT 腿 12 笔 REV（反向 CHoCH）退出是否过激。
# 判据：REV 退出后 30 根 5m 内，若价格跌回 entry 下方(post_min<entry)=退出过早(过激)；
#       若价格续涨(post_min≥entry 且 post_max>exit)=退出正确(真反转)。
# 另跑「仅 SHORT 关反向 CHoCH」对照，量化修复影响。
import rs_backtest_paxg as P
from rs_data import resample_htf

base = P.get_5m(P.CONFIG["SYMBOL"], (2024, 1, 1), (2026, 10, 3), P.CACHE_5M)
ltf5 = base
mtf = resample_htf(base, 15); htf = resample_htf(base, 60); htf4 = resample_htf(base, 240)

# —— 基线（含反向 CHoCH）——
tr, _ = P.run_backtest(mtf, htf, htf4, ltf5, rev_diag=True)
shorts = [t for t in tr if t["direction"] == "SHORT"]
revs = [t for t in shorts if t["exit_reason"] == "REV"]
print(f"SHORT 总数={len(shorts)}  REV={len(revs)}")
print("\n=== 逐笔 SHORT REV 诊断 ===")
over = 0
for t in revs:
    entry = t["entry_price"]; exitp = t["exit_price"]; sl = t["sl_dist"]
    adv = t["adv_max"]; trH = t["rev_tr_H"]; pmx = t["post_max"]; pmn = t["post_min"]
    # 过激判据
    premature = (pmn is not None and pmn < entry)
    # 若不过激退出，被动拿到 entry(BE) 也比 REV 好多少
    verdict = "过激(过早)" if premature else "正确(真反转)"
    if premature:
        over += 1
    print(f"{t['signal_time']}  entry={entry} exit(REV)={exitp}(Δ{exitp-entry:+.2f}) "
          f"sl={sl} tr_H={trH} adv_max={adv}({adv/sl*100:.0f}%SL) "
          f"post30 max={pmx} min={pmn} → {verdict}")

print(f"\n过激(退出后跌回 entry 下) = {over} / {len(revs)}")

# 汇总
def stats(sub):
    n=len(sub)
    if n==0: return "n=0"
    pn=[t["pnl_points"] for t in sub]
    w=[p for p in pn if p>0]; l=[-p for p in pn if p<=0]
    gp=sum(w); gl=sum(l); pf=gp/gl if gl>0 else float('inf')
    return f"n={n} 胜率={len(w)/n*100:.0f}% PF={pf:.2f} 净pnl={sum(pn):.1f} 期望={sum(pn)/n:.2f}"

print("\n=== 对照：仅 SHORT 关反向 CHoCH ===")
tr2, _ = P.run_backtest(mtf, htf, htf4, ltf5, rev_exit_short=False, rev_diag=True)
sh2 = [t for t in tr2 if t["direction"]=="SHORT"]
print("SHORT 关 REV:", stats(sh2))
from collections import Counter
print("  SHORT 退出分布:", dict(Counter(t["exit_reason"] for t in sh2)))
# 全系统对照
all1 = stats(tr); all2 = stats(tr2)
print("全系统(含REV):", all1)
print("全系统(仅SHORT关REV):", all2)
