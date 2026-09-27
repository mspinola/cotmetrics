"""Consequence check: flow z under the fixed 52/26 window vs under the page's per-market
CustomLookbackWeeks (what build_category_frame would receive from get_category_data at
lookback='Custom'). Counts weeks whose 1-sigma sign (active/inactive, direction) differs."""
import numpy as np, pandas as pd, cotdata
from cotmetrics import categories as cat
from cotmetrics.indexer import get_indexer

ix = get_indexer()
rows = []
for name, sym, rep in [("Gold","GC","disagg"), ("Feeder Cattle","GF","disagg"),
                       ("30-Year Note","ZB","tff"), ("S&P 500","ES","tff"), ("Crude Oil","CL","disagg")]:
    inst = ix.get_instrument_from_name(name)
    code = ix.get_instrument_code_from_name(name)
    raw = cotdata.get_cot(code, report=rep)
    lb = inst.custom_lookback
    fr = cat.build_category_frame(raw, rep, lb)
    specs = cat.present_categories(fr, rep)
    for s in specs:
        dnet = fr[cat.net_col(s)].diff()
        z52 = dnet / dnet.rolling(52, min_periods=26).std()
        zlb = dnet / dnet.rolling(lb, min_periods=max(2, lb//2)).std()
        sg = lambda z: np.where(z > 1, 1, np.where(z < -1, -1, 0))
        m = z52.notna() & zlb.notna()
        a, b = sg(z52[m]), sg(zlb[m])
        rows.append((sym, lb, s.key, int(m.sum()), int((a != b).sum()), round(float((a != b).mean()*100),1)))
df = pd.DataFrame(rows, columns=["sym","custom_lb","cohort","n","sign_differs","pct"])
print(df.to_string(index=False))
