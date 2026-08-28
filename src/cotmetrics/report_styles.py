"""
cotmetrics/report_styles.py

Presentation rules for the Signal Matrix: colour ramps and value formatting.

Split out of reports.py so it carries no data-layer imports. reports.py pulls in
cotIndexer at module scope, which needs a populated COTDATA_STORE, and that made
these pure functions untestable without standing up the whole store.
"""
import pandas as pd

import cotmetrics.constants as const
import cotmetrics.models as models

# ── colour helpers ────────────────────────────────────────────────────────────
_BULL   = "#10B981"
_BEAR   = "#EF4444"
_YELLOW = "#EAB308"
_NEUTRAL = "#ABB8C9"
_DIM    = "#737373"

# Page background these tints are blended against, per the <style> block below.
_BG = "#1a1a1a"


def _blend(hex_color, toward, amount):
    """Blend one #rrggbb toward another. `amount` 0 = unchanged, 1 = fully `toward`."""
    a = hex_color.lstrip("#")
    b = toward.lstrip("#")
    def mix(i):
        return round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * amount)
    return "#{:02x}{:02x}{:02x}".format(mix(0), mix(2), mix(4))


# The approach step, flattened toward the background. The Dash heatmap expresses this
# as opacity, but email clients handle rgba on *text* unreliably (Outlook in
# particular), so here it is blended to hex against the known page background instead.
_BULL_NEAR = _blend(_BULL, _BG, 0.5)
_BEAR_NEAR = _blend(_BEAR, _BG, 0.5)

# One wash weight past the gate, not a gradient: a setup is binary, so (97, 3, 5) and
# (100, 0, 0) must render identically. Backgrounds may stay rgba -- it is text colour
# that email clients mishandle.
_WASH_BULL = "rgba(16,185,129,0.20)"
_WASH_BEAR = "rgba(239,68,68,0.20)"


def _leg_agrees(v, state, high, low, near=const.SETUP_NEAR_WIDTH):
    """Is a speculator leg on the side its row's setup direction implies?

    Uses the same "close" width as the near states rather than the gate itself, so a
    leg that is plainly on the right side still counts: S&P 500's Small Specs at 91
    agree with a bear setup even though the gate is 95.
    """
    if state == const.SETUP_BULL:
        return v <= low + near
    if state == const.SETUP_BEAR:
        return v >= high - near
    return False


def _setup_cell_style(v, state, role, high, low, is_equity=False,
                      near=const.SETUP_NEAR_WIDTH):
    """Colour one positioning-index cell from its *row's* setup state.

    `role` is "comm" or "spec", which decides the side of the band the cell has to be on
    to count toward the setup: a bullish setup wants Commercials high and speculators
    low. `state` comes from utils.setup_state, so the styling and the strategy read the
    same rules rather than each encoding them.

    A full setup washes every leg in the band. A near setup only tints the legs actually
    at or near their own gate, so the blocking leg stays neutral and reads as the reason
    the setup has not fired: Cocoa at (0, 100, 80) tints Commercials and Large Specs and
    leaves Small Specs dim.

    Equities skip the speculator legs in utils.is_setup, so their spec cells never tint
    on a near state. On a full setup the whole band washes, since for equities the
    Commercial leg alone is the setup and highlighting only that one cell would
    understate it.
    """
    dim = f"color:{_DIM};"
    if v is None or not state:
        return dim

    if state in const.SETUP_FULL_STATES:
        # An equity setup is decided by Commercials alone, so its spec legs can sit
        # anywhere. Washing the whole band still reads correctly as "this row is a
        # setup", but it would colour a leg against its own value: DOW is a bear setup
        # whose Small Specs sit at 64, and a red mid-range cell invites being read as a
        # bearish extreme. So an equity spec leg only washes when it is at least near
        # its own gate on the setup's side. Commodity rows are unaffected -- is_setup
        # already required every leg through its gate before the state could be full.
        if is_equity and role == "spec" and not _leg_agrees(v, state, high, low, near):
            return dim
        if state == const.SETUP_BULL:
            return f"color:{_BULL}; background-color:{_WASH_BULL};"
        return f"color:{_BEAR}; background-color:{_WASH_BEAR};"

    if is_equity and role == "spec":
        return dim
    if state == const.SETUP_NEAR_BULL:
        close = v >= high - near if role == "comm" else v <= low + near
        return f"color:{_BULL_NEAR};" if close else dim
    if state == const.SETUP_NEAR_BEAR:
        close = v <= low + near if role == "comm" else v >= high - near
        return f"color:{_BEAR_NEAR};" if close else dim
    return dim

