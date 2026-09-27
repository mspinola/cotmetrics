"""COT flow states, the handoff's scope: the 42-market replication re-tabulated under
ADR-0005's universe (physical commodities and currencies), with and without gold (the
discovery market), and re-anchored at the first settlement strictly AFTER the resolved
CFTC release date.

Origin: docs/handoffs/2026-09-26-cot-flow-states-cross-universe.md asked for the pooled
test on the ADR-0005 universe (npf/docs/adr/ADR-0005-cot-group-semantics-by-market.md:
COT-gated readings apply to physical commodities and currencies; index futures and
Treasuries have no interpretable split). cot_flow_states_universe.py pooled all 42
markets; this script reads its parquet and re-cuts it. Nothing about the design changes:
same states, same threshold, same window, same horizons, same per-report role mapping.

Anchor. The universe doc's "Friday" diagnostic starts at the settlement on report date +
3 days. That close prints before the 15:30 ET publication on every exchange in the
universe (COMEX metals settle 13:30 ET, grains 14:20, energies 14:30), and the CFTC
published 13 of the reports dated 2025-09-30 to 2025-12-23 between 7 and 50 days late.
Here the anchor is the first settlement strictly after the resolved release date, the
workspace's Monday-close convention (npf/scripts/episode_age_v6.py ENTRY_LAG_DAYS = 6;
npf/docs/npf/episode_age_closed.md finding 7). The release date comes from cotdata's
release schedule (published, announced or scheduled) where it has one, and from
cotdata.vintage_schedule.derive_release_date (report date + 3, pushed off a weekend)
elsewhere; the JSON records how many rows took each source.

Every pooling choice and anchor below is one 'tried' entry in a SearchSpaceLog under its
own scope, so the denominator of any later gauntlet can include them.

Usage:
  COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \\
  python scripts/analysis/cot_flow_states_scope.py --analysis docs/analysis
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from crucible.validation import SearchSpaceLog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cot_flow_states_universe as U  # noqa: E402  (hac_se, stats_row, state tables)

IN_PREFIX = "2026-09-26-cot-flow-states-universe"
PREFIX = "2026-09-26-cot-flow-states-scope"
SCOPE = "cot_flow_states:adr0005-scope-2026-09-26"

ADR0005_CLASSES = ("Live Stock", "Softs", "Metals", "Energies", "Grains", "Currencies")
DISCOVERY = ("GC",)
HORIZON_WEEKS = 13
ANCHOR_TOL = pd.Timedelta("7D")


def release_anchored_returns(frame, weeks=HORIZON_WEEKS):
    """13-week log return from the first propadj settlement strictly after the resolved
    release date to the first settlement on or after that anchor + 13 weeks."""
    from cotdata import vintage_schedule as vs
    from marketdata import get_bars

    sched = vs.read_release_schedule()
    smap = {pd.Timestamp(r).normalize(): pd.Timestamp(d).normalize()
            for r, d in zip(sched["report_date"], sched["release_date"])}
    out = pd.Series(np.nan, index=frame.index)
    src = pd.Series("derived", index=frame.index, dtype=object)
    for sym, g in frame.groupby("symbol"):
        bars = get_bars(sym, "propadj", domain="futures")
        close = bars["Close"].astype(float)
        close = close[close > 0].dropna().sort_index()
        idx = close.index
        dates = pd.DatetimeIndex(g["date"]).normalize()
        rel = []
        for d in dates:
            if d in smap:
                rel.append(smap[d])
                src.loc[g.index[len(rel) - 1]] = "schedule"
            else:
                rel.append(pd.Timestamp(vs.derive_release_date(d)))
        rel = pd.DatetimeIndex(rel)
        ia = idx.searchsorted(rel, side="right")          # strictly after the release
        anchors = pd.DatetimeIndex(np.where(ia < len(idx), idx.values[np.minimum(ia, len(idx) - 1)],
                                            np.datetime64("NaT")))
        ends = anchors + pd.Timedelta(weeks=weeks)
        ie = idx.searchsorted(ends.fillna(idx[-1] + pd.Timedelta("1D")), side="left")
        ok = (ia < len(idx)) & (ie < len(idx)) & ((anchors - rel) <= ANCHOR_TOL)
        vals = np.full(len(g), np.nan)
        vals[ok] = np.log(close.values[ie[ok]]) - np.log(close.values[ia[ok]])
        out.loc[g.index] = vals
    return out, src


def cofiring(pool, states=("VALUE_ACCUM", "BROAD_LIQUID")):
    rows = {}
    for st in states:
        sub = pool[pool["state"] == st]
        per_week = sub.groupby("date")["symbol"].nunique()
        rows[st] = dict(rows=int(len(sub)), distinct_weeks=int(per_week.shape[0]),
                        weeks_with_3_or_more=int((per_week >= 3).sum()),
                        share_of_rows_in_weeks_with_3_or_more=float(
                            sub["date"].map(per_week).ge(3).mean()) if len(sub) else np.nan,
                        max_markets_in_one_week=int(per_week.max()) if len(per_week) else 0)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", required=True, help="docs/analysis dir holding the universe parquet")
    a = ap.parse_args()
    t0 = time.time()
    pq = os.path.join(a.analysis, f"{IN_PREFIX}.parquet")
    df = pd.read_parquet(pq).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    log_path = os.path.join(a.analysis, f"{PREFIX}.searchlog.jsonl")
    if os.path.exists(log_path):
        os.remove(log_path)
    log = SearchSpaceLog(scope=SCOPE, path=log_path)

    print("release-anchored returns ...")
    df["fwd13_rel"], src = release_anchored_returns(df)
    src_counts = src.value_counts().to_dict()
    print("  release-date source:", src_counts)

    scopes = {
        "adr0005": df[df["asset_class"].isin(ADR0005_CLASSES)],
        "adr0005_exGC": df[df["asset_class"].isin(ADR0005_CLASSES) & ~df["symbol"].isin(DISCOVERY)],
    }
    anchors = {"tuesday_propadj": "fwd13_pa", "release_next_settle": "fwd13_rel"}
    results = dict(config=dict(classes=ADR0005_CLASSES, discovery_excluded=DISCOVERY,
                               horizon_weeks=HORIZON_WEEKS, anchor_tolerance_days=7,
                               release_source_counts=src_counts,
                               input_parquet=pq, generated=time.strftime("%Y-%m-%dT%H:%M:%S")),
                   pooled={}, per_class={}, single_cohort={}, per_market_value_accum={},
                   cofiring={}, big_moves_propadj={})
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda v: f"{v:,.2f}")

    for sname, pool in scopes.items():
        syms = sorted(pool["symbol"].unique())
        print(f"\n===== scope {sname}: {len(syms)} markets, {len(pool):,} market-weeks =====")
        results["pooled"][sname] = {}
        for aname, col in anchors.items():
            tab = pd.DataFrame([U.stats_row(g, col, HORIZON_WEEKS, dict(state=st))
                                for st, g in pool.groupby("state", sort=False)] +
                               [U.stats_row(pool, col, HORIZON_WEEKS, dict(state="ALL"))])
            tab = tab[tab["n"] > 0].sort_values("n", ascending=False).reset_index(drop=True)
            results["pooled"][sname][aname] = U._jsonable(tab, index=False)
            print(f"\n-- fwd13 by state, {sname}, anchor {aname} --")
            print(tab.to_string(index=False))
            log.record(dict(scope_filter=sname, anchor=aname, horizon=HORIZON_WEEKS,
                            markets=syms, **U.CONFIG), status="tried")
        # 4-week, Tuesday propadj only
        tab4 = pd.DataFrame([U.stats_row(g, "fwd4_pa", 4, dict(state=st))
                             for st, g in pool.groupby("state", sort=False)] +
                            [U.stats_row(pool, "fwd4_pa", 4, dict(state="ALL"))])
        tab4 = tab4[tab4["n"] > 0].sort_values("n", ascending=False).reset_index(drop=True)
        results["pooled"][sname]["tuesday_propadj_fwd4"] = U._jsonable(tab4, index=False)
        print(f"\n-- fwd4 by state, {sname}, anchor tuesday_propadj --")
        print(tab4.to_string(index=False))
        log.record(dict(scope_filter=sname, anchor="tuesday_propadj", horizon=4,
                        markets=syms, **U.CONFIG), status="tried")
        # single-cohort baseline, 13w, both anchors
        results["single_cohort"][sname] = {}
        for aname, col in anchors.items():
            rows = []
            for role in ("TREND", "VALUE", "RETAIL"):
                for sgn, lab in ((1, "buy"), (-1, "sell")):
                    sub = pool[pool[f"s_{role}"] == sgn]
                    rows.append(U.stats_row(sub, col, HORIZON_WEEKS, dict(role=role, move=lab)))
            sc = pd.DataFrame(rows)
            results["single_cohort"][sname][aname] = U._jsonable(sc, index=False)
            print(f"\n-- single-cohort fwd13, {sname}, anchor {aname} --")
            print(sc.to_string(index=False))
        # per-market VALUE_ACCUM sign count, tuesday propadj
        pm = []
        for sym, g in pool.groupby("symbol"):
            va = g.loc[g["state"] == "VALUE_ACCUM", "fwd13_pa"].dropna()
            un = g["fwd13_pa"].dropna()
            pm.append(dict(symbol=sym, asset_class=g["asset_class"].iloc[0], n=int(len(va)),
                           mean=va.mean() * 100 if len(va) else np.nan, uncond=un.mean() * 100,
                           above=bool(len(va) >= 5 and va.mean() > un.mean())))
        pm = pd.DataFrame(pm)
        elig = pm[pm["n"] >= 5]
        results["per_market_value_accum"][sname] = dict(
            table=U._jsonable(pm, index=False), above=int(elig["above"].sum()), eligible=int(len(elig)))
        print(f"\n-- VALUE_ACCUM per market ({sname}): {int(elig['above'].sum())} of {len(elig)} with n>=5 above own unconditional --")
        # co-firing
        results["cofiring"][sname] = cofiring(pool)
        print("\n-- co-firing --")
        print(json.dumps(results["cofiring"][sname], indent=1))
        log.record(dict(diagnostic="cofiring_distinct_weeks", scope_filter=sname), status="tried")

    # per class, scope adr0005, 13w tuesday propadj
    pool = scopes["adr0005"]
    for klass, g in pool.groupby("asset_class"):
        tab = pd.DataFrame([U.stats_row(h, "fwd13_pa", HORIZON_WEEKS, dict(state=st))
                            for st, h in g.groupby("state", sort=False)] +
                           [U.stats_row(g, "fwd13_pa", HORIZON_WEEKS, dict(state="ALL"))])
        tab = tab[tab["n"] > 0].sort_values("n", ascending=False).reset_index(drop=True)
        results["per_class"][klass] = U._jsonable(tab, index=False)
        print(f"\n-- fwd13 by state, class {klass}, tuesday_propadj --")
        print(tab.to_string(index=False))
    log.record(dict(diagnostic="per_class_fwd13", scope_filter="adr0005", anchor="tuesday_propadj",
                    classes=sorted(pool["asset_class"].unique())), status="tried")

    # big moves on the propadj basis (all 42), to qualify the doc's 1,228 cache figure
    big = df[df["fwd13_pa"].abs() > 0.5]
    results["big_moves_propadj"] = dict(total=int(len(big)),
                                        by_symbol=big["symbol"].value_counts().head(8).to_dict())
    print("\n|fwd13_pa| > 50%:", results["big_moves_propadj"])

    results["search_log"] = dict(path=log_path, n_variants=log.n_variants)
    out = os.path.join(a.analysis, f"{PREFIX}.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"\nSearchSpaceLog n_variants = {log.n_variants}")
    print("wrote", out, f"in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
