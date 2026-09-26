"""Per-market cohort roles re-measured on the ratio-adjusted price series, with stability.

Origin: `docs/analysis/2026-09-26-cot-cohort-roles.md` (the Cowork session) assigned each
Disaggregated and TFF cohort a role per market from the same-week correlation of its weekly
net change with the price return. That script read the `close` column of
`2026-09-26-cot-flow-states-universe.parquet`, which is cot-analyzer's cache close: an
additively back-adjusted series that goes non-positive on long commodity histories, so a
log return exists on only 215 of 1,059 weeks for LBR, 233 for HO, 240 for RB and 405 for
OJ. This script applies the same rule, unchanged, to weekly log returns of the
`propadj` futures tier of marketdata, which is ratio-adjusted and stays positive, and then
asks the question the origin doc left open: does the assignment hold on rolling windows?

The rule was fixed before the run and is the origin doc's, byte for byte in intent:

    px_corr      = corr(dNet_c, same-week log return), full history
    gross_share  = mean over the last 52 weeks of (long_c + short_c) / total gross
    role         = RETAIL        if the cohort is nonreportable
                 = inert         if gross_share < 0.05
                 = SPEC          if px_corr >= +0.15
                 = COUNTERPARTY  if px_corr <= -0.15
                 = NEUTRAL       otherwise
    merge check  = cohorts sharing a role must have non-negative pairwise dNet correlation

Cohort legs come from `cotmetrics.categories` (the specs, `_resolve`, `_numeric`) so no
CFTC column name is re-spelled here, and positions come from `cotdata.get_cot`, which
stitches contract codes (the origin script read one parquet per code and dropped RTY's
predecessor). Net = long minus short, gross = long plus short, dNet = net.diff().

Stability, fixed before the run: rolling 156-week windows stepping 13 weeks, a window
counted only when at least 104 of its weeks carry a return and every cohort's dNet;
inside each window px_corr and gross_share (its own last 52 weeks) are recomputed and the
same thresholds applied. Reported per (report, symbol, cohort) as the fraction of windows
agreeing with the full-history role, and per (report, symbol) as the fraction of windows
whose COUNTERPARTY set equals the full-history COUNTERPARTY set
(`counterparty_set_stability`), with the SPEC set beside it.

Criterion, written before looking at any result: a market's measured roles are stable
enough to commit as data when `counterparty_set_stability >= 0.6` over at least 8 windows,
that is, the full-history counterparty set is reproduced on a clear majority of
three-year windows. A market failing this falls back to the per-report default in
`docs/design/cot-flows.md` section 3 (disagg: producer_merchant + swap; tff: dealer).
The counterparty set is the criterion because it is the only role the flow module reads
per symbol; the opinion triple stays the per-report default everywhere.

Usage (from the cotmetrics checkout):

    COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \\
      ../npf/.venv/bin/python scripts/analysis/cot_cohort_roles_propadj.py \\
        --params ../cotmetrics-config/params.yaml \\
        --universe docs/analysis/2026-09-26-cot-flow-states-universe.parquet \\
        --cowork-collapse docs/analysis/2026-09-26-cot-cohort-collapse.csv \\
        --out docs/analysis
"""

import argparse
import os
import time

import cotdata
import numpy as np
import pandas as pd
import yaml
from marketdata import get_bars

from cotmetrics import categories

THRESHOLD = 0.15
MIN_SHARE = 0.05
SHARE_WEEKS = 52
PRICE_TOL = pd.Timedelta("3D")
WINDOW = 156
STEP = 13
MIN_OBS = 104
STABLE_MIN = 0.6
MIN_WINDOWS = 8
DATE_TAG = "2026-09-26"

# Short labels matching the origin doc's tables, so the two collapse CSVs diff by eye.
SHORT = {
    "producer_merchant": "Prod",
    "swap": "Swap",
    "managed_money": "MM",
    "other_reportable": "Other",
    "nonreportable": "NonRep",
    "dealer": "Dealer",
    "asset_manager": "AssetMgr",
    "leveraged": "LevFund",
}
ROLE_SPEC, ROLE_CP, ROLE_NEUTRAL, ROLE_INERT, ROLE_RETAIL = (
    "SPEC", "COUNTERPARTY", "NEUTRAL", "inert", "RETAIL",
)


