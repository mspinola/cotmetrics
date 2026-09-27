"""Do state weeks cluster into runs across the universe? weeks vs episodes per named state,
run-length stats, and share of within-market gaps shorter than the 13w horizon."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from cotdata import get_cot
from cotmetrics import categories as cat
DISAGG = "GF HE LE CT CC KC LBR OJ SB HG GC PA PL SI CL NG RB HO ZC ZS ZM ZL ZW".split()
TFF = "ZB ZN ZF ZT YM NQ RTY ES BTC ETH 6A 6B 6C 6S 6E 6J 6M 6N DX".split()
TRIPLE = {"disagg": ["managed_money", "other_reportable", "nonreportable"],
          "tff": ["leveraged", "asset_manager", "nonreportable"]}
NAMES = {(1,1,1):"BROAD_ACCUM",(1,1,-1):"INST_BUY_RETAIL_SELL",(1,-1,1):"TREND+RETAIL_BUY",(1,-1,-1):"MM_ALONE_BUY",
         (-1,1,1):"MM_SELL_OTHERS_BUY",(-1,1,-1):"VALUE_ACCUM",(-1,-1,1):"RETAIL_ALONE_BUY",(-1,-1,-1):"BROAD_LIQUID"}
W, MP, H = 52, 26, 13
def runs(mask):
    m = mask.values.astype(int); r=[]; k=0
    for v in m:
        if v: k+=1
        elif k: r.append(k); k=0
    if k: r.append(k)
    return np.array(r, dtype=int)
recs = []; sc = []
for report, syms in (("disagg", DISAGG), ("tff", TFF)):
    for sym in syms:
        df = get_cot(sym, report=report)
        if df.empty: continue
        specs = {s.key: s for s in cat.categories_for(report)}
        z = {}
        for k in TRIPLE[report]:
            s = specs[k]
            lo = cat._numeric(cat._resolve(df, s.long_col)).astype(float); sh = cat._numeric(cat._resolve(df, s.short_col)).astype(float)
            d = (lo - sh).diff(); z[k] = d / d.rolling(W, min_periods=MP).std()
        sg = lambda v: np.where(v > 1, 1, np.where(v < -1, -1, 0))
        a, b, c = (sg(z[k]) for k in TRIPLE[report])
        state = pd.Series([NAMES.get((x,y,w), "PARTIAL" if (x,y,w)!=(0,0,0) else "QUIET") for x,y,w in zip(a,b,c)], index=df.index)
        for k, arr in zip(TRIPLE[report], (a,b,c)):
            for sgn, lab in ((1,"buy"),(-1,"sell")):
                r = runs(pd.Series(arr==sgn, index=df.index))
                sc.append(dict(report=report, sym=sym, cohort=k, move=lab, weeks=int(r.sum()), episodes=len(r), maxrun=int(r.max()) if len(r) else 0))
        for st in list(NAMES.values()):
            m = state == st
            r = runs(m)
            dates = state.index[m.values]
            gaps = (np.diff(pd.DatetimeIndex(dates).values).astype("timedelta64[D]").astype(int)//7) if len(dates) > 1 else np.array([])
            recs.append(dict(report=report, sym=sym, state=st, weeks=int(m.sum()), episodes=len(r), maxrun=int(r.max()) if len(r) else 0,
                             runs_ge2=int((r>=2).sum()), gaps_lt_h=int((gaps<H).sum()), gaps_eq_1=int((gaps==1).sum()), n_gaps=len(gaps)))
t = pd.DataFrame(recs)
pd.set_option("display.width", 220)
print("== named states, pooled over 42 markets: weeks vs episodes (first week of a run) ==")
g = t.groupby("state")[["weeks","episodes","runs_ge2","gaps_lt_h","gaps_eq_1","n_gaps"]].sum()
g["weeks/episodes"] = (g["weeks"]/g["episodes"]).round(3); g["maxrun"] = t.groupby("state")["maxrun"].max()
print(g.sort_values("weeks", ascending=False).to_string())
print("\n== same, split by report ==")
g2 = t.groupby(["report","state"])[["weeks","episodes","runs_ge2","gaps_lt_h","n_gaps"]].sum(); g2["weeks/episodes"]=(g2["weeks"]/g2["episodes"]).round(3)
print(g2.to_string())
print("\n== single-cohort same-sign runs, pooled: weeks vs episodes ==")
s = pd.DataFrame(sc); gs = s.groupby(["report","cohort","move"])[["weeks","episodes"]].sum(); gs["weeks/episodes"]=(gs["weeks"]/gs["episodes"]).round(3); gs["maxrun"]=s.groupby(["report","cohort","move"])["maxrun"].max()
print(gs.to_string())
print("\n== GC VALUE_ACCUM ==")
print(t[(t.sym=="GC")&(t.state=="VALUE_ACCUM")].to_string(index=False))
