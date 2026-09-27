"""Weekly flow of a COT leg: its net change each report week, scaled by its own history.

What the /analysis Positioning Index panel draws under its lines: the Legacy
Commercial leg's week-over-week net change divided by the rolling 52-week standard
deviation of those changes (`CotIndexer.get_commercial_flow_data`). Commercial because
every setup in the app is triggered by the Commercial index at an extreme, and on
equities it is the only leg the gate reads (`utils.is_setup`).

The design record is `docs/design/cot-flows.md`: the work began as a per-cohort flow
study on gold, went through several displays that were built and withdrawn (a
cohort-by-week heatmap, flow-state names, a speculator series), and ended on this one
strip. `cotmetrics.flow_roles`, the measured per-market cohort roles, survives for the
panel's retail label.

Pure: imports numpy, pandas and constants only, so it runs against the empty store CI
uses. Three choices a reader will otherwise rediscover as bugs:

* The window is FIXED at `const.FLOW_Z_WEEKS` and is not the page lookback.
  params.yaml sets the Custom lookback to 8 weeks on OJ and 216 on PA; a z against 8
  weeks of flow history is noise and one against 216 is a different quantity. The
  window rides in the column name ("Comm Flow Z 52w").
* No mean subtraction. Weekly net changes have no level to remove: the z says how big
  this week's move is against the leg's usual move, and subtracting a rolling mean
  would turn a steady one-direction accumulation into a string of zeros. So
  `indicators.calculate_z_score` is not reused.
* NaN, never 0, under `min_periods`, on a zero-sd window, across a missed report week
  and across a contract-code switch (LBR's 2023 stitch alternates codes over three
  weeks and prints flows of several sd on nothing). 0 would read as a quiet week.

Nothing here carries a forward return or a verdict. The pre-registered test of the
flow-state idea failed the crucible gauntlet on 2026-09-26, single-cohort weekly moves
were a genuine null on 42 markets, and no signal, condition, model or synthesis reads
these columns.
"""

import numpy as np
import pandas as pd

import cotmetrics.constants as const

# --- column names -----------------------------------------------------------------
# The view never spells one itself.

def flow_col(prefix):
    return prefix + const.FLOW


def flow_z_col(prefix):
    return prefix + const.FLOW_Z + f" {const.FLOW_Z_WEEKS}w"


# --- the primitive ----------------------------------------------------------------

def weekly_change(series, *, max_gap_days=const.FLOW_MAX_GAP_DAYS, source_code=None):
    """`series.diff()`, NaN across a missed report week and a contract-code switch.

    `max_gap_days` masks a row more than that many days after the prior row (None
    turns it off; a non-datetime index skips it, having no gap to measure).
    `source_code` is aligned to the index (const.SOURCE_CODE from the category
    frame); a row whose code differs from the prior row's is masked.
    """
    out = series.diff()
    n = len(out)
    if n == 0:
        return out
    mask = np.zeros(n, dtype=bool)
    if max_gap_days is not None and isinstance(series.index, pd.DatetimeIndex):
        gap_days = series.index.to_series().diff().dt.days.to_numpy()
        mask |= gap_days > max_gap_days
    if source_code is not None:
        code = (source_code.reindex(series.index) if isinstance(source_code, pd.Series)
                else pd.Series(source_code, index=series.index)).astype(object)
        changed = code.to_numpy() != code.shift().to_numpy()
        changed[0] = False
        mask |= changed
    if mask.any():
        out = out.copy()
        out.iloc[mask] = np.nan
    return out


def flow_z(series, window=const.FLOW_Z_WEEKS, min_periods=const.FLOW_Z_MIN_PERIODS):
    """`series / rolling sd`, NaN under min_periods and on a zero-sd window.

    `series` is a weekly change (from `weekly_change`). The rolling sd counts non-NaN
    observations, so a masked week thins the window for the next `window` rows rather
    than poisoning it.
    """
    sd = series.rolling(window, min_periods=min_periods).std()
    return series / sd.where(sd > 0)


# --- a leg's flow ----------------------------------------------------------------------

def leg_flow_frame(net, prefix, source_code=None):
    """One leg's weekly flow: "<prefix> dNet" and "<prefix> Flow Z 52w" on `net`'s index.

    `net` is a net-contracts Series indexed by report date (a Legacy leg, for the
    /analysis Positioning Index strip). `source_code` is aligned to it and masks
    contract-population switches as in `weekly_change`.
    """
    out = pd.DataFrame(index=net.index)
    out[flow_col(prefix)] = weekly_change(net, source_code=source_code)
    out[flow_z_col(prefix)] = flow_z(out[flow_col(prefix)])
    return out

