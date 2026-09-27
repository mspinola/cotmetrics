"""One role series per market: the speculator net, the retail net, and a weekly flow z.

The display the COT flow work ended on ("Scope, restated v2" in
`docs/handoffs/2026-09-26-cot-flow-states-cross-universe.md`): per market, the net
position of the cohorts measured to act as the speculator, its positioning index, and
one strip of its week-over-week flow scaled by its own history. Which cohorts form the
speculator is data, not code: `cotmetrics.flow_roles`, generated from the propadj
cohort-role measurement, keyed by (report, symbol) with a per-report default.

Why one series: every long is somebody's short, so across all cohorts the weekly net
changes sum to zero, and the counterparty's net is the mirror of the speculator's plus
whatever the neutral cohorts did. Drawing both repeats one line. Neutral cohorts, by
the rule that labels them, do not move with price, which is what the panel is read
against.

Deliberately pure, like `categories`: everything here takes the OUTPUT of
`categories.build_category_frame`, so the Swap_/Swap__ resolution, dtype coercion and
`present_categories` are inherited. Imports numpy, pandas, constants, categories,
indicators and the generated `flow_roles` table, nothing else, so it runs against the
empty store CI uses.

Three choices a reader will otherwise rediscover as bugs:

* The flow window is FIXED at `const.FLOW_Z_WEEKS` and is not the page lookback.
  params.yaml sets the Custom lookback to 8 weeks on OJ and 216 on PA; a z against 8
  weeks of flow history is noise and one against 216 is a different quantity. The
  window rides in the column name ("Speculator Flow Z 52w").
* No mean subtraction. Weekly net changes have no level to remove: the z says how big
  this week's move is against this series' usual move, and subtracting a rolling mean
  would turn a steady one-direction accumulation into a string of zeros. So
  `indicators.calculate_z_score` is not reused.
* NaN, never 0, under `min_periods`, on a zero-sd window, across a missed report week
  and across a contract-code switch (LBR's 2023 stitch alternates codes over three
  weeks and prints managed-money z of -3.7 then +3.3 on nothing). 0 would read as a
  quiet week.

Nothing here carries a forward return or a verdict. The pre-registered test of the
flow-state idea failed the crucible gauntlet on 2026-09-26, and no signal, condition,
model or synthesis reads these columns.
"""

import numpy as np
import pandas as pd

import cotmetrics.categories as categories
import cotmetrics.constants as const
import cotmetrics.flow_roles as flow_roles
import cotmetrics.indicators as indicators

# --- column names -----------------------------------------------------------------
# The view never spells one itself.

def net_col(prefix):
    return prefix + const.NET_SUFFIX


def flow_col(prefix):
    return prefix + const.FLOW


def flow_z_col(prefix):
    return prefix + const.FLOW_Z + f" {const.FLOW_Z_WEEKS}w"


def index_col(prefix, lookback_header):
    return prefix + lookback_header + const.IDX


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


# --- the resolvers ------------------------------------------------------------------

def _summed_net(category_frame, report, keys):
    by_key = {s.key: s for s in categories.present_categories(category_frame, report)}
    if not keys or any(k not in by_key for k in keys):
        return None
    return sum(category_frame[categories.net_col(by_key[k])] for k in keys)


def speculator_net(category_frame, report, symbol=None):
    """Net contracts of the cohorts `flow_roles` names as this market's speculator.

    None where the table names no speculator (the view falls back to Legacy
    Non-Commercial) or where a named cohort is missing from the frame: a partial sum
    would be a different series under the same name.
    """
    roles = flow_roles.roles_for(report, symbol)
    return _summed_net(category_frame, report, roles.speculator)


def retail_net(category_frame, report):
    """Net contracts of Non-Reportable, the same key on both reports. None if absent."""
    return _summed_net(category_frame, report, ("nonreportable",))


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


def speculator_frame(category_frame, report, symbol=None):
    """The columns the Positioning Index panel draws, on the category frame's index.

    "Speculator Net", "Speculator<header> Idx" (the range index at the frame's page
    lookback, window lookback + 1 as in build_category_frame), "Speculator dNet" and
    "Speculator Flow Z 52w", and "Retail Net". The speculator columns are absent where
    `speculator_net` is None. attrs: "flow_roles" (the table entry as a dict),
    "speculator_label", "lookback_header", "lookback_weeks".
    """
    roles = flow_roles.roles_for(report, symbol)
    header = category_frame.attrs.get("lookback_header")
    weeks = category_frame.attrs.get("lookback_weeks")
    source = (category_frame[const.SOURCE_CODE]
              if const.SOURCE_CODE in category_frame.columns else None)

    out = pd.DataFrame(index=category_frame.index)
    spec = speculator_net(category_frame, report, symbol)
    if spec is not None:
        p = const.SPECULATOR
        out[net_col(p)] = spec
        if header is not None and weeks:
            span = int(weeks) + 1
            out[index_col(p, header)] = indicators.calculate_range_index(
                spec, window=span, min_periods=span)
        out[flow_col(p)] = weekly_change(spec, source_code=source)
        out[flow_z_col(p)] = flow_z(out[flow_col(p)])
    retail = retail_net(category_frame, report)
    if retail is not None:
        out[net_col(const.RETAIL)] = retail

    labels = {s.key: s.label for s in categories.categories_for(report)}
    out.attrs["flow_roles"] = roles.as_dict()
    out.attrs["speculator_label"] = (
        " + ".join(labels.get(k, k) for k in roles.speculator)
        if spec is not None else None)
    out.attrs["lookback_header"] = header
    out.attrs["lookback_weeks"] = weeks
    return out
