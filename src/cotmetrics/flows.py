"""Week-over-week cohort flows for the Disaggregated and TFF reports.

The primitive from `docs/analysis/2026-09-26-cot-flow-states-gold.md`, restated as a
column family: for each trader category, the change in net position since the prior
report (dNet), the same for each leg (dLong, dShort), and dNet divided by its own
rolling standard deviation (Flow Z), which is what makes a week's move comparable
across cohorts and markets. Plus one per-market counterparty composite, a thin flag,
and the sign vocabulary the gold study read its heatmap with.

Deliberately pure, like `categories`: it takes the OUTPUT of
`categories.build_category_frame` (so the Swap_/Swap__ resolution, dtype coercion,
skipped categories and `present_categories` are inherited) and returns only new
columns on the same index. Imports numpy, pandas, constants, categories and the
generated `flow_roles` table, nothing else, so it runs against the empty store CI uses.

Four choices a reader will otherwise rediscover as bugs:

* The window is FIXED at `const.FLOW_Z_WEEKS` and is not the page lookback. params.yaml
  sets the Custom lookback to 8 weeks on OJ and 216 on PA. A z against 8 weeks of
  flow history is noise and one against 216 is a different quantity. The window rides
  in the column name ("Managed Money Flow Z 52w") so it cannot be mistaken for the
  " 26" / " 52" / " Custom" infix that `index_col` and `zscore_col` carry.
* No mean subtraction. Weekly net changes have no level to remove: the question the
  z answers is "how big is this week's move against this cohort's usual move", and
  subtracting a rolling mean would turn a steady one-direction accumulation into a
  string of zeros. `indicators.calculate_z_score` is therefore not reused, and the
  design doc (section 2) says why twice more.
* NaN, never 0, under `min_periods` and on a zero-sd window. `calculate_z_score` adds
  1e-9 to the sd and fills NaN with 0, and on DC's empty swap-dealer windows that prints
  0.0, which the sign classifier reads as QUIET. Here a window with no reading is a
  missing reading, and the classifier returns None there.
* The current-state store is read, not a vintage. A CFTC reclassification that
  restates cohort levels prints one spurious flow the week it lands. Vintages exist
  only from 2026-07-31, so this cannot be flagged yet (design doc, section 6).

The state column is a vocabulary, not a signal. The pre-registered test of it
(VALUE_ACCUM long, 13 weeks, ADR-0005 scope) failed the crucible gauntlet on all
three pillars on 2026-09-26 (design doc, "The study: run, failed, closed"). Nothing
here carries a forward return or a verdict word, and nothing in `signals`,
`conditions`, `models` or `synthesis` reads these columns.

Held out on purpose, per the design doc's PR 1 scope: dGross and the straddle flag,
the derisk flag (fixed multipliers designed on gold, untested elsewhere), any forward
return, any state NAME for TFF (the sign string renders until a TFF vocabulary is
proposed), and percent-of-OI flows (same function on `pct_oi_col`, later).
"""

import numpy as np
import pandas as pd

import cotmetrics.categories as categories
import cotmetrics.constants as const
import cotmetrics.flow_roles as flow_roles

FLOW_STATE_QUIET = "QUIET"
FLOW_STATE_PARTIAL = "PARTIAL"

# The gold script's STATE_NAMES verbatim (scripts/analysis/cot_flow_states.py), keyed
# by the (Managed Money, Other Reportable, Non-Reportable) sign triple, which is the
# disagg opinion tuple's order in flow_roles. Caption vocabulary for Disaggregated
# markets only. TFF has no agreed names and renders the sign string.
DISAGG_FLOW_STATES = {
    (1, 1, 1): "BROAD_ACCUM",
    (1, 1, -1): "INST_BUY_RETAIL_SELL",
    (1, -1, 1): "TREND+RETAIL_BUY",
    (1, -1, -1): "MM_ALONE_BUY",
    (-1, 1, 1): "MM_SELL_OTHERS_BUY",
    (-1, 1, -1): "VALUE_ACCUM",
    (-1, -1, 1): "RETAIL_ALONE_BUY",
    (-1, -1, -1): "BROAD_LIQUID",
}

_SIGN_GLYPH = {1: "+", -1: "-", 0: "0"}


# --- column-name builders -------------------------------------------------------
# The UI never spells a flow column itself. It asks for one of these.

def flow_col(spec):
    return spec.prefix + const.FLOW


