import warnings, glob, os
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from cotdata import get_cot, store
from cotmetrics import categories as cat
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)

def legs(df, report):
    out = {}
    for s in cat.categories_for(report):
        lo = cat._numeric(cat._resolve(df, s.long_col)).astype(float)
        sh = cat._numeric(cat._resolve(df, s.short_col)).astype(float)
        out[s.key] = lo - sh
    return out

print("=== LBR primary code 058644 gaps ===")
p = store.read_cot_disagg("LBR_058644"); h = store.read_cot_disagg("LBR_058643")
pi = pd.DatetimeIndex(p.index); hi = pd.DatetimeIndex(h.index)
g = pd.Series(pi).diff().dt.days
print("primary first 12 dates:", [str(d.date()) for d in pi[:12]])
print("primary gaps>8d:", [(str(pi[i].date()), int(g.iloc[i])) for i in range(len(g)) if g.iloc[i] > 8])
print("hist last 10 dates:", [str(d.date()) for d in hi[-10:]])
print("hist OI last 10:", h["Open_Interest_All"].tail(10).tolist(), " primary OI first 10:", p["Open_Interest_All"].head(10).tolist())
print("primary rows before 2023-05:", int((pi < "2023-05-01").sum()))
print("\n=== 6N gap ===")
d = get_cot("6N", report="tff"); idx = pd.DatetimeIndex(d.index); g = pd.Series(idx).diff().dt.days
print([(str(idx[i-1].date()), str(idx[i].date()), int(g.iloc[i])) for i in range(len(g)) if g.iloc[i] > 8])
print("\n=== RTY primary code 239742 internal gap ===")
p = store.read_cot_tff("RTY_239742"); pi = pd.DatetimeIndex(p.index); g = pd.Series(pi).diff().dt.days
print([(str(pi[i-1].date()), str(pi[i].date()), int(g.iloc[i])) for i in range(len(g)) if g.iloc[i] > 8])

print("\n=== SUPPLEMENTAL ===")
for f in sorted(glob.glob("/Users/matts/code/cotdata_store/cot_supplemental/*.parquet")):
    s = pd.read_parquet(f); sym = os.path.basename(f).split("_")[0]
    cols = [c for c in s.columns if "CIT" in c or "NoCIT" in c][:6]
    print(sym, len(s), str(pd.DatetimeIndex(s.index).min().date()), str(pd.DatetimeIndex(s.index).max().date()), "combined?", s.get("FutOnly_or_Combined", pd.Series(["n/a"])).iloc[0] if "FutOnly_or_Combined" in s else "no column")
print("CIT-ish columns on ZW:", [c for c in pd.read_parquet("/Users/matts/code/cotdata_store/cot_supplemental/ZW_001602.parquet").columns if "CIT" in c])
zw_s = get_cot("ZW", report="supplemental"); zw_d = get_cot("ZW", report="disagg")
j = zw_s[["Open_Interest_All"]].join(zw_d[["Open_Interest_All"]], lsuffix="_supp", rsuffix="_disagg", how="inner")
print("ZW OI supplemental vs disagg, last 3 weeks:\n", j.tail(3))
print("ZW OI ratio supp/disagg median:", float((j.iloc[:, 0] / j.iloc[:, 1]).median()))

print("\n=== TFF counterparty correlations of dNet (per market) ===")
TFFC = {"rates": "ZB ZN ZF ZT".split(), "equity": "YM NQ RTY ES".split(), "crypto": "BTC ETH".split(), "fx": "6A 6B 6C 6S 6E 6J 6M 6N DX".split()}
recs = []
for cls, syms in TFFC.items():
    for sym in syms:
        df = get_cot(sym, report="tff"); n = legs(df, "tff"); dn = {k: v.diff() for k, v in n.items()}
        oi = cat._numeric(df["Open_Interest_All"]).astype(float)
        def c(a, b): return float(dn[a].corr(dn[b]))
        recs.append(dict(cls=cls, sym=sym, lev_dealer=c("leveraged", "dealer"), lev_am=c("leveraged", "asset_manager"),
                         am_dealer=c("asset_manager", "dealer"), lev_other=c("leveraged", "other_reportable"),
                         lev_nonrep=c("leveraged", "nonreportable"), am_other=c("asset_manager", "other_reportable"),
                         gross_share_dealer=float(((cat._numeric(cat._resolve(df, "Dealer_Positions_Long_All")) + cat._numeric(cat._resolve(df, "Dealer_Positions_Short_All"))) / (2 * oi)).tail(52).mean()),
                         gross_share_am=float(((cat._numeric(cat._resolve(df, "Asset_Mgr_Positions_Long_All")) + cat._numeric(cat._resolve(df, "Asset_Mgr_Positions_Short_All"))) / (2 * oi)).tail(52).mean()),
                         gross_share_lev=float(((cat._numeric(cat._resolve(df, "Lev_Money_Positions_Long_All")) + cat._numeric(cat._resolve(df, "Lev_Money_Positions_Short_All"))) / (2 * oi)).tail(52).mean()),
                         gross_share_other=float(((cat._numeric(cat._resolve(df, "Other_Rept_Positions_Long_All")) + cat._numeric(cat._resolve(df, "Other_Rept_Positions_Short_All"))) / (2 * oi)).tail(52).mean())))
