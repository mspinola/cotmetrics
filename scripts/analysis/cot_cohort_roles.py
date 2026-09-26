import pandas as pd, numpy as np, glob, os
S="/sessions/inspiring-magical-curie/mnt/cotdata_store"
u=pd.read_parquet("/sessions/inspiring-magical-curie/mnt/trading_workspace/cotmetrics/docs/analysis/2026-09-26-cot-flow-states-universe.parquet")
px=u.dropna(subset=["close"]).set_index(["symbol","date"])["close"]
D={"MM":("M_Money_Positions_Long_All","M_Money_Positions_Short_All"),"Other":("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All"),
   "NonRep":("NonRept_Positions_Long_All","NonRept_Positions_Short_All"),"Prod":("Prod_Merc_Positions_Long_All","Prod_Merc_Positions_Short_All"),"Swap":("Swap_Positions_Long_All","Swap__Positions_Short_All")}
T={"Dealer":("Dealer_Positions_Long_All","Dealer_Positions_Short_All"),"AssetMgr":("Asset_Mgr_Positions_Long_All","Asset_Mgr_Positions_Short_All"),
   "LevFund":("Lev_Money_Positions_Long_All","Lev_Money_Positions_Short_All"),"Other":("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All"),"NonRep":("NonRept_Positions_Long_All","NonRept_Positions_Short_All")}
def load(f):
    d=pd.read_parquet(f)
    if "As_of_Date_In_Form_YYMMDD" in d: d.index=pd.to_datetime(d["As_of_Date_In_Form_YYMMDD"].astype(int).astype(str).str.zfill(6),format="%y%m%d")
    else: d.index=pd.to_datetime(d.index)
    return d[~d.index.duplicated()].sort_index()
out=[]
for rep,C in (("disagg",D),("tff",T)):
    for f in sorted(glob.glob(f"{S}/cot_{rep}/*.parquet")):
        sym=os.path.basename(f).split("_")[0]
        if sym=="RTY" and "23977A" in f: continue
        if sym not in px.index.get_level_values(0): continue
        d=load(f)
        if len(d)<300: continue
        net=pd.DataFrame({k:d[l]-d[s] for k,(l,s) in C.items()}); gross=pd.DataFrame({k:d[l]+d[s] for k,(l,s) in C.items()})
        dn=net.diff(); p=px.loc[sym]; r=np.log(p).diff().reindex(dn.index)
        cm=dn.corr()
        for c in C:
            out.append(dict(report=rep,sym=sym,cohort=c,px_corr=round(dn[c].corr(r),2),gross_share=round(float((gross[c]/gross.sum(axis=1)).iloc[-52:].mean()),2),
                            **{f"c_{k}":round(cm.loc[c,k],2) for k in C if k!=c}))
t=pd.DataFrame(out)
t.to_csv("/tmp/cohort_roles.csv",index=False)
pd.set_option("display.width",250)
for rep in ("disagg","tff"):
    x=t[t.report==rep]
    print(f"\n== {rep}: same-week price correlation of each cohort's weekly net change (rows=markets) ==")
    print(x.pivot(index="sym",columns="cohort",values="px_corr").to_string())
    print(f"\n== {rep}: gross share (last 52w) ==")
    print(x.pivot(index="sym",columns="cohort",values="gross_share").to_string())
import pandas as pd, numpy as np
t=pd.read_csv("/tmp/cohort_roles.csv")
TH=0.15; MIN_SHARE=0.05
def role(r):
    if r.cohort=="NonRep": return "RETAIL"
    if r.gross_share<MIN_SHARE: return "inert(<5%)"
    if r.px_corr>=TH: return "SPEC"
    if r.px_corr<=-TH: return "COUNTERPARTY"
    return "NEUTRAL"
t["role"]=t.apply(role,axis=1)
rows=[]
for (rep,sym),g in t.groupby(["report","sym"]):
    g=g.set_index("cohort")
    spec=[c for c in g.index if g.loc[c,"role"]=="SPEC"]; cp=[c for c in g.index if g.loc[c,"role"]=="COUNTERPARTY"]
    neu=[c for c in g.index if g.loc[c,"role"]=="NEUTRAL"]; inert=[c for c in g.index if g.loc[c,"role"].startswith("inert")]
    # merge check: cohorts sharing a role should not have negative flow corr
    def ok(lst): return all(g.loc[a,f"c_{b}"]>=0 for i,a in enumerate(lst) for b in lst[i+1:])
    retail_beh=g.loc["NonRep","role"] if False else ("spec-like" if g.loc["NonRep","px_corr"]>=TH else "cp-like" if g.loc["NonRep","px_corr"]<=-TH else "neutral")
    rows.append(dict(report=rep,sym=sym,SPEC="+".join(spec) or "-",COUNTERPARTY="+".join(cp) or "-",NEUTRAL="+".join(neu) or "-",inert="+".join(inert) or "-",
                     spec_merge_ok=ok(spec),cp_merge_ok=ok(cp),retail_behaves=retail_beh,
                     buckets=(1 if spec else 0)+(1 if cp else 0)+(1 if neu else 0)+1))
R=pd.DataFrame(rows)
pd.set_option("display.width",250)
print(R.to_string(index=False))
print("\nbucket count distribution:",R.buckets.value_counts().to_dict())
print("retail behaves:",R.retail_behaves.value_counts().to_dict())
R.to_csv("/tmp/cohort_collapse.csv",index=False)