# --- loading ---------------------------------------------------------------------------

def load_universe(params_path):
    """[(asset_class, symbol)] from params.yaml, skipping Role: heldout."""
    with open(params_path) as fh:
        cfg = yaml.safe_load(fh)
    roles = cfg.get("roles") or {}
    default_role = roles.get("default", "deploy")
    out = []
    for block in cfg["AssetClasses"]:
        for klass, items in block.items():
            class_role = roles.get(klass, default_role)
            for it in items:
                if it.get("Role", class_role) == "heldout":
                    continue
                out.append((klass, it["Symbol"]))
    return out


def load_positions(symbol):
    """(report, raw): whichever of disagg / tff the store serves for this symbol."""
    for report in categories.REPORT_CHOICES:
        raw = cotdata.get_cot(symbol, report=report)
        if raw is not None and len(raw):
            return report, raw.sort_index()
    raise ValueError(f"{symbol}: no disagg or tff rows in the store")


def cohort_legs(raw, report):
    """(net, gross) frames keyed by category key, legs resolved through categories.py."""
    net, gross = {}, {}
    for spec in categories.categories_for(report):
        longs = categories._numeric(categories._resolve(raw, spec.long_col))
        shorts = categories._numeric(categories._resolve(raw, spec.short_col))
        if longs is None or shorts is None:
            continue
        net[spec.key] = longs - shorts
        gross[spec.key] = longs + shorts
    return pd.DataFrame(net), pd.DataFrame(gross)


def propadj_returns(symbol, report_dates):
    """Same-week log return on the ratio-adjusted tier, close reindexed to report dates."""
    close = get_bars(symbol, "propadj", domain="futures")["Close"].astype(float)
    close = close[close > 0].dropna().sort_index()
    p = close.reindex(report_dates, method="nearest", tolerance=PRICE_TOL)
    return np.log(p).diff()


def cache_returns(universe, symbol, report_dates):
    """The origin measurement's return: log diff of the parquet's cache close, positive only."""
    px = universe.loc[universe.symbol == symbol].set_index("date")["close"].astype(float)
    px = px[~px.index.duplicated()].sort_index()
    px = px.where(px > 0)
    return np.log(px).diff().reindex(report_dates)


# --- the rule --------------------------------------------------------------------------

def role_of(key, px_corr, gross_share):
    if key == "nonreportable":
        return ROLE_RETAIL
    if pd.isna(gross_share) or gross_share < MIN_SHARE:
        return ROLE_INERT
    if pd.isna(px_corr):
        return ROLE_NEUTRAL
    if px_corr >= THRESHOLD:
        return ROLE_SPEC
    if px_corr <= -THRESHOLD:
        return ROLE_CP
    return ROLE_NEUTRAL


def assign(dnet, gross, ret):
    """Per-cohort px_corr, gross_share and role over the rows given."""
    share = (gross.div(gross.sum(axis=1), axis=0)).iloc[-SHARE_WEEKS:].mean()
    out = {}
    for key in dnet.columns:
        corr = dnet[key].corr(ret)
        out[key] = dict(px_corr=corr, gross_share=float(share[key]),
                        role=role_of(key, corr, share[key]))
    return out


def merge_ok(cm, members):
    return all(cm.loc[a, b] >= 0 for i, a in enumerate(members) for b in members[i + 1:])


def collapse_row(report, symbol, roles, cm):
    """One market's collapse, in the origin CSV's shape plus the keys beside the labels."""
    keys = list(roles)
    by = {r: [k for k in keys if roles[k]["role"] == r]
          for r in (ROLE_SPEC, ROLE_CP, ROLE_NEUTRAL, ROLE_INERT, ROLE_RETAIL)}
    nonrep = roles.get("nonreportable", {}).get("px_corr", np.nan)
    retail = ("spec-like" if nonrep >= THRESHOLD else
              "cp-like" if nonrep <= -THRESHOLD else "neutral")
    row = dict(report=report, sym=symbol)
    for r in (ROLE_SPEC, ROLE_CP, ROLE_NEUTRAL, ROLE_INERT):
        row[r] = "+".join(SHORT[k] for k in by[r]) or "-"
    row.update(
        spec_merge_ok=merge_ok(cm, by[ROLE_SPEC]),
        cp_merge_ok=merge_ok(cm, by[ROLE_CP]),
        retail_behaves=retail,
        buckets=1 + sum(1 for r in (ROLE_SPEC, ROLE_CP, ROLE_NEUTRAL) if by[r]),
    )
    for r in (ROLE_SPEC, ROLE_CP, ROLE_NEUTRAL, ROLE_INERT, ROLE_RETAIL):
        row[f"{r}_keys"] = "+".join(by[r]) or "-"
    return row


