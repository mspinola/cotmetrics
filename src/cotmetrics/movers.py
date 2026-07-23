"""
cotmetrics/movers.py

The Home page board: one sweep over every market's latest row, and the selectors that
read it two ways.

`get_board` does the sweep. Two views select from it and they answer different
questions, which is why both exist:

  weekly movers  -- what *changed* at this release, ranked on the week-over-week point
                    change of the 0-100 positioning index.
  active setups  -- where positioning *is*, filtered to rows whose setup state is at or
                    approaching a gate.

Commercials rather than whichever leg moved most. Every setup gates on the Commercial
leg, so a large Commercial move is the one that can actually change a row's setup
state. Ranking on any leg surfaces more, but Small Specs crowd it out: their median
weekly move is 8.0 points against 6.0 for the other two, so raw-point ranking
over-selects them without that meaning more.

The sweep is shared rather than run once per view for two reasons. It is the expensive
part (42 instruments, and the tape synthesis on top when a filter is active), and more
importantly a second sweep is a second place for the model to be applied. Setup state
computed twice is setup state that can disagree with itself, which is the whole defect
models.py exists to prevent.

Kept out of reports.py so the Dash home page can import it without pulling in the
Signal Matrix builder, and out of the app so the emailed report can use it later.
"""
import pandas as pd

import cotmetrics.constants as const
import cotmetrics.models as models
from cotmetrics.indexer import get_indexer

# The indexer used to be imported inside get_weekly_movers rather than here, because
# importing it instantiated a CotIndexer off COTDATA_STORE and that made even the pure
# caption logic unimportable without standing up the whole store. `get_indexer` builds on
# first call now, so the import is free and this can sit at module scope like anything
# else. Keep the calls inside the functions: that is where the store is actually needed.

MOVER_GROUP = "Commercials"
# Adjective form, for headings. "Biggest Commercials Moves" does not read.
MOVER_GROUP_ADJ = "Commercial"

# "Unusual" flag: this week's move as a multiple of the market's *own* typical weekly
# Commercial move, so a market that normally drifts 5 points and lurches 25 is marked
# even though bigger absolute moves rank above it. Ranking stays on raw points -- a list
# whose headline number does not explain its own order is hard to scan -- so this rides
# along as a flag rather than replacing the sort.
#
# 4x is a top-decile week: 9.7% of all Commercial observations clear it, against 16.8%
# at 3x and 30% at 2x. On the current board it marks 2 of the 8 cards.
UNUSUAL_MULTIPLE = 4.0
# Below this the multiple is noise: a leg whose typical week is 1 point turns a 4-point
# drift into a "4x" event. Guards the quiet-market amplification the ratio invites.
UNUSUAL_MIN_POINTS = 5
# Fewer observations than this and the median is not a stable baseline to divide by.
UNUSUAL_MIN_HISTORY = 52

# Home page tape-bias filter chips. Same tokens and same OR-when-both semantics as
# build_mobile_asset_card, so the movers strip and the screener below it agree on what
# a toggle means.
FILTER_BULL = "TAPE_BIAS_BULL"
FILTER_BEAR = "TAPE_BIAS_BEAR"
_FILTER_BIAS = {FILTER_BULL: "bullish", FILTER_BEAR: "bearish"}


def _wanted_biases(filter_types):
    """Tape biases a filter selection admits, or None when it admits everything."""
    wanted = {_FILTER_BIAS[f] for f in (filter_types or []) if f in _FILTER_BIAS}
    return wanted or None


def _unusual_multiple(delta, history):
    """This move as a multiple of the market's own typical weekly move, or None.

    Median rather than mean or standard deviation: weekly index deltas are heavy-tailed,
    and the handful of lurches this flag exists to catch would otherwise inflate the very
    baseline they are measured against.

    Returns None when the move is too small or the history too short to divide by, so
    callers can treat "not unusual" and "cannot tell" the same way without a magic number.
    """
    if delta is None or abs(delta) < UNUSUAL_MIN_POINTS:
        return None
    scale = history.dropna().abs()
    if len(scale) < UNUSUAL_MIN_HISTORY:
        return None
    typical = scale.median()
    if not typical:
        return None
    return abs(delta) / typical


