"""COT flow states on the ADR-0005 universe, judged by crucible: does the gold VALUE_ACCUM
lean travel?

Design frozen in docs/analysis/2026-09-26-cot-flow-states-cross-universe.md (committed
before the first run). State derivation is imported unchanged from
cot_flow_states_universe.py, which is itself the gold design generalised to TFF roles.

What this adds over the descriptive universe pass:
  - ADR-0005 scope only: physical commodities (Disaggregated) and currencies (TFF)
  - prices from MARKETDATA_STORE (propadj futures), entry at the Friday release
  - non-overlapping, vol-normalised, causally drift-removed trades in a crucible TradeLog
  - crucible holdout (2019-01-01, 8w embargo) and run_gauntlet with n_variants = the log

The SearchSpaceLog is rebuilt on every run from the committed seed (the prior universe
pass, 44 entries) plus this run's variants, so a re-run does not inflate the count.

Usage (from the workspace root):
  COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \\
  npf/.venv/bin/python cotmetrics/scripts/analysis/cot_flow_states_cross_universe.py \\
      --params cotmetrics-config/params.yaml --out cotmetrics/docs/analysis
"""

import argparse
import json
import os
import shutil
import sys
import time

import numpy as np
import pandas as pd
from crucible.edge.trade_log import TradeLog
from crucible.validation import (
    SearchSpaceLog,
    holdout,
    run_gauntlet,
    sidak_correction,
    sign_permutation_pvalue,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cot_flow_states_universe as u  # noqa: E402

PREFIX = "2026-09-26-cot-flow-states-cross-universe"
SCOPE = u.SCOPE  # same scope as the prior universe pass, so its looks are counted
SCOPE_CLASSES = {"Metals": "commodity", "Energies": "commodity", "Grains": "commodity",
                 "Softs": "commodity", "Live Stock": "commodity", "Currencies": "currency"}
HORIZONS = (13, 4)
SPLIT, EMBARGO, SEED = "2019-01-01", 8, 0
VOL_WIN, VOL_MIN, DRIFT_MIN = 260, 120, 52
PRIMARY = ("VALUE_ACCUM", 1, 13)
DESIGN = dict(split=SPLIT, embargo_weeks=EMBARGO, seed=SEED, vol_win=VOL_WIN, vol_min=VOL_MIN,
              drift_min=DRIFT_MIN, price="marketdata propadj futures Close",
              entry="first close >= report_date + 3d", exit="first close >= entry + h weeks",
              r="dir * (log(exit/entry)/(sd_daily_260 * sqrt(sessions)) - causal drift)",
              overlap="non-overlapping within market", **{k: v for k, v in u.CONFIG.items()
                                                         if k not in ("price_source",)})


def market_trades(frame, close, horizons):
    """Per report week: entry/exit dates, vol-normalised long return and causal drift."""
    close = close[close > 0].dropna().sort_index()
    idx, px = close.index, close.to_numpy(float)
    lr = np.diff(np.log(px), prepend=np.nan)
    sd = pd.Series(lr).rolling(VOL_WIN, min_periods=VOL_MIN).std().shift(1).to_numpy()
    anchors = pd.DatetimeIndex(frame.index) + u.RELEASE_LAG
    ia = idx.searchsorted(anchors, side="left")
    ok_a = ia < len(idx)
    ia_c = np.minimum(ia, len(idx) - 1)
    ok_a &= (idx[ia_c] - anchors) <= pd.Timedelta("7D")
    out = pd.DataFrame(index=frame.index)
    out["state"] = frame["state"].to_numpy()
    for h in horizons:
        ie = idx.searchsorted(idx[ia_c] + pd.Timedelta(weeks=h), side="left")
        ok = ok_a & (ie < len(idx)) & np.isfinite(sd[ia_c])
        ie_c = np.minimum(ie, len(idx) - 1)
        held = (ie_c - ia_c).astype(float)
        r = np.log(px[ie_c] / px[ia_c]) / (sd[ia_c] * np.sqrt(np.maximum(held, 1)))
        r = np.where(ok, r, np.nan)
        entry = np.where(ok, idx[ia_c].to_numpy(), np.datetime64("NaT"))
        exit_ = np.where(ok, idx[ie_c].to_numpy(), np.datetime64("NaT"))
        # causal drift: mean r over anchors whose trade exited strictly before this entry
        valid = np.isfinite(r)
        ex_sorted = np.sort(exit_[valid])
        order = np.argsort(exit_[valid], kind="stable")
        csum = np.concatenate([[0.0], np.cumsum(r[valid][order])])
        k = np.searchsorted(ex_sorted, entry, side="left")
        drift = np.where(k >= DRIFT_MIN, csum[k] / np.maximum(k, 1), np.nan)
        out[f"entry{h}"], out[f"exit{h}"] = entry, exit_
        out[f"held{h}"], out[f"r{h}"], out[f"drift{h}"] = held, r, np.where(ok, drift, np.nan)
    return out


def book(tr, state, direction, h):
    """Non-overlapping trades for one (state, direction, h), all markets."""
    rows = []
    for sym, g in tr.groupby("symbol", sort=False):
        c = g[(g["state"] == state) & g[f"r{h}"].notna() & g[f"drift{h}"].notna()]
        last_exit = pd.Timestamp.min
        for _, row in c.iterrows():
            if row[f"entry{h}"] < last_exit:
                continue
            last_exit = row[f"exit{h}"]
            rows.append(dict(symbol=sym, asset_class=row["asset_class"], group=row["group"],
                             entry_date=row[f"entry{h}"], exit_date=row[f"exit{h}"],
                             bars_held=row[f"held{h}"],
                             r_raw=direction * row[f"r{h}"],
                             r=direction * (row[f"r{h}"] - row[f"drift{h}"])))
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["symbol", "asset_class", "group", "entry_date", "exit_date",
                                   "bars_held", "r_raw", "r"])
    return df.sort_values("entry_date").reset_index(drop=True)