# --- stability -------------------------------------------------------------------------

def rolling_roles(dnet, gross, ret):
    """[(window_end, {key: role})] over 156-week windows stepping 13, min 104 usable weeks."""
    usable = ret.notna() & dnet.notna().all(axis=1)
    out = []
    n = len(dnet)
    for start in range(0, n - WINDOW + 1, STEP):
        sl = slice(start, start + WINDOW)
        if int(usable.iloc[sl].sum()) < MIN_OBS:
            continue
        roles = assign(dnet.iloc[sl], gross.iloc[sl], ret.iloc[sl])
        out.append((dnet.index[start + WINDOW - 1], {k: v["role"] for k, v in roles.items()}))
    return out


def stability_rows(report, symbol, full, windows):
    """Per-cohort agreement and the per-market set stabilities, one row per cohort."""
    full_roles = {k: v["role"] for k, v in full.items()}
    n_win = len(windows)

    def set_stability(role):
        target = {k for k, r in full_roles.items() if r == role}
        hits = sum(1 for _, w in windows if {k for k, r in w.items() if r == role} == target)
        return hits / n_win if n_win else np.nan

    cp_stab = set_stability(ROLE_CP)
    spec_stab = set_stability(ROLE_SPEC)
    rows = []
    for key, role in full_roles.items():
        agree = sum(1 for _, w in windows if w[key] == role)
        dist = pd.Series([w[key] for _, w in windows]).value_counts()
        rows.append(dict(
            report=report, sym=symbol, cohort=SHORT[key], key=key, full_role=role,
            n_windows=n_win,
            agree_frac=round(agree / n_win, 3) if n_win else np.nan,
            window_roles=" ".join(f"{r}:{c}" for r, c in dist.items()),
            counterparty_set_stability=round(cp_stab, 3) if n_win else np.nan,
            spec_set_stability=round(spec_stab, 3) if n_win else np.nan,
            stable_enough=bool(n_win >= MIN_WINDOWS and cp_stab >= STABLE_MIN),
        ))
    return rows