def _caption(idx, delta):
    """Where the move left Commercials, in the vocabulary the heatmap already uses.

    Describes position, not prediction: "pushed into the top of its range", never
    "bullish". It also says nothing about the row's setup state, which travels as a
    separate field. Gluing the two together reads as cause and effect and is often
    exactly wrong -- Orange Juice's Small Specs jumped 69 points into their own top,
    which is what *blocks* its bullish setup rather than advancing it.

    The tiers are deliberately a fixed scale rather than the active model's band. This
    is a positional description of where the index sits, and where 85 sits does not
    change because the gate around it moved. The badge is the authority on setup state;
    letting the caption shift under it would give one row two answers.
    """
    direction = "Pushed" if delta > 0 else "Dropped"
    if idx >= const.INDEX_HIGH_THRESHOLD:
        where = "into the top of its range"
    elif idx <= const.INDEX_LOW_THRESHOLD:
        where = "to the bottom of its range"
    elif idx >= const.INDEX_NORM_HIGH_THRESHOLD:
        where = "into the high end of its range"
    elif idx <= const.INDEX_NORM_LOW_THRESHOLD:
        where = "to the low end of its range"
    else:
        where = "toward mid-range"
    return f"{direction} {where}"


def _leg(value):
    """A leg index as a plain int, or None when the frame has no reading for it."""
    if value is None or pd.isna(value):
        return None
    return round(float(value))


def get_board(asset_classes=None, lookback="Custom", target_date=None, filter_types=None,
              model=None):
    """Every market's latest row, as the one sweep both Home page strips read.

    Returns an unordered list of dicts, one per market with usable data. `delta`,
    `multiple` and `caption` are None where the Commercial index did not move or the
    frame is too short to scale the move against -- selection is the caller's job, and a
    row with no move is still a row with a setup state.

    That last point is why the sweep does not drop zero-delta rows itself, as the movers
    ranking used to. A market pinned at an extreme with no Commercial move this week is
    the *most* interesting kind of setup, and dropping it here would delete it from the
    setups view to satisfy a rule that only the movers view has.

    `filter_types` restricts the pool here rather than at selection, so a filtered movers
    strip still fills up by reaching further down the list rather than shrinking to
    whatever survived an unfiltered top slice. On current data a bias filter would leave
    only 2 to 4 of the unfiltered top 8, which reads as broken rather than filtered.

    Tape bias needs the full synthesis per asset, so it is only computed when a filter
    is actually active.

    `model` selects the whole read, not just the badge: the frame, the ranking delta and
    the setup state all come from it. They have to move together -- ranking on raw
    contracts while badging setups from the normalized basis is the mixed rule
    models.py exists to prevent.
    """
    model = model if isinstance(model, models.PositioningModel) else models.resolve(model)
    from cotmetrics.synthesis import generate_exhaustive_tape_synthesis

    wanted_biases = _wanted_biases(filter_types)

    if not asset_classes:
        asset_classes = get_indexer().get_asset_classes()

    # The gate reads whichever columns the model says it reads (model.leg_columns via
    # setup_state_from), rather than this function picking them. Naming them here is
    # what shipped the defect this replaced: the lookback-named columns are the raw
    # series whatever basis was fetched, so under NPF the gate read one series while the
    # card displayed another. 35 of 42 frames held different values in the two places
    # and 6 markets were badged differently here than on their own accordion card.
    # Platinum showed SETUP beside a neutral card, and Soybean Oil's bear setup did not
    # show at all. Raw PF hid it completely, because there the two families coincide.
    _, lrg_col, sml_col = model.leg_columns(lookback)
    rows = []
    for ac in asset_classes:
        for asset in get_indexer().get_assets_for_asset_class(ac):
            df = get_indexer().get_symbols_data(asset, lookback, model.basis)
            if df.empty:
                continue

            if target_date:
                matching = df[df.index.strftime("%Y-%m-%d") == target_date]
                if matching.empty:
                    continue
                latest = matching.iloc[-1]
            else:
                latest = df.iloc[-1]

            # The index level is required -- it is the headline number on every card and
            # the input to the gate. The delta is not: it only gates the movers view.
            idx = latest.get(const.COMMS_IDX)
            if idx is None or pd.isna(idx):
                continue

            delta = latest.get(const.COMM_WOW)
            if delta is None or pd.isna(delta) or delta == 0:
                delta = None

            symbol = get_indexer().get_instrument_symbol_from_name(asset)
            if wanted_biases is not None:
                bias = generate_exhaustive_tape_synthesis(
                    latest, symbol_str=symbol, df=df
                ).get("tape_bias", "neutral")
                if bias not in wanted_biases:
                    continue

            multiple = _unusual_multiple(delta, df[const.COMM_WOW])
            is_equity = get_indexer().is_equity(asset)

            rows.append({
                "asset": asset,
                "asset_class": ac,
                "symbol": symbol,
                "group": MOVER_GROUP,
                "index": round(float(idx)),
                "delta": round(float(delta)) if delta is not None else None,
                "multiple": round(multiple, 1) if multiple is not None else None,
                "unusual": multiple is not None and multiple >= UNUSUAL_MULTIPLE,
                "setup": model.setup_state_from(latest, lookback, is_equity),
                # The speculator legs, for the setups view to show the gate's working.
                # Read off the same columns the gate just used, so a card cannot print
                # one series as the gate's reasoning while the verdict came from
                # another. There is no Commercial twin here on purpose: `index` above is
                # that number, and giving the card's headline and the gate's input
                # separate fields is what let them drift apart in the first place.
                "lrg_index": _leg(latest.get(lrg_col)),
                "sml_index": _leg(latest.get(sml_col)),
                "is_equity": is_equity,
                "caption": _caption(idx, delta) if delta is not None else None,
            })

    return rows


