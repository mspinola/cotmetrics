import pandas as pd, numpy as np, glob, os, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.gridspec import GridSpec
S="/sessions/inspiring-magical-curie/mnt/cotdata_store"
u=pd.read_parquet("/sessions/inspiring-magical-curie/mnt/trading_workspace/cotmetrics/docs/analysis/2026-09-26-cot-flow-states-universe.parquet")
px=u.dropna(subset=["close"]).set_index(["symbol","date"])["close"]
D={"MM":("M_Money_Positions_Long_All","M_Money_Positions_Short_All"),"Other":("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All"),"NonRep":("NonRept_Positions_Long_All","NonRept_Positions_Short_All"),"Prod":("Prod_Merc_Positions_Long_All","Prod_Merc_Positions_Short_All"),"Swap":("Swap_Positions_Long_All","Swap__Positions_Short_All")}
T={"Dealer":("Dealer_Positions_Long_All","Dealer_Positions_Short_All"),"AssetMgr":("Asset_Mgr_Positions_Long_All","Asset_Mgr_Positions_Short_All"),"LevFund":("Lev_Money_Positions_Long_All","Lev_Money_Positions_Short_All"),"Other":("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All"),"NonRep":("NonRept_Positions_Long_All","NonRept_Positions_Short_All")}
R=pd.read_csv("/tmp/cohort_collapse.csv").set_index("sym")
def load(f):
    d=pd.read_parquet(f)
    if "As_of_Date_In_Form_YYMMDD" in d: d.index=pd.to_datetime(d["As_of_Date_In_Form_YYMMDD"].astype(int).astype(str).str.zfill(6),format="%y%m%d")
    else: d.index=pd.to_datetime(d.index)
    return d[~d.index.duplicated()].sort_index()
def ridx(s,w=156): lo=s.rolling(w,min_periods=52).min(); hi=s.rolling(w,min_periods=52).max(); return 100*(s-lo)/(hi-lo)
BG="#0e1116"; PAN="#12161c"; DIM="#8b97a5"; TXT="#d9e0e8"
syms=["GC","ZC","6E","ES"]; n=104
fig=plt.figure(figsize=(16,4.2*len(syms)),facecolor=BG); gs=GridSpec(3*len(syms),1,height_ratios=[1.3,0.8,0.3]*len(syms),hspace=0.12)
for k,sym in enumerate(syms):
    r=R.loc[sym]; rep=r.report; C=D if rep=="disagg" else T
    f=[x for x in glob.glob(f"{S}/cot_{rep}/{sym}_*.parquet") if not (sym=="RTY" and "23977A" in x)][0]; d=load(f)
    net={c:(d[l]-d[s]) for c,(l,s) in C.items()}; oi=d.Open_Interest_All
    spec=sum(net[c] for c in r.SPEC.split("+")); ret=net["NonRep"]
    spec_idx=ridx(spec); ret_idx=ridx(ret)
    dz=spec.diff(); z=dz/dz.rolling(52,min_periods=26).std()
    p=px.loc[sym].reindex(d.index)
    l=d.index[-n:]; x=np.arange(n)
    a1=fig.add_subplot(gs[3*k]); a2=fig.add_subplot(gs[3*k+1],sharex=a1); a3=fig.add_subplot(gs[3*k+2],sharex=a1)
    for a in (a1,a2,a3):
        a.set_facecolor(PAN); a.tick_params(colors=DIM,labelsize=8); a.set_xlim(-.5,n-.5)
        for s_ in ("top","right"): a.spines[s_].set_visible(False)
    a1.plot(x,p.loc[l].values,color="#d4a72c",lw=1.6); a1.grid(color="#20262e",lw=.7)
    a1.set_title(f"{sym} ({rep}): speculator = {r.SPEC}, counterparty = {r.COUNTERPARTY}, neutral = {r.NEUTRAL}",color="#fff",loc="left",fontsize=11)
    ax2=a1.twinx(); ax2.plot(x,oi.loc[l].values/1000,color=DIM,lw=.8,ls=":"); ax2.tick_params(colors=DIM,labelsize=7); ax2.spines["top"].set_visible(False)
    a2.plot(x,spec_idx.loc[l].values,color="#3b9ddd",lw=1.8,label=f"speculator net, 3yr index ({r.SPEC})")
    a2.plot(x,ret_idx.loc[l].values,color="#f2c14e",lw=1,alpha=.7,label=f"retail net, 3yr index (behaves {r.retail_behaves})")
    a2.axhspan(80,100,color="#3b9ddd",alpha=.08); a2.axhspan(0,20,color="#e4572e",alpha=.08); a2.set_ylim(0,100); a2.set_yticks([0,20,50,80,100]); a2.grid(color="#20262e",lw=.7)
    a2.legend(loc="upper left",fontsize=7.5,frameon=False,labelcolor=TXT,ncol=2)
    a3.imshow(z.loc[l].values[None,:],aspect="auto",cmap="RdBu",norm=TwoSlopeNorm(vcenter=0,vmin=-3,vmax=3),extent=(-.5,n-.5,.5,-.5))
    a3.set_yticks([0]); a3.set_yticklabels(["spec flow z"],color=TXT,fontsize=8)
    for a in (a1,a2): plt.setp(a.get_xticklabels(),visible=False)
    xt=list(range(0,n,8)); a3.set_xticks(xt); a3.set_xticklabels([l[i].strftime("%b %y") for i in xt],color=DIM,fontsize=8)
fig.suptitle("One role series per market: the speculator net (level as 3yr index, flow as one z strip). Counterparty is its mirror by identity; neutral cohorts omitted.",color="#fff",x=0.01,ha="left",fontsize=12,y=0.995)
for q in ("/sessions/inspiring-magical-curie/mnt/outputs/","/sessions/inspiring-magical-curie/mnt/gold/"): plt.savefig(q+"2026-09-26-cot-one-role-view.png",dpi=120,facecolor=BG,bbox_inches="tight")
print("ok")
