import logging
import os
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytz

import cotmetrics.constants as constants

# Log location. Must be absolute: a relative "logs" resolves against the cwd we
# happen to be started in, which is / for launchd/cron jobs -- that made import
# fail outright with "OSError: [Errno 30] Read-only file system: 'logs'". Honors
# COTMETRICS_LOG_DIR, mirroring the COTMETRICS_CACHE convention in constants.
LOG_DIR = os.environ.get(
    "COTMETRICS_LOG_DIR", str(Path.home() / ".cache" / "cotmetrics" / "logs")
)

main_cot_logger_file = "app_cot_logger.log"
def get_cot_logger():
    logger = logging.getLogger(main_cot_logger_file)

    # Prevents adding multiple handlers if the function is called twice
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        # Ensure it doesn't send logs to the root logger as well (prevents duplicates)
        logger.propagate = False

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        # Stream Handler (console/stdout/stderr, required for Gunicorn workers to propagate to server supervisor logs)
        # Attached first so logging still works if the file handler below can't be built.
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File Handler (rotating logs). Best-effort: an unwritable LOG_DIR degrades
        # to console-only logging rather than taking down import for every caller.
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            handler = RotatingFileHandler(
                os.path.join(LOG_DIR, main_cot_logger_file),
                maxBytes=10*1024*1024,
                backupCount=5
            )
            handler.setLevel(logging.INFO)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except OSError as e:
            logger.warning(f"file logging disabled ({LOG_DIR}): {e}")

    return logger


def setup_launch_logger(log_directory=None):
    log_directory = log_directory or LOG_DIR

    # Create a specific logger just for startups
    launch_logger = logging.getLogger("app_launch")
    launch_logger.setLevel(logging.INFO)

    # Prevent duplicate logging during Dash hot-reloads
    if not launch_logger.handlers:
        # Best-effort for the same reason as get_cot_logger: this runs at import.
        try:
            os.makedirs(log_directory, exist_ok=True)
            file_handler = logging.FileHandler(os.path.join(log_directory, "launches.log"))

            # Simple, clean formatting specifically for timestamps
            formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - SYSTEM LAUNCHED')
            file_handler.setFormatter(formatter)

            launch_logger.addHandler(file_handler)
        except OSError as e:
            get_cot_logger().warning(f"launch logging disabled ({log_directory}): {e}")

    return launch_logger


# Initialize loggers
cot_logger = get_cot_logger()
downloader_logger = get_cot_logger()
launch_logger = setup_launch_logger()


def milliseconds_until_midnight():
    """Calculate the number of milliseconds until the next midnight in the app's timezone."""
    local_tz = pytz.timezone(constants.app_timezone)
    now = datetime.now(tz=local_tz)
    next_midnight = (now + timedelta(days=1)).replace(hour=0,
                                                      minute=0,
                                                      second=0,
                                                      microsecond=0)
    delta = next_midnight - now
    return int(delta.total_seconds() * 1000)


def get_lookback_weeks(lookback, instrument):
    if lookback == "26":
        return 26
    elif lookback == "52":
        return 52
    else:
        return instrument.custom_lookback


def is_setup(is_equity, comms_idx, lrg_idx, sml_idx, min_idx=5, max_idx=95,
             spec_idxs=None):
    """Vectorized setup detector. Works on scalars or Series.

    `spec_idxs` overrides which speculator legs gate the setup, for models whose gate is
    not the three-leg CLS default. The CS gate drops Large Specs, so it passes
    [sml_idx]. Left as None the legs are [lrg_idx, sml_idx], matching every existing
    caller.

    setup_state below is the scalar twin, kept in step by
    test_setup_state_matches_is_setup_across_a_sweep rather than by inspection.
    """
    legs = [lrg_idx, sml_idx] if spec_idxs is None else list(spec_idxs)

    bullish = (comms_idx >= max_idx)
    close_bullish = (comms_idx >= max_idx-5)
    bearish = (comms_idx <= min_idx)
    close_bearish = (comms_idx <= min_idx+5)

    # Apply the non-equity filters if applicable
    if not is_equity and legs:
        # A full setup needs every leg through its gate. A near one needs Commercials
        # close and two things of the spec legs: at least one within reach of its own
        # gate, AND none leaning against the setup (past neutral the wrong way).
        #
        # The second clause is the fix. The rule used to be the first clause alone, so a
        # row with one spec through its gate read as "approaching" even when another spec
        # sat at the opposite extreme: Orange Juice at Comm 96 / Large 0 / Small 100 was
        # near_bull on Large, while Small at 100 leaned hard bearish. Requiring no leg
        # past neutral drops that, while keeping rows where a leg is short of its gate but
        # still on the setup's side (Cocoa's Small at 80 against a bear setup).
        #
        # Keeping the first clause is what leaves the NPF CS gate untouched: with a single
        # spec leg, "that leg near its gate" already implies "on the setup's side", so the
        # neutral clause adds nothing and the verdict is unchanged from before.
        near_bull_any = near_bear_any = None     # some leg within reach of its gate
        near_bull_side = near_bear_side = None    # no leg leaning against the setup
        for s in legs:
            bullish &= (s <= min_idx)
            bearish &= (s >= max_idx)
            leg_near_bull = (s <= min_idx+5)
            leg_near_bear = (s >= max_idx-5)
            near_bull_any = leg_near_bull if near_bull_any is None else (near_bull_any | leg_near_bull)
            near_bear_any = leg_near_bear if near_bear_any is None else (near_bear_any | leg_near_bear)
            on_bull_side = (s <= constants.INDEX_NEUTRAL)
            on_bear_side = (s >= constants.INDEX_NEUTRAL)
            near_bull_side = on_bull_side if near_bull_side is None else (near_bull_side & on_bull_side)
            near_bear_side = on_bear_side if near_bear_side is None else (near_bear_side & on_bear_side)
        close_bullish &= near_bull_any & near_bull_side
        close_bearish &= near_bear_any & near_bear_side

    return bullish, bearish, close_bullish, close_bearish


