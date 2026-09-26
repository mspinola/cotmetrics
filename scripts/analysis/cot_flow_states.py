"""COT flow states for gold: week-over-week net change by cohort, a cross-cohort state
classifier, and a descriptive look at forward returns per state.

Reproducer for docs/analysis/2026-09-26-cot-flow-states-gold.md.

Design fixed before any result was seen (no parameter search was run, see the doc):
  z_c      = dNet_c / rolling_std(dNet_c, 52w, min 26w)      per cohort c
  active   = |z_c| > 1.0
  state    = (sign(z_MM), sign(z_Other), sign(z_NonRep)) with 0 when not active
  straddle = dGross_c > 2 * rolling_std(dGross_c) and |dNet_c| < 0.25 * dGross_c
  derisk   = dSpread_MM > 1 * rolling_std and dNet_MM < 0

Reads the disaggregated store directly so it runs without a cotmetrics install. A
production version belongs in cotmetrics (categories.py already owns the cohort specs
and the net/pct-OI/index/z columns; this adds the dNet family and the state).

Usage:
  python scripts/analysis/cot_flow_states.py --store ~/code/cotdata_store \
      --prices ~/code/trading_workspace/cot-analyzer/data_cache/GC.parquet \
      --out docs/analysis
"""
import argparse, os, sys
import numpy as np, pandas as pd

COHORTS = {
    "MM":     ("M_Money_Positions_Long_All",   "M_Money_Positions_Short_All",   "M_Money_Positions_Spread_All"),
    "Other":  ("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All","Other_Rept_Positions_Spread_All"),
    "NonRep": ("NonRept_Positions_Long_All",   "NonRept_Positions_Short_All",   None),
    "Prod":   ("Prod_Merc_Positions_Long_All", "Prod_Merc_Positions_Short_All", None),
    "Swap":   ("Swap_Positions_Long_All",      "Swap__Positions_Short_All",     "Swap__Positions_Spread_All"),
}
SPEC = ["MM","Other","NonRep"]          # the three cohorts that carry an opinion
Z_WIN, Z_MIN, Z_ACT = 52, 26, 1.0       # fixed before results

STATE_NAMES = {
 ( 1, 1, 1):"BROAD_ACCUM",        ( 1, 1,-1):"INST_BUY_RETAIL_SELL",
 ( 1,-1, 1):"TREND+RETAIL_BUY",   ( 1,-1,-1):"MM_ALONE_BUY",
 (-1, 1, 1):"MM_SELL_OTHERS_BUY", (-1, 1,-1):"VALUE_ACCUM",
 (-1,-1, 1):"RETAIL_ALONE_BUY",   (-1,-1,-1):"BROAD_LIQUID",
}

def load(store, prices):
    df = pd.read_parquet(os.path.join(store, "cot_disagg", "GC_088691.parquet"))
    df["date"] = pd.to_datetime(df["As_of_Date_In_Form_YYMMDD"].astype(int).astype(str).str.zfill(6), format="%y%m%d")
    df = df.sort_values("date").set_index("date")
    px = pd.read_parquet(prices)[["Report_Date_as_MM_DD_YYYY","Closing Price"]]
    px.columns = ["date","close"]; px["date"] = pd.to_datetime(px["date"])
    px = px.dropna().set_index("date")["close"].astype(float)
    return df, px

