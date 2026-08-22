"""Audit: does any market's contract definition change inside its PRICED window?

Reproducer for docs/analysis/2026-08-22-effective-dated-contract-multipliers.md.

`marketdata.store.read_metadata()` carries ONE `Point Value` per symbol with no
effective date, and `cotmetrics.exposure.point_values()` applies it to a market's
entire COT history. Wherever a contract was re-denominated mid-history that multiplier
is wrong for every week before the change.

Two signals are available in the store, and the audit runs both because neither is
sufficient on its own:

  names  `Market_and_Exchange_Names` per week. Cheap, but very noisy: 72% of the
         boundaries it produces are CFTC-wide relabel dates shared by many markets at
         once, and it MISSES a re-denomination that came with no rename (which is what
         actually happened to the Russell).

  scale  a one-week event in which every REPORTABLE position column scales by the same
         factor. That is what a re-denomination looks like in the data, because the
         clearing house rewrites open lots. Non-reportable columns are deliberately
         excluded: the reporting threshold is a lot count, so it does not scale with the
         contract, and traders cross it when lots are rewritten.

         The screen's false positives are quarterly expiry weeks, where index and
         currency open interest collapses uniformly across buckets and then rebuilds.
         Two independent tests separate them, and the audit reports both. Proximity to a
         quarterly third Friday is the cheap one. PERSISTENCE is the principled one: a
         re-denomination rewrites open lots and never reverts, while an expiry sawtooth
         returns to its prior level within a quarter.

Run (cotmetrics has no venv by design; see the workspace CLAUDE.md):

    COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \
    COTMETRICS_PARAMS=../cotmetrics-config/params.yaml COTMETRICS_CACHE=~/code/cotmetrics_cache \
      ../npf/.venv/bin/python scripts/analysis/audit_contract_regimes.py
"""
import cotdata
import numpy as np
import pandas as pd

from cotmetrics import exposure
from cotmetrics.indexer import get_indexer

#: The reportable buckets. See the module docstring for why non-reportable is excluded.
REPORTABLE = ("Open_Interest_All",
              "NonComm_Positions_Long_All", "NonComm_Positions_Short_All",
              "Comm_Positions_Long_All", "Comm_Positions_Short_All")

#: A re-denomination moves every reportable column by one factor. Allow 30% spread
#: between the largest and smallest column ratio: a real conversion still lands on a
#: week of ordinary trading, and traders cross the reporting threshold as lots are
#: rewritten, so the columns do not agree to the digit.
MAX_COLUMN_SPREAD = 0.30

#: Below this the week is ordinary trading rather than a re-denomination.
MIN_STEP = 1.5

#: Ignore weeks whose prior positions are too small for a ratio to mean anything.
MIN_LOTS = 200

#: Quarterly expiry window, in days either side of the third Friday of Mar/Jun/Sep/Dec.
#: 14 of the 16 events sit inside 4 days; this catches the collapse but not the rebuild
#: a week later, which is why persistence is tested too.
EXPIRY_DAYS = 5

#: Weeks either side over which a real re-denomination must hold. Half a year: long
#: enough that a quarterly sawtooth has completed a full cycle and reverted.
PERSIST_WEEKS = 26

#: How far the 26-week step may differ from the one-week step, in log space, and still
#: count as having held. 0.25 is a factor of 1.28 either way. An expiry sawtooth reverts
#: most of the way and lands outside it; the Russell conversion lands at 0.06.
PERSIST_TOLERANCE = 0.25


def _weekly(symbol: str) -> pd.DataFrame:
    """A symbol's stitched COT history, indexed in ns so `_asof` can merge on it."""
    hist = cotdata.get_cot(symbol).sort_index()
    if hist.empty:
        return hist
    # Parquet hands back datetime64[us]; merge_asof needs both sides in the same unit.
    hist.index = pd.DatetimeIndex(hist.index).astype("datetime64[ns]")
    return hist


def name_runs(hist: pd.DataFrame) -> pd.DataFrame:
    """Collapse the weekly name column into contiguous runs."""
    key = (hist["Market_and_Exchange_Names"].astype(str) + "|"
           + hist["CFTC_Contract_Market_Code"].astype(str))
    rows = []
    for _, block in hist.groupby((key != key.shift()).cumsum()):
        rows.append({"name": str(block["Market_and_Exchange_Names"].iloc[0]),
                     "code": str(block["CFTC_Contract_Market_Code"].iloc[0]),
                     "first": block.index.min(), "last": block.index.max(),
                     "weeks": len(block)})
    return pd.DataFrame(rows)


def near_quarterly_expiry(date: pd.Timestamp, days: int = EXPIRY_DAYS) -> bool:
    """Is this week within `days` of the third Friday of a quarterly month?"""
    if date.month not in (3, 6, 9, 12):
        return False
    month = pd.date_range(date.replace(day=1), periods=31, freq="D")
    fridays = [d for d in month if d.month == date.month and d.dayofweek == 4]
    return abs((date - fridays[2]).days) <= days