def setup_state(comm_idx, spec_idxs, is_equity=False,
                min_idx=5, max_idx=95, near=constants.SETUP_NEAR_WIDTH):
    """Collapse one band's legs into a single scalar state.

    Returns one of SETUP_BULL / SETUP_BEAR / SETUP_NEAR_BULL / SETUP_NEAR_BEAR /
    SETUP_NONE. Same rules as `is_setup`, generalized two ways: any number of
    speculator legs (the NPF CS gate uses Commercials plus Small only, where the CLS
    gate uses all three) and any threshold pair.

    A full setup takes precedence over a near one, and `is_setup` is the reference:
    test_setup_state_matches_is_setup asserts the two agree across a sweep for the
    three-leg 95/5 case.

    Scalar rather than vectorized on purpose. It is consumed per row when building the
    Signal Matrix, so the caller can carry the state as a column and both renderers
    style from it instead of each re-deriving the rules.
    """
    if comm_idx is None:
        return constants.SETUP_NONE
    legs = [s for s in spec_idxs if s is not None]
    if not is_equity and len(legs) != len(spec_idxs):
        return constants.SETUP_NONE

    bull = comm_idx >= max_idx
    bear = comm_idx <= min_idx
    near_bull = comm_idx >= max_idx - near
    near_bear = comm_idx <= min_idx + near

    # Equities skip the speculator filters entirely, matching is_setup: for them the
    # Commercial leg alone defines the setup.
    if not is_equity:
        bull = bull and all(s <= min_idx for s in legs)
        bear = bear and all(s >= max_idx for s in legs)
        # A near setup needs one spec leg within reach of its gate AND no leg leaning
        # against it (past neutral the wrong way). The second clause is the addition: it
        # drops rows blocked by a leg at the opposite extreme (Orange Juice's Small at
        # 100 against a bull) while keeping a leg that is short of its gate but still on
        # the setup's side. The first clause leaves the single-leg NPF gate unchanged.
        # See is_setup, the reference this is checked against.
        near_bull = (near_bull and any(s <= min_idx + near for s in legs)
                     and all(s <= constants.INDEX_NEUTRAL for s in legs))
        near_bear = (near_bear and any(s >= max_idx - near for s in legs)
                     and all(s >= constants.INDEX_NEUTRAL for s in legs))

    if bull:
        return constants.SETUP_BULL
    if bear:
        return constants.SETUP_BEAR
    if near_bull:
        return constants.SETUP_NEAR_BULL
    if near_bear:
        return constants.SETUP_NEAR_BEAR
    return constants.SETUP_NONE


def price_trend_is_up(df, as_of, period=constants.PRICE_TREND_PERIOD):
    """Is the close higher than it was `period` reports before `as_of`?

    The directional context that decides whether rising open interest reads as
    accumulation or as distribution. Both the signal cards and the tape synthesis ask
    it, and both used to answer it themselves with the period and the NaN handling
    written out twice.

    The two copies had already drifted at the guards: the synthesis version returned
    False for a frame with no close column, the card version raised. False wins here,
    because every caller treats "not up" as the neutral reading rather than as an
    error.
    """
    import pandas as pd  # deferred, like read_and_clean_xls below

    if df is None or constants.CLOSING_PRICE not in df.columns:
        return False
    closes = df[constants.CLOSING_PRICE].loc[:as_of]
    if len(closes) <= period:
        return False
    delta = closes.diff(period).iloc[-1]
    return bool(pd.notna(delta) and delta > 0)


def standardize_contract_code(val):
    """Standardizes CFTC contract codes to 6-digit zero-padded string format."""
    s = str(val).strip()
    if s.isdigit():
        return s.zfill(6)
    return s


def read_and_clean_xls(xl_path, target_columns=None):
    """Reads a CFTC Excel file, cleans columns, and standardizes contract codes."""
    import pandas as pd

    # Read the specific columns if provided
    df = pd.read_excel(xl_path, usecols=target_columns)

    if constants.CONTRACT_CODE_XLS in df.columns:
        df[constants.CONTRACT_CODE_XLS] = df[constants.CONTRACT_CODE_XLS].apply(standardize_contract_code)

    return df

