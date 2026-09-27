"""Consequence-lens checks for the Comm/Prod/Swap recommendation.

1. Reproduce the DISAGG counterparty dNet correlations (mm_comm, mm_prod, mm_swap) per
   market, and classify which sub-cohort absorbs MM flow, so the class split the claim
   asserts (metals+energy = swap, rest = prod) is checked on HG, RB, HO too.
2. Under the gold doc's own thresholded state (|z| > 1 on MM, Other, NonRep), count weeks
   where the three are QUIET but |z_Comm| > 1, i.e. the fourth row carries information the
   state discards. Per market and pooled.
3. Mechanical share: by the identity Comm = -(MM + Other + NonRep), so corr(MM, Comm) is
   partly construction. Report corr(MM, -(Other + NonRep)) beside it.
"""
import warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")
from cotdata import get_cot
from cotmetrics import categories as cat

pd.set_option("display.width", 250)
DIS = "GF HE LE CT CC KC LBR OJ SB HG GC PA PL SI CL NG RB HO ZC ZS ZM ZL ZW".split()
CLASS = {**{s: "livestock" for s in "GF HE LE".split()}, **{s: "softs" for s in "CT CC KC LBR OJ SB".split()},
         **{s: "metals" for s in "HG GC PA PL SI".split()}, **{s: "energy" for s in "CL NG RB HO".split()},
         **{s: "grains" for s in "ZC ZS ZM ZL ZW".split()}}
W, MP, ACT = 52, 26, 1.0

def nets(df):
    out = {}
    for s in cat.categories_for("disagg"):
        lo = cat._numeric(cat._resolve(df, s.long_col)).astype(float)
        sh = cat._numeric(cat._resolve(df, s.short_col)).astype(float)
        out[s.key] = lo - sh
    return out

def z(x):
    return x / x.rolling(W, min_periods=MP).std()

recs = []; quiet_rows = []
for sym in DIS:
    df = get_cot(sym, report="disagg")
    n = nets(df); dn = {k: v.diff() for k, v in n.items()}
    dn["comm"] = dn["producer_merchant"] + dn["swap"]
    dn["opinion_rest"] = -(dn["other_reportable"] + dn["nonreportable"])
    c = lambda a, b: float(dn[a].corr(dn[b]))
    mm_prod, mm_swap = c("managed_money", "producer_merchant"), c("managed_money", "swap")
    absorber = "swap" if mm_swap < mm_prod else "prod"
    recs.append(dict(sym=sym, cls=CLASS[sym], mm_comm=c("managed_money", "comm"), mm_prod=mm_prod, mm_swap=mm_swap,
                     absorber=absorber, mm_vs_negOtherNonrep=c("managed_money", "opinion_rest"),
                     var_share_mm=float(dn["managed_money"].var() / sum(dn[k].var() for k in ("managed_money", "other_reportable", "nonreportable")))))
    zm, zo, zn = z(dn["managed_money"]), z(dn["other_reportable"]), z(dn["nonreportable"])
    zc = z(dn["comm"])
    sg = lambda s: np.where(s > ACT, 1, np.where(s < -ACT, -1, 0))
    nact = (sg(zm) != 0).astype(int) + (sg(zo) != 0).astype(int) + (sg(zn) != 0).astype(int)
    valid = zc.notna() & zm.notna() & zo.notna() & zn.notna()
    quiet = valid & (nact == 0)
    quiet_rows.append(dict(sym=sym, weeks=int(valid.sum()), quiet=int(quiet.sum()),
                           quiet_but_comm_active=int((quiet & (zc.abs() > ACT)).sum()),
                           any_state_comm_active=int((valid & (zc.abs() > ACT)).sum()),
                           # sign disagreement: all three opinion cohorts inactive but Comm active either way
                           ))

t = pd.DataFrame(recs)
print("=== DISAGG counterparty correlations of dNet (reproduced) ===")
print(t.round(2).to_string(index=False))
print("\nmedian:\n", t.median(numeric_only=True).round(2).to_string())
print("\nabsorber by class:\n", t.groupby(["cls", "absorber"]).size().to_string())
print("\nswap-absorbed markets:", t.loc[t.absorber == "swap", "sym"].tolist())
print("prod-absorbed markets:", t.loc[t.absorber == "prod", "sym"].tolist())
print("median mm_prod on prod-absorbed:", round(float(t.loc[t.absorber == "prod", "mm_prod"].median()), 2),
      " median mm_swap on prod-absorbed:", round(float(t.loc[t.absorber == "prod", "mm_swap"].median()), 2))

q = pd.DataFrame(quiet_rows)
print("\n=== Under the doc's thresholded state: QUIET weeks where |z_Comm| > 1 ===")
print(q.to_string(index=False))
print("pooled: quiet=%d  quiet_but_comm_active=%d (%.1f%% of quiet)  weeks=%d" % (
    q.quiet.sum(), q.quiet_but_comm_active.sum(), 100 * q.quiet_but_comm_active.sum() / q.quiet.sum(), q.weeks.sum()))
gc = q[q.sym == "GC"].iloc[0]
print("GC: quiet=%d quiet_but_comm_active=%d" % (gc.quiet, gc.quiet_but_comm_active))
