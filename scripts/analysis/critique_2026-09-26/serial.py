import sys, numpy as np, pandas as pd
sys.path.insert(0, '/Users/matts/code/trading_workspace/cotmetrics/scripts/analysis')
import cot_flow_states as G
df, px = G.load('/Users/matts/code/cotdata_store', '/Users/matts/code/trading_workspace/cot-analyzer/data_cache/GC.parquet')
out = G.attach_returns(G.derive(df), px)
print("weeks", len(out))
# serial structure
for c in ["MM","Other","NonRep"]:
    d = out[f"dNet_{c}"].dropna(); z = out[f"z_{c}"].dropna(); lvl = out[f"net_{c}"].dropna()
    print(f"{c:7s} lag1 ac: level={lvl.autocorr(1):.3f}  dNet={d.autocorr(1):.3f}  z={z.autocorr(1):.3f}  |z| lag1={z.abs().autocorr(1):.3f}  P(|z|>1)={(z.abs()>1).mean():.3f}  P(|z|>1 | prev |z|>1)={(z.abs()>1)[ (z.abs()>1).shift(1).fillna(False)].mean():.3f}")
# run lengths of |z|>1 per cohort
def runs(mask):
    m = mask.values.astype(int); r=[]; k=0
    for v in m:
        if v: k+=1
        elif k: r.append(k); k=0
    if k: r.append(k)
    return np.array(r)
for c in ["MM","Other","NonRep"]:
    r = runs(out[f"z_{c}"].abs()>1)
    print(f"{c:7s} |z|>1 episodes={len(r)} weeks={r.sum()} mean run={r.mean():.2f} median={np.median(r):.0f} p90={np.percentile(r,90):.0f} max={r.max()}")
    # same-sign runs
    for s,lab in ((1,"buy"),(-1,"sell")):
        r = runs(out[f"s_{c}"]==s)
        print(f"   {lab}: episodes={len(r)} weeks={r.sum()} mean run={r.mean():.2f} max={r.max()}")
# clustering of VALUE_ACCUM weeks
va = out.index[out["state"]=="VALUE_ACCUM"]
gaps = np.diff(va.values).astype('timedelta64[D]').astype(int)//7
print("VALUE_ACCUM dates:", [d.strftime('%Y-%m-%d') for d in va])
print("gaps (weeks):", gaps.tolist(), " gaps<13:", int((gaps<13).sum()), "of", len(gaps))
# rolling std normaliser: std of dNet/OI across time (nonstationarity)
oi = out["OI"]
for c in ["MM","Comm"]:
    x = out[f"dNet_{c}"]/oi
    print(f"{c} dNet/OI  overall std={x.std():.4f}  rolling52 std range: {x.rolling(52).std().min():.4f}..{x.rolling(52).std().max():.4f}")
    y = out[f"dNet_{c}"]
    print(f"{c} dNet raw  rolling52 std range: {y.rolling(52).std().min():.0f}..{y.rolling(52).std().max():.0f}")
# 13w and 4w forward return distribution & autocorr of overlapping fwd returns
for h in (4,13):
    f = out[f"fwd{h}"].dropna()
    print(f"fwd{h}: n={len(f)} mean={f.mean()*100:.2f}% std={f.std()*100:.2f}% lag1={f.autocorr(1):.3f} lag{h-1}={f.autocorr(h-1):.3f} lag{h}={f.autocorr(h):.3f}")
# weekly return
w = np.log(out["close"]).diff().dropna()
print(f"weekly logret: n={len(w)} mean={w.mean()*100:.3f}% std={w.std()*100:.2f}% lag1={w.autocorr(1):.3f}")
