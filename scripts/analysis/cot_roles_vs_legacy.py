import pandas as pd, numpy as np, glob, os
S="/sessions/inspiring-magical-curie/mnt/cotdata_store"
R=pd.read_csv("/tmp/cohort_collapse.csv")
D={"MM":("M_Money_Positions_Long_All","M_Money_Positions_Short_All"),"Other":("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All"),"NonRep":("NonRept_Positions_Long_All","NonRept_Positions_Short_All"),"Prod":("Prod_Merc_Positions_Long_All","Prod_Merc_Positions_Short_All"),"Swap":("Swap_Positions_Long_All","Swap__Positions_Short_All")}
T={"Dealer":("Dealer_Positions_Long_All","Dealer_Positions_Short_All"),"AssetMgr":("Asset_Mgr_Positions_Long_All","Asset_Mgr_Positions_Short_All"),"LevFund":("Lev_Money_Positions_Long_All","Lev_Money_Positions_Short_All"),"Other":("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All"),"NonRep":("NonRept_Positions_Long_All","NonRept_Positions_Short_All")}
def load(f):
    d=pd.read_parquet(f)
    if "As_of_Date_In_Form_YYMMDD" in d: d.index=pd.to_datetime(d["As_of_Date_In_Form_YYMMDD"].astype(int).astype(str).str.zfill(6),format="%y%m%d")
    else: d.index=pd.to_datetime(d.index)
    return d[~d.index.duplicated()].sort_index()
rows=[]
for _,r in R.iterrows():
    rep,sym=r.report,r.sym; C=D if rep=="disagg" else T
    fs=[f for f in glob.glob(f"{S}/cot_{rep}/{sym}_*.parquet") if not (sym=="RTY" and "23977A" in f)]
    lf=glob.glob(f"{S}/cot_legacy/{sym}_*.parquet")
    if not fs or not lf: continue
    d=load(fs[0]); L=load(lf[0])
    net={k:(d[l]-d[s]) for k,(l,s) in C.items()}
    def grp(names): return sum(net[n] for n in names.split("+")) if names!="-" else None
    spec,cp=grp(r.SPEC),grp(r.COUNTERPARTY)
    lc=(L.Comm_Positions_Long_All-L.Comm_Positions_Short_All); ln=(L.NonComm_Positions_Long_All-L.NonComm_Positions_Short_All)
    ix=d.index.intersection(L.index)
    def c(a,b): return round(a.reindex(ix).diff().corr(b.reindex(ix).diff()),2) if a is not None else np.nan
    rows.append((rep,sym,r.SPEC,c(spec,ln),r.COUNTERPARTY,c(cp,lc)))
t=pd.DataFrame(rows,columns=["report","sym","SPEC","flowcorr_SPEC_vs_LegacyNonComm","COUNTERPARTY","flowcorr_CP_vs_LegacyComm"])
pd.set_option("display.width",200); print(t.to_string(index=False))