def summarise(df):
    r = df["r"].astype(float)
    if len(r) < 3:
        return dict(n=int(len(r)), E=float(r.mean()) if len(r) else np.nan)
    return dict(n=int(len(r)), E=float(r.mean()), E_raw=float(df["r_raw"].mean()),
                hit=float((r > 0).mean() * 100), t=float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))),
                markets=int(df["symbol"].nunique()))


def split_read(df, n_var):
    """Holdout verdict plus a Sidak-corrected TEST sign-permutation p at the final count."""
    tl = TradeLog.from_frame(df)
    ho = holdout(tl, SPLIT, embargo_weeks=EMBARGO, seed=SEED)
    test = df[pd.to_datetime(df["entry_date"]) >= pd.Timestamp(SPLIT) + pd.Timedelta(weeks=EMBARGO)]
    p_raw = sign_permutation_pvalue(test["r"].to_numpy(float), seed=SEED) if len(test) > 2 else np.nan
    return ho, dict(train_n=ho.train_n, train_E=ho.train.point, test_n=ho.test_n,
                    test_E=ho.test.point, test_ci=[ho.test.ci.low, ho.test.ci.high],
                    test_label=ho.test.label, test_p_raw=p_raw,
                    test_p_sidak=sidak_correction(p_raw, n_var) if np.isfinite(p_raw) else np.nan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    from marketdata import get_bars

    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
    log_path = os.path.join(a.out, f"{PREFIX}.searchlog.jsonl")
    shutil.copyfile(os.path.join(a.out, f"{PREFIX}.searchlog.seed.jsonl"), log_path)
    log = SearchSpaceLog(scope=SCOPE, path=log_path)
    print(f"seeded SearchSpaceLog with {log.n_variants} prior entries")

    universe = [x for x in u.load_universe(a.params) if x[0] in SCOPE_CLASSES]
    print(f"universe: {len(universe)} markets in ADR-0005 scope")
    parts, skipped = [], []
    for klass, sym, _ in universe:
        try:
            report, raw = u.load_positions(sym)
            fr = u.derive(raw, report)
            close = get_bars(sym, "propadj", domain="futures")["Close"].astype(float)
            tr = market_trades(fr, close, HORIZONS)
        except Exception as exc:  # noqa: BLE001
            skipped.append(dict(symbol=sym, reason=f"{type(exc).__name__}: {exc}"))
            print(f"SKIP {sym}: {exc}")
            continue
        tr["symbol"], tr["asset_class"], tr["group"], tr["report"] = sym, klass, SCOPE_CLASSES[klass], report
        parts.append(tr.reset_index())
    tr = pd.concat(parts, ignore_index=True)
    print(f"loaded {tr['symbol'].nunique()} markets, {len(tr)} market-weeks "
          f"({tr['r13'].notna().sum()} with r13, {tr['drift13'].notna().sum()} with drift)\n")

    # ---- enumerate every variant this run scores, log them all BEFORE computing verdicts
    variants = []  # (name, state, direction, h, subset)
    variants.append(("primary", *PRIMARY, "all"))
    variants += [("class", "VALUE_ACCUM", 1, 13, g) for g in ("commodity", "currency")]
    variants.append(("gold", "VALUE_ACCUM", 1, 13, "GC"))
    for h in HORIZONS:
        for st in u.STATE_NAMES.values():
            if (st, h) != ("VALUE_ACCUM", 13):
                variants.append(("secondary", st, None, h, "all"))
    for kind, st, d, h, sub in variants:
        log.record(dict(study="cross_universe", kind=kind, state=st, direction=d, h=h,
                        subset=sub, **DESIGN), status="tried")
    n_var = log.n_variants
    print(f"SearchSpaceLog n_variants = {n_var} (prior {n_var - log.session_n_variants}, "
          f"this run {log.session_n_variants})\n")

    def subset(df, sub):
        if sub == "all":
            return df
        if sub in ("commodity", "currency"):
            return df[df["group"] == sub]
        return df[df["symbol"] == sub]

    # ---- sanity: unconditional non-overlapping long book should sit near zero after drift
    base = {}
    for h in HORIZONS:
        base[h] = summarise(book(tr.assign(state="ANY"), "ANY", 1, h))
        print(f"unconditional long, h={h}: {base[h]}")
    print()

    results = []
    primary_book = None
    for kind, st, d, h, sub in variants:
        if d is None:  # secondary: direction from the TRAIN-period long mean
            probe = book(tr, st, 1, h)
            tr_rows = probe[(pd.to_datetime(probe["exit_date"]) < pd.Timestamp(SPLIT))]
            d = 1 if (len(tr_rows) == 0 or tr_rows["r"].mean() >= 0) else -1
        df = subset(book(tr, st, d, h), sub)
        row = dict(kind=kind, state=st, direction=d, h=h, subset=sub, **summarise(df))
        if len(df) >= 6:
            ho, sr = split_read(df, n_var)
            row.update(sr)
        results.append(row)
        if kind == "primary":
            primary_book = df
    res = pd.DataFrame(results)
    cols = ["kind", "state", "direction", "h", "subset", "n", "markets", "E", "E_raw", "hit", "t",
            "train_n", "train_E", "test_n", "test_E", "test_label", "test_p_raw", "test_p_sidak"]
    print(res[[c for c in cols if c in res]].to_string(index=False))
    print()

    # ---- primary: full holdout print, gauntlet, per-market spread
    tl = TradeLog.from_frame(primary_book)
    ho = holdout(tl, SPLIT, embargo_weeks=EMBARGO, seed=SEED)
    print(ho, "\n")
    per_mkt = {s: TradeLog.from_frame(g.reset_index(drop=True))
               for s, g in primary_book.groupby("symbol") if len(g) >= 3}
    gz = run_gauntlet(tl, trade_logs=per_mkt, n_variants=log)
    print(gz.audit_report() if hasattr(gz, "audit_report") else gz, "\n")
    pm = primary_book.groupby("symbol").agg(asset_class=("asset_class", "first"), n=("r", "size"),
                                            E=("r", "mean"), E_raw=("r_raw", "mean"))
    elig = pm[pm["n"] >= 5]
    print(pm.sort_values("E").to_string())
    print(f"\nsign count (n>=5): {int((elig['E'] > 0).sum())} of {len(elig)} markets positive\n")

    tr.to_parquet(os.path.join(a.out, f"{PREFIX}.parquet"), index=False)
    summary = dict(generated=pd.Timestamp.now().isoformat(timespec="seconds"), design=DESIGN,
                   universe=[dict(asset_class=k, symbol=s) for k, s, _ in universe],
                   skipped=skipped, unconditional=base,
                   results=json.loads(res.to_json(orient="records")),
                   primary_holdout=str(ho), primary_gauntlet=gz.to_dict(),
                   primary_per_market=json.loads(pm.reset_index().to_json(orient="records")),
                   sign_count=dict(positive=int((elig["E"] > 0).sum()), eligible=int(len(elig))),
                   search_log=dict(path=os.path.basename(log_path), n_variants=n_var,
                                   session_n_variants=log.session_n_variants))
    with open(os.path.join(a.out, f"{PREFIX}.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
