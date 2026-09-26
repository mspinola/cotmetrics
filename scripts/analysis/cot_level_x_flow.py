import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.gridspec import GridSpec
S="/sessions/inspiring-magical-curie/mnt/cotdata_store"; O="/sessions/inspiring-magical-curie/mnt/outputs/"; G="/sessions/inspiring-magical-curie/mnt/gold/"
out=pd.read_parquet("/tmp/cfo/2026-09-26-cot-flow-states-gold.parquet")
LB=156
def ridx(s,w=LB): lo=s.rolling(w,min_periods=52).min(); hi=s.rolling(w,min_periods=52).max(); return 100*(s-lo)/(hi-lo)
out["net_Comm"]=out.net_Prod+out.net_Swap
rows=["MM","Other","NonRep","Comm"]; labs=["Managed Money","Other Rept","Non-Rept","Commercials"]
for r in rows: out[f"lvl_{r}"]=ridx(out[f"net_{r}"])
BG="#0e1116"; PAN="#12161c"; DIM="#8b97a5"; TXT="#d9e0e8"
# ---------- figure A: three-panel layout ----------
n=104; l=out.iloc[-n:]; idx=l.index; x=np.arange(n)
Z=np.vstack([l[f"z_{r}"].values for r in rows]); L=np.vstack([l[f"lvl_{r}"].values for r in rows])
fig=plt.figure(figsize=(16,10.5),facecolor=BG); gs=GridSpec(3,1,height_ratios=[1.5,1.0,1.0],hspace=0.07)
ax=[fig.add_subplot(gs[i]) for i in range(3)]
for a in ax:
    a.set_facecolor(PAN); a.tick_params(colors=DIM,labelsize=9); a.set_xlim(-.5,n-.5)
    for s in ("top","right"): a.spines[s].set_visible(False)
a=ax[0]; a.plot(x,l["close"].values,color="#d4a72c",lw=1.8); a.grid(color="#20262e",lw=.7); a.set_ylabel("GC weekly close",color=DIM)
a2=a.twinx(); a2.plot(x,l["OI"].values/1000,color=DIM,lw=.9,ls=":"); a2.set_ylabel("OI (k)",color=DIM); a2.tick_params(colors=DIM,labelsize=8); a2.spines["top"].set_visible(False)
marks={"2025-10-21":"Oct top","2026-01-27":"Jan 28 top","2026-06-30":"Jun 30 ICL","2026-08-26":"Aug 25 DCH"}
for d,t in marks.items():
    i=idx.get_indexer([pd.Timestamp(d)],method="nearest")[0]
    for a_ in ax: a_.axvline(i,color="#fff",alpha=.25,ls="--",lw=.9)
    ax[0].text(i,ax[0].get_ylim()[1],t,color=TXT,fontsize=8,ha="center",va="bottom")
a=ax[1]; im=a.imshow(Z,aspect="auto",cmap="RdBu",norm=TwoSlopeNorm(vcenter=0,vmin=-3,vmax=3),extent=(-.5,n-.5,3.5,-.5))
a.set_yticks(range(4)); a.set_yticklabels(labs,color=TXT,fontsize=9); a.set_ylabel("FLOW: weekly net change / 52w std",color=DIM,fontsize=9)
for r_i in range(4):
    li=L[r_i]; a.scatter(x[li<=10],[r_i]*int((li<=10).sum()),marker="v",s=16,color="#111",zorder=3); a.scatter(x[li>=90],[r_i]*int((li>=90).sum()),marker="^",s=16,color="#111",zorder=3)