def rank_movers(rows, limit=8):
    """Board rows ranked by the largest week-over-week Commercial move.

    Rows whose Commercial index did not move are dropped rather than padding the list
    with zeroes: a strip whose headline number is `0` explains nothing.
    """
    moved = [r for r in rows if r["delta"]]
    moved.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return moved[:limit]


def select_setups(rows, limit=None):
    """Board rows at or approaching a gate, full setups first.

    Ordered by tier and then by how far into its own range the Commercial index sits, so
    the headline number on each card explains its own position in the list. That is the
    same principle the movers ranking follows, and it works across directions because a
    bull setup near 100 and a bear setup near 0 are equally far from mid-range.

    Near states are included rather than split into their own strip. There are weeks when
    a model has only two full setups on the whole board, and a two-card strip beside an
    eight-card movers strip reads as broken. They stay visually subordinate to the full
    ones, and the tier ordering means a reader never has to check a badge to know which
    kind they are looking at.
    """
    tier = {s: 0 for s in const.SETUP_FULL_STATES}
    tier.update({s: 1 for s in const.SETUP_NEAR_STATES})

    hits = [r for r in rows if r["setup"] in tier]
    hits.sort(key=lambda r: (tier[r["setup"]], -abs(r["index"] - 50), r["asset"]))
    return hits[:limit] if limit else hits


def get_weekly_movers(asset_classes=None, lookback="Custom", target_date=None, limit=8,
                      filter_types=None, model=None):
    """Markets ranked by the largest week-over-week Commercial index move.

    Sweep plus selection, for callers that want only this view. The Home page sweeps once
    via get_board and calls the selectors itself, so it does not pay for two sweeps to
    draw two strips.
    """
    return rank_movers(
        get_board(asset_classes, lookback, target_date, filter_types, model), limit,
    )


def get_active_setups(asset_classes=None, lookback="Custom", target_date=None, limit=None,
                      filter_types=None, model=None):
    """Markets at or approaching a positioning gate. Sweep plus selection, as above."""
    return select_setups(
        get_board(asset_classes, lookback, target_date, filter_types, model), limit,
    )