def derive(df):
    out = pd.DataFrame(index=df.index)
    out["OI"] = df["Open_Interest_All"]
    spr = sum(df[s].fillna(0) for _,_,s in COHORTS.values() if s)
    out["OI_less_spread"] = out["OI"] - spr
    for c,(L,S,SP) in COHORTS.items():
        lo, sh = df[L].astype(float), df[S].astype(float)
        out[f"net_{c}"]    = lo - sh
        out[f"dNet_{c}"]   = (lo - sh).diff()
        out[f"dGross_{c}"] = lo.diff().abs() + sh.diff().abs()
        sd = out[f"dNet_{c}"].rolling(Z_WIN, min_periods=Z_MIN).std()
        out[f"z_{c}"] = out[f"dNet_{c}"] / sd
        gsd = out[f"dGross_{c}"].rolling(Z_WIN, min_periods=Z_MIN).std()
        out[f"straddle_{c}"] = (out[f"dGross_{c}"] > 2*gsd) & (out[f"dNet_{c}"].abs() < 0.25*out[f"dGross_{c}"])
        if SP:
            dsp = df[SP].astype(float).diff(); out[f"dSpread_{c}"] = dsp
    out["dNet_Comm"] = out["dNet_Prod"] + out["dNet_Swap"]
    out["z_Comm"] = out["dNet_Comm"] / out["dNet_Comm"].rolling(Z_WIN, min_periods=Z_MIN).std()
    out["derisk_MM"] = (out["dSpread_MM"] > out["dSpread_MM"].rolling(Z_WIN,min_periods=Z_MIN).std()) & (out["dNet_MM"] < 0)
    # identity check: every long has a short, so sum of dNet over all cohorts is ~0
    out["identity"] = sum(out[f"dNet_{c}"] for c in COHORTS)
    sg = lambda z: np.where(z > Z_ACT, 1, np.where(z < -Z_ACT, -1, 0))
    out["s_MM"], out["s_Other"], out["s_NonRep"] = sg(out["z_MM"]), sg(out["z_Other"]), sg(out["z_NonRep"])
    out["n_active"] = (out[["s_MM","s_Other","s_NonRep"]] != 0).sum(axis=1)
    out["state"] = [STATE_NAMES.get((a,b,c), "PARTIAL" if (a,b,c)!=(0,0,0) else "QUIET")
                    for a,b,c in zip(out["s_MM"],out["s_Other"],out["s_NonRep"])]
    return out

def attach_returns(out, px):
    p = px.reindex(out.index, method="nearest", tolerance=pd.Timedelta("3D"))
    out["close"] = p
    lp = np.log(p)
    for h in (4, 13):
        out[f"fwd{h}"] = lp.shift(-h) - lp
    return out

def table(out, h):
    col=f"fwd{h}"; base = out[col].dropna()
    rows=[]
    for st,g in out.groupby("state"):
        r=g[col].dropna()
        if len(r)==0: continue
        rows.append(dict(state=st, n=len(r), mean=r.mean()*100, median=r.median()*100,
                         hit=(r>0).mean()*100, t=(r.mean()/(r.std(ddof=1)/np.sqrt(len(r)))) if len(r)>2 else np.nan))
    t=pd.DataFrame(rows).set_index("state")
    t.loc["ALL"]=dict(n=len(base), mean=base.mean()*100, median=base.median()*100, hit=(base>0).mean()*100, t=np.nan)
    return t.sort_values("n", ascending=False)

def single_cohort_table(out, h):
    col=f"fwd{h}"; rows=[]
    for c in SPEC:
        for s,lab in ((1,"buy"),(-1,"sell")):
            r=out.loc[out[f"s_{c}"]==s, col].dropna()
            rows.append(dict(cohort=c, move=lab, n=len(r), mean=r.mean()*100, hit=(r>0).mean()*100))
    return pd.DataFrame(rows)