def scale_events(hist: pd.DataFrame) -> pd.DataFrame:
    """Weeks where every reportable column moved by ~one factor."""
    cols = [c for c in REPORTABLE if c in hist.columns]
    pos = hist[cols].apply(pd.to_numeric, errors="coerce")
    ratios = pos / pos.shift(1)
    k = ratios.median(axis=1)
    spread = (ratios.max(axis=1) - ratios.min(axis=1)) / k
    hit = ((pos.shift(1) >= MIN_LOTS).all(axis=1)
           & (np.abs(np.log(k)) > np.log(MIN_STEP))
           & (spread < MAX_COLUMN_SPREAD)).fillna(False)

    # Did the step hold? Compare half a year either side, on open interest.
    oi = pos["Open_Interest_All"]
    before = oi.shift(1).rolling(PERSIST_WEEKS).median()
    after = oi[::-1].rolling(PERSIST_WEEKS).median()[::-1]
    held = after / before

    return pd.DataFrame({"date": k.index[hit], "k": k[hit].to_numpy(),
                         "spread": spread[hit].to_numpy(),
                         "held": held[hit].to_numpy()})


def main() -> int:
    ix = get_indexer()
    pvs = exposure.point_values()

    inventory, boundaries, events = [], [], []
    for inst in sorted(ix.instruments.values(), key=lambda i: i.symbol):
        hist = _weekly(inst.symbol)
        if hist.empty:
            continue
        runs = name_runs(hist)

        priced = pd.Series(False, index=hist.index)
        if inst.symbol in pvs:
            carried = exposure._asof(exposure.price_levels(inst.symbol), hist.index,
                                     exposure.DEFAULT_MAX_STALENESS_DAYS)
            priced = carried.notna()
        first_priced = hist.index[priced.to_numpy()].min() if priced.any() else None

        inventory.append({"symbol": inst.symbol, "class": inst.asset_class,
                          "cot_first": hist.index.min().date(),
                          "first_priced": first_priced.date() if first_priced is not None else None,
                          "priced_weeks": int(priced.sum()), "name_runs": len(runs),
                          "point_value": pvs.get(inst.symbol)})

        for i, run in runs.iloc[1:].iterrows():
            after = int((priced.to_numpy() & (hist.index >= run["first"])).sum())
            boundaries.append({"symbol": inst.symbol, "date": run["first"].date(),
                               "prev": runs.iloc[i - 1]["name"], "name": run["name"],
                               "code": run["code"],
                               "inside_priced": first_priced is not None and run["first"] > first_priced,
                               "priced_before": int(priced.sum()) - after,
                               "priced_after": after})

        for _, ev in scale_events(hist).iterrows():
            k, held = float(ev["k"]), float(ev["held"])
            persisted = np.isfinite(held) and abs(np.log(held / k)) < PERSIST_TOLERANCE
            events.append({"symbol": inst.symbol, "date": ev["date"].date(),
                           "k": round(k, 3), "spread": round(float(ev["spread"]), 3),
                           "held_26wk": round(held, 3) if np.isfinite(held) else None,
                           "near_expiry": near_quarterly_expiry(ev["date"]),
                           "persisted": bool(persisted)})

    inv = pd.DataFrame(inventory)
    bnd = pd.DataFrame(boundaries)
    evt = pd.DataFrame(events)

    pd.set_option("display.width", 200)
    print("=" * 78)
    print("1. INVENTORY: COT history, priced window and name runs per market")
    print("=" * 78)
    print(inv.to_string(index=False))

    print()
    print("=" * 78)
    print("2. NAME BOUNDARIES")
    print("=" * 78)
    shared = bnd["date"].value_counts()
    shared = set(shared[shared >= 3].index)
    print(f"{len(bnd)} boundaries across {len(inv)} markets; "
          f"{int(bnd['date'].isin(shared).sum())} sit on a date shared by >=3 markets "
          f"(a CFTC-wide relabel, not a contract event).")
    print("\nIdiosyncratic boundaries INSIDE a priced window:")
    idio = bnd[~bnd["date"].isin(shared) & bnd["inside_priced"]]
    print(idio.sort_values("priced_before", ascending=False).to_string(index=False))

    print()
    print("=" * 78)
    print("3. UNIFORM ONE-WEEK SCALE EVENTS (the re-denomination signature)")
    print("=" * 78)
    print(evt.sort_values("date").to_string(index=False))
    print(f"\n{len(evt)} events. {int(evt['near_expiry'].sum())} sit within "
          f"{EXPIRY_DAYS} days of a quarterly third Friday; "
          f"{int((~evt['persisted']).sum())} had reverted {PERSIST_WEEKS} weeks later.")
    real = evt[evt["persisted"] & ~evt["near_expiry"]]
    print("\nSurvives BOTH tests, i.e. a candidate re-denomination:")
    print(real.to_string(index=False) if len(real) else "  (none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