# --- main ------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--params", required=True, help="cotmetrics-config/params.yaml")
    ap.add_argument("--universe", required=True,
                    help="2026-09-26-cot-flow-states-universe.parquet (its close is the cache close)")
    ap.add_argument("--cowork-collapse", required=True,
                    help="2026-09-26-cot-cohort-collapse.csv from the origin measurement")
    ap.add_argument("--out", required=True, help="directory for the three CSVs")
    args = ap.parse_args()
    t0 = time.time()

    universe = pd.read_parquet(args.universe)
    universe["date"] = pd.to_datetime(universe["date"])
    cowork = pd.read_csv(args.cowork_collapse).set_index(["report", "sym"])

    role_rows, collapse_rows, stab_rows, weeks_rows = [], [], [], []
    for klass, symbol in load_universe(args.params):
        report, raw = load_positions(symbol)
        raw = raw[~raw.index.duplicated()]
        net, gross = cohort_legs(raw, report)
        dnet = net.diff()
        ret = propadj_returns(symbol, dnet.index)
        ret_cache = cache_returns(universe, symbol, dnet.index)
        weeks_rows.append(dict(
            report=report, sym=symbol, asset_class=klass, n_weeks=len(dnet),
            usable_propadj=int((ret.notna() & dnet.notna().all(axis=1)).sum()),
            usable_cache=int((ret_cache.notna() & dnet.notna().all(axis=1)).sum()),
        ))

        full = assign(dnet, gross, ret)
        cm = dnet.corr()
        for key, v in full.items():
            role_rows.append(dict(
                report=report, sym=symbol, cohort=SHORT[key], key=key,
                px_corr=round(v["px_corr"], 3), gross_share=round(v["gross_share"], 3),
                role=v["role"],
                **{f"c_{SHORT[k]}": round(cm.loc[key, k], 3) for k in dnet.columns if k != key},
            ))
        collapse_rows.append(collapse_row(report, symbol, full, cm))
        stab_rows.extend(stability_rows(report, symbol, full, rolling_roles(dnet, gross, ret)))

    roles = pd.DataFrame(role_rows)
    collapse = pd.DataFrame(collapse_rows)
    stability = pd.DataFrame(stab_rows)
    weeks = pd.DataFrame(weeks_rows).set_index(["report", "sym"])
    collapse = collapse.merge(weeks[["usable_propadj", "usable_cache"]], left_on=["report", "sym"],
                              right_index=True)
    collapse = collapse.sort_values(["report", "sym"]).reset_index(drop=True)
    stability = stability.sort_values(["report", "sym"]).reset_index(drop=True)

    os.makedirs(args.out, exist_ok=True)
    roles.to_csv(os.path.join(args.out, f"{DATE_TAG}-cot-cohort-roles-propadj.csv"), index=False)
    collapse.to_csv(os.path.join(args.out, f"{DATE_TAG}-cot-cohort-collapse-propadj.csv"),
                    index=False)
    stability.to_csv(os.path.join(args.out, f"{DATE_TAG}-cot-cohort-roles-stability.csv"),
                     index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print("== usable weeks for the same-week correlation, propadj beside the cache close ==")
    print(weeks.sort_values("usable_cache").to_string())

    print("\n== collapse on propadj (threshold 0.15, inert below 5% of gross) ==")
    print(collapse.drop(columns=[c for c in collapse.columns if c.endswith("_keys")])
          .to_string(index=False))
    print("\nbucket count distribution:", collapse.buckets.value_counts().to_dict())
    print("retail behaves:", collapse.retail_behaves.value_counts().to_dict())

    print("\n== assignments that changed against the cache-close measurement ==")
    changed = []
    for _, r in collapse.iterrows():
        k = (r.report, r.sym)
        if k not in cowork.index:
            changed.append(f"{r.report} {r.sym}: not in the origin table (new on propadj)")
            continue
        old = cowork.loc[k]
        diffs = []
        for col in (ROLE_SPEC, ROLE_CP, ROLE_NEUTRAL, ROLE_INERT):
            a = set(str(old[col]).split("+")) - {"-"}
            b = set(str(r[col]).split("+")) - {"-"}
            if a != b:
                diffs.append(f"{col} {old[col]} -> {r[col]}")
        if diffs:
            changed.append(f"{r.report} {r.sym}: " + "; ".join(diffs))
    print("\n".join(changed) if changed else "none")
    print(f"\n{len(changed)} of {len(collapse)} markets changed at least one bucket")

    print(f"\n== stability: {WINDOW}-week windows every {STEP} weeks, min {MIN_OBS} usable ==")
    per_sym = (stability.groupby(["report", "sym"])
               [["n_windows", "counterparty_set_stability", "spec_set_stability", "stable_enough"]]
               .first())
    print(per_sym.to_string())
    print("\nper-cohort agreement with the full-history role:")
    print(stability[["report", "sym", "cohort", "full_role", "agree_frac", "window_roles"]]
          .to_string(index=False))
    print("\nmedian counterparty_set_stability:",
          round(per_sym.counterparty_set_stability.median(), 3),
          " median spec_set_stability:", round(per_sym.spec_set_stability.median(), 3),
          " median per-cohort agree_frac:", round(stability.agree_frac.median(), 3))
    failing = per_sym[~per_sym.stable_enough]
    print(f"\ncriterion: counterparty_set_stability >= {STABLE_MIN} over >= {MIN_WINDOWS} windows")
    print(f"failing ({len(failing)} of {len(per_sym)}):",
          ", ".join(f"{s} ({v:.2f})" for (_, s), v in
                    failing.counterparty_set_stability.items()) or "none")
    print(f"\nelapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
