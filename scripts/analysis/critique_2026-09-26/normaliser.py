import numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
import cotdata
from cotmetrics import categories
U = "GF HE LE CT CC KC LBR OJ SB HG GC PA PL SI CL NG RB HO ZC ZS ZM ZL ZW".split()
specs = {s.key: s for s in categories.categories_for("disagg")}
rows=[]; occ=[]
def z(d): return d / d.rolling(52, min_periods=26).std()
for sym in U:
    raw = cotdata.get_cot(sym, report="disagg")
    fr = categories.build_category_frame(raw, "disagg", 52)
    net = {k: fr[categories.net_col(specs[k])].astype(float) for k in ("managed_money","other_reportable","nonreportable")}
    oi = pd.to_numeric(raw["Open_Interest_All"], errors="coerce").reindex(fr.index)
    d = net["managed_money"].diff()
    z_sd = z(d); z_oi = d/oi; z_lvl = d/net["managed_money"].rolling(52,min_periods=26).std()
    rows.append(dict(sym=sym, n=len(d), medOI=int(oi.median()), sd_dNet=int(d.std()),
        sd_dNet_over_OI_pct=round(z_oi.std()*100,2), roll52sd_max_over_min=round((d.rolling(52).std().max()/d.rolling(52).std().min()),1),
        oi_max_over_min=round(oi.max()/oi.min(),1), kurt_zsd=round(z_sd.kurt(),1), kurt_zoi=round(z_oi.kurt(),1),
        p_zsd_gt1=round((z_sd.abs()>1).mean(),3), p_zoi_gt1sd=round((z_oi.abs()>z_oi.std()).mean(),3),
        corr_zsd_zlvl=round(z_sd.corr(z_lvl),2), sd_zlvl=round(z_lvl.std(),3), lag1_zsd=round(z_sd.autocorr(1),2)))
    s = {k: np.sign(z(v.diff())).where(z(v.diff()).abs()>1, 0) for k,v in net.items()}
    va = (s["managed_money"]==-1)&(s["other_reportable"]==1)&(s["nonreportable"]==-1)
    full = (pd.DataFrame(s)!=0).all(axis=1)
    occ.append(dict(sym=sym, weeks=len(va), value_accum=int(va.sum()), all_three_active=int(full.sum())))
t = pd.DataFrame(rows).set_index("sym"); pd.set_option("display.width",240)
print(t.to_string())
print("\nsd(dNet/OI) % across markets: min", t.sd_dNet_over_OI_pct.min(), "max", t.sd_dNet_over_OI_pct.max(), "max/min", round(t.sd_dNet_over_OI_pct.max()/t.sd_dNet_over_OI_pct.min(),1))
print("P(|z_sd|>1): min", t.p_zsd_gt1.min(), "median", t.p_zsd_gt1.median(), "max", t.p_zsd_gt1.max(), "(gaussian 0.317)")
print("P(|z_oi|>1sd): min", t.p_zoi_gt1sd.min(), "median", t.p_zoi_gt1sd.median(), "max", t.p_zoi_gt1sd.max())
print("kurtosis z_sd median", t.kurt_zsd.median(), " z_oi median", t.kurt_zoi.median())
print("sd(dNet / rolling sd of LEVEL): min", t.sd_zlvl.min(), "max", t.sd_zlvl.max())
print("within-market rolling-52 sd of dNet, max/min: median", t.roll52sd_max_over_min.median(), "max", t.roll52sd_max_over_min.max())
print("OI max/min within market: median", t.oi_max_over_min.median(), "max", t.oi_max_over_min.max())
print("lag1 autocorr of z_sd: median", t.lag1_zsd.median(), "min", t.lag1_zsd.min(), "max", t.lag1_zsd.max())
o = pd.DataFrame(occ).set_index("sym"); print("\nVALUE_ACCUM occupancy per market (counts only):"); print(o.T.to_string())
print("pooled VALUE_ACCUM weeks =", o.value_accum.sum(), " pooled all-three-active =", o.all_three_active.sum(), " of", o.weeks.sum(), "market-weeks")
