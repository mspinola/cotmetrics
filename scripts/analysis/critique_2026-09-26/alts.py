import sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, '/Users/matts/code/trading_workspace/cotmetrics/scripts/analysis')
import cot_flow_states as G
from crucible.edge.stats import block_bootstrap_pvalue, block_bootstrap_ci
df, px = G.load('/Users/matts/code/cotdata_store', '/Users/matts/code/trading_workspace/cot-analyzer/data_cache/GC.parquet')
out = G.attach_returns(G.derive(df), px)
f13 = out["fwd13"]; f4 = out["fwd4"]
def hac_t(x, lag):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n=len(x); m=x.mean(); e=x-m
    s = np.sum(e*e)/n
    for k in range(1, lag+1):
        w = 1 - k/(lag+1); s += 2*w*np.sum(e[k:]*e[:-k])/n
    return m/np.sqrt(s/n), n
print("== Correct statistics on the doc's headline rows (fwd13, Tuesday-anchored as in the doc) ==")
for st in ("PARTIAL","QUIET","VALUE_ACCUM"):
    m = out["state"]==st
    r = f13[m].dropna()
    naive = r.mean()/(r.std(ddof=1)/np.sqrt(len(r)))
    # HAC over the calendar-ordered subset: use full grid series with zeros where inactive (indicator regression)
    # Approach A: HAC on the subset series in calendar order (Newey-West lag 12 over subset positions is wrong when gaps>13),
    # so build the full-grid product: y_t = f13_t * 1[state_t] ; mean of y over active weeks = conditional mean. HAC on the grid.
    ind = m.astype(float); y = (f13.fillna(0)*ind)
    grid = pd.DataFrame({"y":y, "i":ind}).dropna()
    # difference-from-unconditional: demeaned indicator regression coefficient ~ (mean|state - mean|all)
    d = f13 - f13.mean()
    yy = (d.fillna(0)*ind).values; ii = ind.values
    # coefficient = sum(yy)/sum(ii); its HAC se via the score series u_t = ii*(d_t) 
    u = yy - 0*ii
    n = len(u); beta = u.sum()/ii.sum()
    e = ii*(d.fillna(0).values - beta)
    lag=12; s=np.sum(e*e)
    for k in range(1,lag+1):
        w=1-k/(lag+1); s+=2*w*np.sum(e[k:]*e[:-k])
    se = np.sqrt(s)/ii.sum()
    t_diff = beta/se
    # non-overlapping thinning: keep active weeks separated by >=13
    dates = out.index[m & f13.notna()]; keep=[]; last=None
    for dt in dates:
        if last is None or (dt-last).days>=13*7: keep.append(dt); last=dt
    r_no = f13.loc[keep]
    t_no = r_no.mean()/(r_no.std(ddof=1)/np.sqrt(len(r_no)))
    # block bootstrap p on the calendar-grid excess series (crucible.edge.stats), block=13 weeks
    grid_excess = (d.fillna(0)*ind).values
    # test H0: conditional excess mean = 0, using the grid series of ind*(f - mean) scaled by 1/p(state)
    series = grid_excess/ii.mean()
    p_blk = block_bootstrap_pvalue(series, block=13, n_boot=5000, seed=0)
    ci = block_bootstrap_ci(series, block=13, n_boot=5000, seed=0)
    print(f"{st:12s} n={len(r):4d} mean={r.mean()*100:.2f}% naive_t(vs0)={naive:.2f}  excess-vs-uncond={beta*100:+.2f}% HAC(NW lag12) t={t_diff:+.2f}  non-overlap thinned n={len(r_no)} t(vs0)={t_no:.2f}  block(13w) bootstrap p(excess>0)={p_blk:.3f} CI[{ci.low*100:+.2f},{ci.high*100:+.2f}]%")
print("\n== Alternatives to the 8-state table, fwd13, descriptive only (each is a NEW VARIANT if pursued) ==")
# continuous divergence composite: z_MM - z_Comm (spec vs structural), and z_Other - z_MM (value vs trend)
z = out[["z_MM","z_Other","z_NonRep","z_Comm"]]
comp = {"z_MM - z_Comm": z.z_MM - z.z_Comm, "z_Other - z_MM": z.z_Other - z.z_MM, "z_Other - (z_MM+z_NonRep)/2": z.z_Other - (z.z_MM+z.z_NonRep)/2}
for k,v in comp.items():
    c13 = v.corr(f13, method="spearman"); c4 = v.corr(f4, method="spearman")
    print(f"{k:32s} spearman with fwd13={c13:+.3f} fwd4={c4:+.3f}  sd={v.std():.2f}  lag1 ac={v.autocorr(1):+.3f}")
# 2- and 3-week accumulation of z
for w in (2,3):
    acc = z.rolling(w).sum()
    s = pd.DataFrame({c: np.where(acc[c]>1*np.sqrt(w),1,np.where(acc[c]<-1*np.sqrt(w),-1,0)) for c in ["z_MM","z_Other","z_NonRep"]}, index=out.index)
    n_full = (s!=0).all(axis=1).sum()
    va = ((s.z_MM==-1)&(s.z_Other==1)&(s.z_NonRep==-1))
    r = f13[va].dropna()
    print(f"{w}-week sum of z, threshold sqrt({w}): all-three-active weeks={n_full}  VALUE_ACCUM-analogue n={len(r)} mean={r.mean()*100:.2f}% hit={(r>0).mean()*100:.0f}%")
# two-cohort states MM x NonRep
tc = out.groupby(["s_MM","s_NonRep"])["fwd13"].agg(["count","mean"]); tc["mean"]*=100
print("\nMM x NonRep two-cohort table (fwd13 %):"); print(tc.round(2).to_string())
# ordinal: n_active and net sign
out["net_sign"] = out[["s_MM","s_Other","s_NonRep"]].sum(axis=1)
o = out.groupby(["n_active","net_sign"])["fwd13"].agg(["count","mean"]); o["mean"]*=100
print("\nordinal n_active x net_sign (fwd13 %):"); print(o.round(2).to_string())
