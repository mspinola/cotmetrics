"""Legacy equivalence of the per-market role groups, on the propadj-measured roles.

Re-run of scripts/analysis/cot_roles_vs_legacy.py (Cowork session, handoff Addendum 3),
which read the cache-close role table. This one reads the ratio-adjusted table
docs/analysis/2026-09-26-cot-cohort-collapse-propadj.csv, so HO, RB, CL, HE, LBR, ETH and
ZF, whose roles changed with the price series, get their Legacy correlation on the roles
that will ship. Same measurement: weekly-flow correlation of the SPEC group's net with
Legacy Non-Commercial net, and of the COUNTERPARTY group's net with Legacy Commercial net,
over the weeks both reports share. No threshold, no search.

Usage:
  COTDATA_STORE=~/code/cotdata_store python scripts/analysis/cot_roles_vs_legacy_propadj.py \\
      --collapse docs/analysis/2026-09-26-cot-cohort-collapse-propadj.csv \\
      --out docs/analysis/2026-09-26-cot-roles-vs-legacy-propadj.csv
"""

import argparse

import cotdata
import numpy as np
import pandas as pd

from cotmetrics import categories as cat


def _net(raw, report, keys):
    specs = {s.key: s for s in cat.categories_for(report)}
    total = None
    for k in keys:
        s = specs[k]
        lo = cat._numeric(cat._resolve(raw, s.long_col))
        sh = cat._numeric(cat._resolve(raw, s.short_col))
        if lo is None or sh is None:
            return None
        total = (lo - sh) if total is None else total + (lo - sh)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collapse", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    table = pd.read_csv(a.collapse)
    rows = []
    for _, r in table.iterrows():
        raw = cotdata.get_cot(r.sym, report=r.report)
        leg = cotdata.get_cot(r.sym, report="legacy")
        if raw is None or raw.empty or leg is None or leg.empty:
            continue
        ix = raw.index.intersection(leg.index)
        ln = (leg["NonComm_Positions_Long_All"] - leg["NonComm_Positions_Short_All"]).astype(float)
        lc = (leg["Comm_Positions_Long_All"] - leg["Comm_Positions_Short_All"]).astype(float)

        def corr(keys_str, legacy_net):
            if keys_str == "-" or pd.isna(keys_str):
                return np.nan
            g = _net(raw, r.report, keys_str.split("+"))
            if g is None:
                return np.nan
            return round(g.reindex(ix).diff().corr(legacy_net.reindex(ix).diff()), 2)

        rows.append(dict(report=r.report, sym=r.sym, SPEC=r.SPEC,
                         flowcorr_SPEC_vs_LegacyNonComm=corr(r.SPEC_keys, ln),
                         COUNTERPARTY=r.COUNTERPARTY,
                         flowcorr_CP_vs_LegacyComm=corr(r.COUNTERPARTY_keys, lc),
                         weeks=int(len(ix))))
    out = pd.DataFrame(rows)
    out.to_csv(a.out, index=False)
    pd.set_option("display.width", 200)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