# field -> (role, band, which setup-state column drives it). The bands come off the
# models rather than the raw constants so a column can never be styled against a band
# its own setup-state column was not resolved with.
_INDEX_COLS = {
    "Comm Index":      ("comm", models.RAW_PF.band, const.SETUP_CLS_COL),
    "Lrg Index":       ("spec", models.RAW_PF.band, const.SETUP_CLS_COL),
    "Sml Index":       ("spec", models.RAW_PF.band, const.SETUP_CLS_COL),
    "Comm Index Norm": ("comm", models.NPF.band, const.SETUP_NPF_COL),
    "Sml Index Norm":  ("spec", models.NPF.band, const.SETUP_NPF_COL),
    # Not in the email's groups today; styled under the model whose gate reads it so
    # the entry is already right if that block ever grows a Large column.
    "Lrg Index Norm":  ("spec", models.NPF_CLS_95_5.band, const.SETUP_NPF_CLS_COL),
}


def _as_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _cell_style(col, val, row=None):
    """Return the CSS style string (color, background, etc) for a given cell.

    `row` is needed only by the speculator index columns, which colour relative to the
    Commercials reading in the same row rather than on their own level.
    """
    base_style = f"color:{_DIM};"

    if val is None or (isinstance(val, float) and pd.isna(val)):
        return base_style
    try:
        v = float(val)
    except (TypeError, ValueError):
        return f"color:{_NEUTRAL};"

    if col in _INDEX_COLS:
        role, band, state_col = _INDEX_COLS[col]
        state = row.get(state_col, const.SETUP_NONE) if row is not None else const.SETUP_NONE
        is_equity = bool(row.get(const.IS_EQUITY_COL)) if row is not None else False
        return _setup_cell_style(v, state, role, *band, is_equity=is_equity)

    elif col == "Comm Z":
        if v >= const.ZSCORE_MAX_THRESHOLD:
            return f"color:{_BULL};"
        if v <= const.ZSCORE_MIN_THRESHOLD:
            return f"color:{_BEAR};"
        return base_style

    elif col == "OI Z":
        if abs(v) >= const.OI_ZSCORE_HIGHLIGHT_THRESHOLD:
            return f"color:{_YELLOW};"
        return base_style

    elif col == "WILLCO":
        if v >= const.WILLCO_MAX_THRESHOLD:
            return f"color:{_BULL};"
        if v <= const.WILLCO_MIN_THRESHOLD:
            return f"color:{_BEAR};"
        return base_style

    elif col == "Inst Sentiment":
        if v <= const.LW_LRG_SENTIMENT_MIN_THRESHOLD:
            return f"color:{_BULL};"
        if v >= const.LW_LRG_SENTIMENT_MAX_THRESHOLD:
            return f"color:{_BEAR};"
        return base_style

    elif col in ("Comm Move", "Lrg Move", "Sml Move"):
        if v >= const.MOMENTUM_MAX_THRESHOLD:
            return f"color:{_BULL};"
        if v <= const.MOMENTUM_MIN_THRESHOLD:
            return f"color:{_BEAR};"
        return base_style

    elif col == "Max Pain Pull":
        if v > 0:
            return f"color:{_BULL};"
        if v < 0:
            return f"color:{_BEAR};"
        return base_style

    return f"color:{_NEUTRAL};"


def _fmt(col, val):
    """Format a cell value for display in the email."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "–"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)

    if col in ("Comm Z", "OI Z"):
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}"
    if col == "Max Pain Pull":
        return f"{v:+.1f}%"
    if col in ("Comm Move", "Lrg Move", "Sml Move"):
        sign = "+" if v >= 0 else ""
        return f"{sign}{int(v):,}"
    if col == "Delta IV":
        if abs(v) < 0.1:
            return f"{v:.3f}"
        elif abs(v) < 1.0:
            return f"{v:.2f}"
        else:
            return f"{v:.1f}"
    if col == "Max Pain":
        if v < 0.01:
            return f"{v:.5f}"
        elif v < 1.0:
            return f"{v:.4f}"
        elif v < 100:
            return f"{v:.2f}"
        else:
            return str(int(v))
    return str(int(v))
