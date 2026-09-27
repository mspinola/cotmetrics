import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import cotdata
from cotmetrics import categories
U = "GF HE LE CT CC KC LBR OJ SB HG GC PA PL SI CL NG RB HO ZC ZS ZM ZL ZW".split()
specs = {s.key: s for s in categories.categories_for("disagg")}
NAMES = {(1,1,1):"BROAD_ACCUM",(1,1,-1):"INST_BUY_RETAIL_SELL",(1,-1,1):"TREND+RETAIL_BUY",(1,-1,-1):"MM_ALONE_BUY",
         (-1,1,1):"MM_SELL_OTHERS_BUY",(-1,1,-1):"VALUE_ACCUM",(-1,-1,1):"RETAIL_ALONE_BUY",(-1,-1,-1):"BROAD_LIQUID"}
def z(d): return d / d.rolling(52, min_periods=26).std()
def sg(zz): return np.sign(zz).where(zz.abs() > 1.0, 0).fillna(0).astype(int)
def states(fr, col_fn):
    s = [sg(z(fr[col_fn(specs[k])].astype(float).diff())) for k in ("managed_money","other_reportable","nonreportable")]
    return pd.Series([NAMES.get(t, "PARTIAL" if t != (0,0,0) else "QUIET") for t in zip(*s)], index=fr.index)
rows = []
for sym in U:
    fr = categories.build_category_frame(cotdata.get_cot(sym, report="disagg"), "disagg", 52)
    a, b = states(fr, categories.net_col), states(fr, categories.pct_oi_col)
    named_a, named_b = a.isin(NAMES.values()), b.isin(NAMES.values())
    rows.append(dict(sym=sym, weeks=len(a), state_differs=int((a != b).sum()),
        named_on_contracts=int(named_a.sum()), named_on_pct_oi=int(named_b.sum()),
        named_on_both_same=int((named_a & named_b & (a == b)).sum()),
        boxed_only_one_basis=int((named_a ^ named_b).sum()),
        VA_contracts=int((a == "VALUE_ACCUM").sum()), VA_pct_oi=int((b == "VALUE_ACCUM").sum()),
        VA_both=int(((a == "VALUE_ACCUM") & (b == "VALUE_ACCUM")).sum())))
t = pd.DataFrame(rows).set_index("sym"); pd.set_option("display.width", 240)
print(t.to_string())
print("\npooled: state label differs on", t.state_differs.sum(), "of", t.weeks.sum(), "market-weeks =", round(t.state_differs.sum()/t.weeks.sum(),3))
print("pooled named (boxed) weeks: contracts", t.named_on_contracts.sum(), " pct_oi", t.named_on_pct_oi.sum(), " same label on both", t.named_on_both_same.sum(), " boxed under only one basis", t.boxed_only_one_basis.sum())
print("pooled VALUE_ACCUM: contracts", t.VA_contracts.sum(), " pct_oi", t.VA_pct_oi.sum(), " both", t.VA_both.sum())