a.text(0,1.02,"▼ bottom decile of 3yr range   ▲ top decile   (level the flow departs from)",transform=a.transAxes,color=DIM,fontsize=8,va="bottom")
cb=fig.colorbar(im,ax=a,fraction=.02,pad=.01); cb.ax.tick_params(colors=DIM,labelsize=7)
a=ax[2]; C={"MM":"#3b9ddd","Other":"#9b7fd4","NonRep":"#f2c14e","Comm":"#e4572e"}
for r,lab in zip(rows,labs): a.plot(x,L[rows.index(r)],color=C[r],lw=1.6,label=lab)
a.axhspan(80,100,color="#3b9ddd",alpha=.08); a.axhspan(0,20,color="#e4572e",alpha=.08); a.set_ylim(0,100); a.set_yticks([0,20,50,80,100]); a.grid(color="#20262e",lw=.7)
a.set_ylabel("LEVEL: positioning index (3yr range)",color=DIM,fontsize=9); a.legend(loc="upper left",fontsize=8,frameon=False,labelcolor=TXT,ncol=4)
xt=list(range(0,n,8)); a.set_xticks(xt); a.set_xticklabels([idx[i].strftime("%b %y") for i in xt],color=DIM,fontsize=9)
for a_ in ax[:-1]: a_.set_xticks([])
ax[0].set_title("GC: proposed cot-analyzer view. Price + OI, flow heatmap with level markers, positioning index.",color="#fff",loc="left",fontsize=12,pad=22)
fig.text(0.01,0.005,"Flow: disaggregated, 52w rolling std of weekly net change. Level: range index over 156 weeks (min 52); cot-analyzer would use CotIndexer's tuned per-symbol lookback. Source cotdata_store, newest week 2026-09-22.",color=DIM,fontsize=8)
for p in (O,G): plt.savefig(p+"2026-09-26-cot-view-proposed-gold.png",dpi=130,facecolor=BG,bbox_inches="tight")
plt.close()
# ---------- figure B: level x flow scatter, coloured by fwd13 ----------
d=out.dropna(subset=["fwd13"]+[f"lvl_{r}" for r in rows]+[f"z_{r}" for r in rows])
fig,axs=plt.subplots(2,2,figsize=(14,11),facecolor=BG); axs=axs.ravel()
stats=[]
for a,r,lab in zip(axs,rows,labs):
    a.set_facecolor(PAN); a.tick_params(colors=DIM,labelsize=9)
    for s in ("top","right"): a.spines[s].set_visible(False)
    sc=a.scatter(d[f"lvl_{r}"],d[f"z_{r}"],c=100*d["fwd13"],cmap="RdYlGn",vmin=-12,vmax=12,s=14,alpha=.85,edgecolors="none")
    a.axhline(0,color=DIM,lw=.6); a.axvline(20,color=DIM,lw=.6,ls=":"); a.axvline(80,color=DIM,lw=.6,ls=":")
    a.set_xlim(0,100); a.set_ylim(-4,4); a.set_title(lab,color="#fff",loc="left",fontsize=11); a.grid(color="#20262e",lw=.7)
    # quadrant means: buying (z>1) from low level (<20) vs buying from mid (20-80) vs buying from high (>80); same for selling
    for name,m in [("buy<20",(d[f"z_{r}"]>1)&(d[f"lvl_{r}"]<20)),("buy 20-80",(d[f"z_{r}"]>1)&(d[f"lvl_{r}"].between(20,80))),("buy>80",(d[f"z_{r}"]>1)&(d[f"lvl_{r}"]>80)),
                   ("sell<20",(d[f"z_{r}"]<-1)&(d[f"lvl_{r}"]<20)),("sell 20-80",(d[f"z_{r}"]<-1)&(d[f"lvl_{r}"].between(20,80))),("sell>80",(d[f"z_{r}"]<-1)&(d[f"lvl_{r}"]>80))]:
        f=d.loc[m,"fwd13"]; stats.append((r,name,int(m.sum()),100*f.mean() if len(f) else np.nan,100*(f>0).mean() if len(f) else np.nan))
    txt="\n".join(f"{s[1]:>10s} n={s[2]:3d} {s[3]:+5.1f}% hit {s[4]:3.0f}%" for s in stats[-6:])
    a.text(0.99,0.02,txt,transform=a.transAxes,color=TXT,fontsize=7.5,family="monospace",ha="right",va="bottom",bbox=dict(facecolor=BG,alpha=.8,edgecolor="none"))
axs[2].set_xlabel("LEVEL: net position, 3yr range index",color=DIM); axs[3].set_xlabel("LEVEL: net position, 3yr range index",color=DIM)
axs[0].set_ylabel("FLOW: weekly net change / 52w std",color=DIM); axs[2].set_ylabel("FLOW: weekly net change / 52w std",color=DIM)
cb=fig.colorbar(sc,ax=axs,fraction=.02,pad=.01); cb.set_label("forward 13-week log return, %",color=DIM); plt.setp(cb.ax.get_yticklabels(),color=DIM)
fig.suptitle(f"GC 2007-2026: does the sign of a flow depend on the level it departs from?  ({len(d)} weeks, unconditional fwd13 {100*d.fwd13.mean():+.2f}%, hit {100*(d.fwd13>0).mean():.0f}%)",color="#fff",x=0.01,ha="left",fontsize=12)
for p in (O,G): plt.savefig(p+"2026-09-26-cot-level-x-flow-gold.png",dpi=130,facecolor=BG,bbox_inches="tight")
print(pd.DataFrame(stats,columns=["cohort","cell","n","fwd13_mean","hit"]).to_string(index=False))