def plots(out, outdir):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    BG="#0e1116"; PAN="#12161c"; DIM="#8b97a5"
    last = out.iloc[-52:]
    rows = ["MM","Other","NonRep","Comm"]
    Z = np.vstack([last[f"z_{r}"].values for r in rows])
    fig,ax=plt.subplots(figsize=(15,4.2)); fig.patch.set_facecolor(BG); ax.set_facecolor(PAN)
    im=ax.imshow(Z,aspect="auto",cmap="RdBu",norm=TwoSlopeNorm(vcenter=0,vmin=-3,vmax=3))
    ax.set_yticks(range(len(rows))); ax.set_yticklabels(["Managed Money","Other Reportable","Non-Reportable","Commercials"],color="#d9e0e8",fontsize=10)
    xt=list(range(0,52,4)); ax.set_xticks(xt); ax.set_xticklabels([last.index[i].strftime("%b %d") for i in xt],color=DIM,fontsize=9,rotation=0)
    ax.set_xlabel("report date (Tuesday)",color=DIM)
    for i in range(52):
        st=last["state"].iloc[i]
        if st in ("RETAIL_ALONE_BUY","VALUE_ACCUM"):
            ax.add_patch(plt.Rectangle((i-.5,-.5),1,len(rows),fill=False,ec="#f0c14b",lw=1.8))
    cb=fig.colorbar(im,ax=ax,fraction=.02,pad=.01); cb.set_label("dNet / 52w std",color=DIM); cb.ax.yaxis.set_tick_params(color=DIM); plt.setp(cb.ax.get_yticklabels(),color=DIM)
    ax.set_title("Gold COT: week-over-week net change by cohort, last 52 weeks (gold box = a divergence state)",color="#fff",loc="left",fontsize=12,pad=10)
    plt.tight_layout(); plt.savefig(os.path.join(outdir,"2026-09-26-cot-flow-heatmap-gold.png"),dpi=150,facecolor=BG); plt.close()

    # state strip + price, last 3y
    l3=out.iloc[-156:]
    cmap={"BROAD_ACCUM":"#3fb27f","INST_BUY_RETAIL_SELL":"#7ddcae","VALUE_ACCUM":"#1e8449","MM_SELL_OTHERS_BUY":"#a3c9a8",
          "RETAIL_ALONE_BUY":"#e2584d","MM_ALONE_BUY":"#e0a33e","TREND+RETAIL_BUY":"#f2a099","BROAD_LIQUID":"#c0392b",
          "PARTIAL":"#3a4552","QUIET":"#1f262e"}
    fig,(a1,a2)=plt.subplots(2,1,figsize=(15,6.4),gridspec_kw=dict(height_ratios=[3,1],hspace=.08),sharex=True)
    fig.patch.set_facecolor(BG)
    for a in (a1,a2):
        a.set_facecolor(PAN); [a.spines[s].set_visible(False) for s in ("top","right")]; a.tick_params(colors=DIM,labelsize=9)
    a1.plot(l3.index,l3["close"],color="#d4a72c",lw=1.5)
    for st,col in (("RETAIL_ALONE_BUY","#e2584d"),("VALUE_ACCUM","#3fb27f")):
        m=l3["state"]==st; a1.scatter(l3.index[m],l3["close"][m],s=46,c=col,zorder=5,ec=BG,lw=1.2,label=st.replace("_"," ").title())
    a1.legend(loc="upper left",fontsize=9,facecolor=PAN,edgecolor="#2a323d",labelcolor="#d9e0e8")
    a1.set_ylabel("gold weekly close",color=DIM); a1.grid(color="#20262e",lw=.7)
    for i,(d,st) in enumerate(zip(l3.index,l3["state"])):
        a2.bar(d,1,width=7,color=cmap.get(st,"#3a4552"),align="center")
    a2.set_yticks([]); a2.set_ylabel("state",color=DIM)
    handles=[plt.Rectangle((0,0),1,1,color=c) for c in cmap.values()]
    a2.legend(handles,[k.replace("_"," ").title() for k in cmap],ncol=5,fontsize=7.5,loc="upper center",bbox_to_anchor=(.5,-.35),facecolor=PAN,edgecolor="#2a323d",labelcolor="#d9e0e8")
    a1.set_title("Gold: flow state per week (bottom strip) with the two divergence states marked on price",color="#fff",loc="left",fontsize=12,pad=10)
    plt.savefig(os.path.join(outdir,"2026-09-26-cot-flow-states-gold.png"),dpi=150,facecolor=BG,bbox_inches="tight"); plt.close()

