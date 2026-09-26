import numpy as np
rng = np.random.default_rng(0)
N = 1059; sims = 4000
print("Null: iid weekly returns, overlapping h-week forward sums, naive t = mean/(sd/sqrt(n))")
for h in (4, 13):
    ts=[]; ts_sub=[]; ts_nonov=[]
    for _ in range(sims):
        w = rng.standard_normal(N)
        c = np.cumsum(w); f = c[h:] - c[:-h]          # overlapping h-week forward sums
        ts.append(f.mean()/(f.std(ddof=1)/np.sqrt(len(f))))
        # a random 'state' subset of ~21 isolated weeks (spaced >= h apart) vs clustered (3 runs of 7)
        idx = rng.choice(len(f), 21, replace=False)
        ts_sub.append(f[idx].mean()/(f[idx].std(ddof=1)/np.sqrt(21)))
        nov = f[::h]
        ts_nonov.append(nov.mean()/(nov.std(ddof=1)/np.sqrt(len(nov))))
    ts=np.array(ts); ts_sub=np.array(ts_sub); ts_nonov=np.array(ts_nonov)
    print(f"h={h:2d}: full-sample naive t sd={ts.std():.2f} (theory sqrt(h)={np.sqrt(h):.2f}; exact (2h^2+1)/(3h)->sd={np.sqrt((2*h*h+1)/(3*h)):.2f}); P(|t|>1.96)={np.mean(np.abs(ts)>1.96):.3f}")
    print(f"       random 21-week subset t sd={ts_sub.std():.2f}; non-overlapping subsample t sd={ts_nonov.std():.2f}")
# clustered subset: 3 runs of 7 consecutive weeks
for h in (4,13):
    ts=[]
    for _ in range(sims):
        w = rng.standard_normal(N); c=np.cumsum(w); f=c[h:]-c[:-h]
        starts = rng.choice(len(f)-7, 3, replace=False)
        idx = np.concatenate([np.arange(s,s+7) for s in starts])
        ts.append(f[idx].mean()/(f[idx].std(ddof=1)/np.sqrt(len(idx))))
    print(f"h={h:2d}: clustered subset (3 runs x 7 weeks, n=21) naive t sd={np.std(ts):.2f}")
# What PARTIAL's t=5.59 (n=541 of 1045) becomes: it is ~half the sample, so like full sample
print("\nDoc's PARTIAL t=5.59 at h=13 deflated by sqrt(13)=3.61 ->", round(5.59/np.sqrt(13),2), "; by exact factor", round(5.59/np.sqrt((2*169+1)/39),2))
print("Doc's QUIET t=4.15 deflated ->", round(4.15/np.sqrt(13),2))