def flow_long_col(spec):
    return spec.prefix + const.FLOW_LONG


def flow_short_col(spec):
    return spec.prefix + const.FLOW_SHORT


def flow_z_col(spec):
    return spec.prefix + const.FLOW_Z + _window_suffix()


def flow_thin_col(spec):
    return spec.prefix + const.FLOW_THIN


def flow_sign_col(spec):
    return spec.prefix + const.FLOW_SIGN


def counterparty_flow_col():
    return const.COUNTERPARTY + const.FLOW


def counterparty_flow_z_col():
    return const.COUNTERPARTY + const.FLOW_Z + _window_suffix()


def _window_suffix():
    return f" {const.FLOW_Z_WEEKS}w"


# --- the primitive --------------------------------------------------------------

def weekly_change(series, *, max_gap_days=const.FLOW_MAX_GAP_DAYS, source_code=None):
    """`series.diff()` with the two discontinuities of section 5 refused.

    A difference across a missed report week is not a week's flow, and a difference
    across a contract-code change is the difference of two populations (LBR's stitch
    alternates codes across three weeks of 2023 and prints managed-money z of -3.7
    then +3.3 on nothing). Both are NaN rather than 0: 0 would read as QUIET.

    `max_gap_days` masks a row whose index is more than that many days after the
    prior row. None turns the rule off, and a non-datetime index skips it silently
    because there is no gap to measure. `source_code` is a Series aligned to the
    index (const.SOURCE_CODE from the category frame). A row whose code differs from
    the prior row's is masked. Row 0 is NaN by construction of diff.
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
        code = pd.Series(source_code).reindex(series.index) if isinstance(
            source_code, pd.Series) else pd.Series(source_code, index=series.index)
        code = code.astype(object)
        changed = (code.to_numpy() != code.shift().to_numpy())
        changed[0] = False
        mask |= changed
    if mask.any():
        out = out.copy()
        out.iloc[mask] = np.nan
    return out


def _rolling_sd(series, window, min_periods):
    return series.rolling(window, min_periods=min_periods).std()


def flow_z(series, window=const.FLOW_Z_WEEKS, min_periods=const.FLOW_Z_MIN_PERIODS):
    """`series / rolling sd`, NaN under min_periods and on a zero-sd window.

    No mean subtraction, no epsilon, no fillna: see the module docstring. The rolling
    sd counts non-NaN observations, so a masked week (gap or seam) thins the window
    for the next `window` rows rather than poisoning it.
    """
    sd = _rolling_sd(series, window, min_periods)
    return series / sd.where(sd > 0)


def flow_signs(z, threshold=const.FLOW_ACTIVE_Z):
    """-1 / 0 / 1 against a strict |z| > threshold, NA where z is NaN.

    Strict, as in the gold script (`np.where(z > Z_ACT, 1, ...)`): exactly 1.0 is
    inactive. Int64 so the NA is a real NA and not a float that a `!= 0` test would
    count as active.
    """
    z = pd.Series(z, dtype=float)
    out = pd.Series(0, index=z.index, dtype="Int64")
    out[(z > threshold).to_numpy()] = 1
    out[(z < -threshold).to_numpy()] = -1
    out[z.isna().to_numpy()] = pd.NA
    return out


def flow_state(sign_trend, sign_value, sign_retail, report):
    """The week's label from the three opinion-cohort signs. Object Series.

    None wherever any sign is NA (the warm-up is unlabelled, never QUIET). QUIET for
    (0, 0, 0), PARTIAL where at least one but not every cohort is active, and for the
    eight all-active triples, the DISAGG_FLOW_STATES name on Disaggregated and the
    sign string ("-,+,0" style, in opinion order) on TFF, which has no vocabulary yet.
    Styled on `indicators.fomo_zones`: a published cutoff restated, not a verdict.
    """
    a = pd.Series(sign_trend).astype("Int64")
    b = pd.Series(sign_value).astype("Int64")
    c = pd.Series(sign_retail).astype("Int64")
    out = pd.Series([None] * len(a), index=a.index, dtype=object)
    valid = (a.notna() & b.notna() & c.notna()).to_numpy()
    labels = []
    for x, y, w in zip(a.to_numpy()[valid], b.to_numpy()[valid], c.to_numpy()[valid]):
        triple = (int(x), int(y), int(w))
        if triple == (0, 0, 0):
            labels.append(FLOW_STATE_QUIET)
        elif 0 in triple:
            labels.append(FLOW_STATE_PARTIAL)
        elif report == categories.REPORT_DISAGG:
            labels.append(DISAGG_FLOW_STATES[triple])
        else:
            labels.append(",".join(_SIGN_GLYPH[s] for s in triple))
    out.iloc[np.flatnonzero(valid)] = labels
    return out


def build_flow_frame(category_frame, report, symbol=None):
    """The flow columns for one market, on the category frame's index.

    Args:
        category_frame: what `categories.build_category_frame` returned. Only its
            net / long / short columns and, when present, const.SOURCE_CODE are read.
        report: categories.REPORT_DISAGG or REPORT_TFF.
        symbol: the market's symbol ("GC"), which selects the per-market roles from
            `flow_roles`. None or an unmeasured symbol gets the per-report default.

    Returns:
        pd.DataFrame of ONLY the new columns, same index. Empty in, empty out. Per
        present category: dNet, dLong, dShort, "Flow Z 52w", "Flow Thin" (nullable
        boolean, NA where the sd is NaN). Then, when any counterparty member is
        present, "Counterparty dNet" and its z. Then per opinion cohort present a
        "Flow Sign" (Int64), and when all three opinion cohorts are present the
        active count and, on a state-eligible market only, the "Flow State".
        attrs carry every parameter and the roles used.

    The seam mask applies to all three differences of a category, not only dNet: the
    legs come from the same contract population as the net.
    """
    if category_frame is None or category_frame.empty:
        return pd.DataFrame()

    specs = categories.present_categories(category_frame, report)
    by_key = {s.key: s for s in specs}
    source = (category_frame[const.SOURCE_CODE]
              if const.SOURCE_CODE in category_frame.columns else None)
    window, min_periods = const.FLOW_Z_WEEKS, const.FLOW_Z_MIN_PERIODS

    out = pd.DataFrame(index=category_frame.index)
    for spec in specs:
        dnet = weekly_change(category_frame[categories.net_col(spec)], source_code=source)
        out[flow_col(spec)] = dnet
        out[flow_long_col(spec)] = weekly_change(
            category_frame[categories.long_col(spec)], source_code=source)
        out[flow_short_col(spec)] = weekly_change(
            category_frame[categories.short_col(spec)], source_code=source)
        sd = _rolling_sd(dnet, window, min_periods)
        out[flow_z_col(spec)] = dnet / sd.where(sd > 0)
        # Thin dims a cell rather than blanking it: the count is still a reading, the
        # z just is not one worth comparing across markets.
        thin = (sd < const.FLOW_MIN_STD_CONTRACTS).astype("boolean")
        out[flow_thin_col(spec)] = thin.mask(sd.isna(), pd.NA)

    roles = flow_roles.roles_for(report, symbol)
    members = [by_key[k] for k in roles.counterparty if k in by_key]
    if members:
        composite = sum(out[flow_col(s)] for s in members)
        out[counterparty_flow_col()] = composite
        out[counterparty_flow_z_col()] = flow_z(composite, window, min_periods)

    opinion = [by_key.get(k) for k in roles.opinion]
    for spec in opinion:
        if spec is not None:
            out[flow_sign_col(spec)] = flow_signs(out[flow_z_col(spec)])
    if all(spec is not None for spec in opinion):
        signs = [out[flow_sign_col(spec)] for spec in opinion]
        active = sum((s != 0).astype("Int64") for s in signs)
        out[const.FLOW_N_ACTIVE] = active.mask(
            pd.concat(signs, axis=1).isna().any(axis=1), pd.NA)
        if roles.state_eligible:
            out[const.FLOW_STATE] = flow_state(*signs, report=report)

    out.attrs["flow_window"] = window
    out.attrs["flow_min_periods"] = min_periods
    out.attrs["flow_max_gap_days"] = const.FLOW_MAX_GAP_DAYS
    out.attrs["flow_threshold"] = const.FLOW_ACTIVE_Z
    out.attrs["flow_roles"] = {
        "report": roles.report,
        "symbol": symbol,
        "counterparty": roles.counterparty,
        "opinion": roles.opinion,
        "neutral": roles.neutral,
        "inert": roles.inert,
        "residual": roles.residual,
        "source": roles.source,
        "state_eligible": roles.state_eligible,
    }
    return out