def plot_heatmap_with_price(out, outdir, n=104):
    """Price over the cohort heatmap. The version to read: without price the cells are
    uninterpretable, and with it the top signatures show as coincident, not leading."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    BG="#0e1116"; PAN="#12161c"; DIM="#8b97a5"
    l=out.iloc[-n:]; rows=["MM","Other","NonRep","Comm"]
    labs=["Managed Money","Other Reportable","Non-Reportable","Commercials"]
    Z=np.vstack([l[f"z_{r}"].values for r in rows]); x=np.arange(n)
    fig,(a1,a2)=plt.subplots(2,1,figsize=(16,7.6),gridspec_kw=dict(height_ratios=[1.6,1],hspace=.06),sharex=True)
    fig.patch.set_facecolor(BG); a1.set_facecolor(PAN)
    a1.plot(x,l["close"].values,color="#d4a72c",lw=1.8)
    for s_ in ("top","right"): a1.spines[s_].set_visible(False)
    a1.grid(color="#20262e",lw=.7); a1.tick_params(colors=DIM,labelsize=9); a1.set_ylabel("weekly close",color=DIM)
    im=a2.imshow(Z,aspect="auto",cmap="RdBu",norm=TwoSlopeNorm(vcenter=0,vmin=-3,vmax=3),extent=(-.5,n-.5,len(rows)-.5,-.5))
    a2.set_yticks(range(len(rows))); a2.set_yticklabels(labs,color="#d9e0e8",fontsize=10)
    xt=list(range(0,n,8)); a2.set_xticks(xt); a2.set_xticklabels([l.index[i].strftime("%b %y") for i in xt],color=DIM,fontsize=9)
    cb=fig.colorbar(im,ax=[a1,a2],fraction=.015,pad=.01); cb.set_label("weekly net change / 52w std",color=DIM)
    plt.setp(cb.ax.get_yticklabels(),color=DIM)
    a1.set_title("Gold: price over cohort weekly-flow heatmap. Blue = net buying, red = net selling.",color="#fff",loc="left",fontsize=12,pad=10)
    plt.savefig(os.path.join(outdir,"2026-09-26-cot-flow-heatmap-price-gold.png"),dpi=150,facecolor=BG,bbox_inches="tight"); plt.close()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--store",required=True); ap.add_argument("--prices",required=True); ap.add_argument("--out",required=True)
    a=ap.parse_args()
    df,px=load(a.store,a.prices); out=attach_returns(derive(df),px)
    pd.set_option("display.width",200); pd.set_option("display.float_format",lambda v:f"{v:,.2f}")
    print(f"weeks {len(out)}  {out.index.min().date()} -> {out.index.max().date()}   priced {out['close'].notna().sum()}")
    print(f"identity |sum dNet| max = {out['identity'].abs().max():.0f} contracts (should be ~0)\n")
    print("== state frequency ==");   print(out["state"].value_counts().to_string()); print()
    for h in (4,13):
        print(f"== forward {h}w log return (%) by state =="); print(table(out,h).to_string()); print()
    print("== single-cohort baseline, fwd 13w ==");  print(single_cohort_table(out,13).to_string(index=False)); print()
    print("== flags ==")
    for c in SPEC: print(f"  straddle_{c}: {int(out[f'straddle_{c}'].sum())} weeks")
    print(f"  derisk_MM   : {int(out['derisk_MM'].sum())} weeks")
    print("\n== last 8 weeks =="); print(out[["close","z_MM","z_Other","z_NonRep","z_Comm","state","straddle_NonRep","derisk_MM"]].tail(8).to_string())
    os.makedirs(a.out,exist_ok=True); plots(out,a.out); plot_heatmap_with_price(out,a.out)
    out.to_parquet(os.path.join(a.out,"2026-09-26-cot-flow-states-gold.parquet"))
    print("\nwrote figures + parquet to",a.out)

if __name__=="__main__": main()
