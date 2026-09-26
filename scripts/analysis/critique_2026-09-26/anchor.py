import sys, numpy as np, pandas as pd
sys.path.insert(0, '/Users/matts/code/trading_workspace/cotmetrics/scripts/analysis')
import cot_flow_states as G
from marketdata import get_bars
df, px = G.load('/Users/matts/code/cotdata_store', '/Users/matts/code/trading_workspace/cot-analyzer/data_cache/GC.parquet')
out = G.attach_returns(G.derive(df), px)
b = get_bars("GC", "backadj", source="norgate")
print("GC backadj bars:", b.index.min().date(), "->", b.index.max().date(), len(b), "cols", list(b.columns)[:8])
close = b["Close"].astype(float)
# check the cache close vs Norgate close on report dates
tue = out.index
cc = close.reindex(tue, method="ffill")
print("cache close vs norgate backadj close on Tuesdays: corr of weekly logret =", np.corrcoef(np.log(out['close']).diff().dropna(), np.log(cc).diff().reindex(np.log(out['close']).diff().dropna().index))[0,1].round(4))
# Friday release close: first close on or after report date + 3 days
fri = tue + pd.Timedelta(days=3)
cf = close.reindex(fri, method="ffill")
lt, lf = np.log(cc.values), np.log(cf.values)
r_tf = lf - lt   # Tue->Fri (the untradable 3 sessions)
print(f"Tue->Fri logret: mean={np.nanmean(r_tf)*100:.3f}% sd={np.nanstd(r_tf)*100:.2f}%")
res = {}
for h in (4,13):
    f_tue = pd.Series(lt, index=tue); f_fri = pd.Series(lf, index=tue)
    ft = (f_tue.shift(-h) - f_tue); ff = (f_fri.shift(-h) - f_fri)
    print(f"h={h}: Tue-anchored sd={ft.std()*100:.2f}%  Fri-anchored sd={ff.std()*100:.2f}%  share of Tue-anchored variance from Tue->Fri leg ~ {np.nanvar(r_tf)/ft.var():.3f}; mean Tue-anch={ft.mean()*100:.2f}% Fri-anch={ff.mean()*100:.2f}%")
    for st in ("VALUE_ACCUM","PARTIAL","QUIET"):
        m = out["state"]==st
        t1, t2 = ft[m].dropna(), ff[m].dropna()
        tf_st = pd.Series(r_tf, index=tue)[m]
        print(f"   {st:12s} n={len(t1)} Tue-anch mean={t1.mean()*100:.2f}% Fri-anch mean={t2.mean()*100:.2f}%  Tue->Fri leg mean={tf_st.mean()*100:.2f}% (sd {tf_st.std()*100:.2f}%)")
    # single cohort
    for c in ("MM","Other","NonRep"):
        for s,lab in ((1,"buy"),(-1,"sell")):
            m = out[f"s_{c}"]==s
            tf_st = pd.Series(r_tf, index=tue)[m]
            print(f"   {c} {lab}: Tue->Fri leg mean={tf_st.mean()*100:.2f}% n={m.sum()}")
# does the Tuesday-week's own flow correlate with the concurrent price move (coincident, not leading)?
wk = np.log(out["close"]).diff()
for c in ("MM","Other","NonRep","Comm"):
    print(f"corr(z_{c}, same-week return)={out[f'z_{c}'].corr(wk):.3f}  corr(z_{c}, next-week return)={out[f'z_{c}'].corr(wk.shift(-1)):.3f}")