t = pd.DataFrame(recs); print(t.round(2).to_string(index=False))
print("\nmedian by class:\n", t.groupby("cls").median(numeric_only=True).round(2).to_string())

print("\n=== DISAGG counterparty correlations of dNet ===")
DIS = "GF HE LE CT CC KC LBR OJ SB HG GC PA PL SI CL NG RB HO ZC ZS ZM ZL ZW".split()
recs = []
for sym in DIS:
    df = get_cot(sym, report="disagg"); n = legs(df, "disagg"); dn = {k: v.diff() for k, v in n.items()}
    dn["comm"] = dn["producer_merchant"] + dn["swap"]
    def c(a, b): return float(dn[a].corr(dn[b]))
    recs.append(dict(sym=sym, mm_comm=c("managed_money", "comm"), mm_prod=c("managed_money", "producer_merchant"), mm_swap=c("managed_money", "swap"),
                     mm_other=c("managed_money", "other_reportable"), mm_nonrep=c("managed_money", "nonreportable"), other_comm=c("other_reportable", "comm"), nonrep_comm=c("nonreportable", "comm")))
t = pd.DataFrame(recs); print(t.round(2).to_string(index=False)); print("median:\n", t.median(numeric_only=True).round(2).to_string())

print("\n=== VINTAGE OBSERVATIONS ===")
for y in (2025, 2026):
    f = f"/Users/matts/code/cotdata_store/vintage/observations/report_year={y}/observations.parquet"
    o = pd.read_parquet(f)
    print(y, o.shape); print(list(o.columns))
    if y == 2026: print(o.head(3).to_string())
    if "report_type" in o: print(o["report_type"].value_counts().to_dict())
    key = [k for k in ("report_date", "market_code", "report_type", "combined", "category") if k in o.columns]
    if key:
        cnt = o.groupby(key).size()
        print("natural keys:", len(cnt), " keys with >1 observation (a revision):", int((cnt > 1).sum()))
        if "observed_at" in o: print("observed_at range:", o["observed_at"].min(), o["observed_at"].max(), " distinct:", o["observed_at"].nunique())
        if "snapshot_id" in o: print("snapshots:", o["snapshot_id"].nunique())
        multi = cnt[cnt > 1]
        if len(multi):
            m = o.set_index(key).loc[multi.index[:5]]
            print(m.to_string())
            # share of market-weeks with a category net revised >1%
            if {"long", "short"} <= set(o.columns):
                o["net"] = o["long"] - o["short"]
                g = o.sort_values("observed_at").groupby(key)["net"].agg(["first", "last"])
                rel = ((g["last"] - g["first"]).abs() / g["first"].abs().replace(0, np.nan))
                print("share keys with |dnet rev| > 1%:", float((rel > 0.01).mean()), "n>1%:", int((rel > 0.01).sum()))
revdir = "/Users/matts/code/cotdata_store/vintage/revisions"
print("revisions dir exists:", os.path.isdir(revdir), glob.glob(revdir + "/*")[:5] if os.path.isdir(revdir) else "")
print("snapshots.json size:", os.path.getsize("/Users/matts/code/cotdata_store/vintage/snapshots.json"))
print("run.log tail:"); print(open("/Users/matts/code/cotdata_store/vintage/run.log").read()[-1500:])
