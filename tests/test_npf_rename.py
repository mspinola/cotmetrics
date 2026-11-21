"""The Custom -> NPF rename (0.19.0) and its deprecation path.

The frozen per-market table (NpfLookbackWeeks, "CustomLookbackWeeks" before) is a
pre-registered spec: livebook trades on its values. So the rename must not move a single
number, and every old spelling must keep resolving to the same values for at least one
release. These tests pin both halves.
"""
import warnings

import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
from cotmetrics import models
from cotmetrics.CotIndexer import CotIndexer, Instrument, npf_lookback_weeks


def _positions(n=120, seed=7):
    rng = np.random.default_rng(seed)
    oi = rng.integers(50_000, 150_000, n).astype(float)
    comm = np.cumsum(rng.normal(0, 3_000, n))
    large = np.cumsum(rng.normal(0, 2_000, n))
    small = -(comm + large)
    df = pd.DataFrame({
        const.REPORT_DATE_XLS: pd.date_range("2020-01-07", periods=n, freq="7D"),
        const.OPEN_INTEREST_XLS: oi,
        const.COMM_NET: comm, const.LARGE_NET: large, const.SMALL_NET: small,
        const.CLOSING_PRICE: 100 + np.cumsum(rng.normal(0, 1, n)),
    })
    for net, norm in ((const.COMM_NET, const.COMM_NET_NORM),
                      (const.LARGE_NET, const.LARGE_NET_NORM),
                      (const.SMALL_NET, const.SMALL_NET_NORM)):
        df[norm] = df[net] / (oi + 1e-9)
    df[const.COMM_PCT_OI] = round(df[const.COMM_NET] / (oi + 1e-9) * 100, 2)
    df[const.LARGE_PCT_OI] = round(df[const.LARGE_NET] / (oi + 1e-9) * 100, 2)
    df[const.SMALL_PCT_OI] = round(df[const.SMALL_NET] / (oi + 1e-9) * 100, 2)
    df[const.COMM_NET_CHANGE_NORM] = (df[const.COMM_NET_NORM].pct_change() * 100).fillna(0).round(1)
    return df


# ── values: the rename moves nothing ─────────────────────────────────────────────

def test_the_npf_family_equals_what_the_custom_family_computed():
    """The frozen-values guarantee. Build the family under the OLD name, exactly as
    0.18.0 did, and under the new one; every column must match bit for bit."""
    base = _positions()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old = CotIndexer.process_lookback(["Custom", 30], "XX", base.copy())
    new = CotIndexer.process_lookback(["NPF", 30], "XX", base.copy())
    new = CotIndexer.copy_deprecated_custom_family(new)

    old_family = [c for c in old.columns if const.LB_CUSTOM_DEPRECATED in c]
    assert len(old_family) > 20, old_family  # the whole family, not a token column
    for col in old_family:
        npf_col = col.replace(const.LB_CUSTOM_DEPRECATED, const.LB_NPF)
        pd.testing.assert_series_equal(new[npf_col], old[col], check_names=False)
        pd.testing.assert_series_equal(new[col], old[col])


def test_the_custom_copy_touches_only_the_npf_family():
    df = CotIndexer.process_lookback(["NPF", 26], "XX", _positions())
    out = CotIndexer.copy_deprecated_custom_family(df)
    added = set(out.columns) - set(df.columns)
    assert added == {c.replace(" NPF", " Custom") for c in df.columns if " NPF" in c}
    pd.testing.assert_frame_equal(out[df.columns], df)


# ── the deprecated spellings still resolve, and say so ───────────────────────────

def test_old_constants_resolve_to_the_new_columns_with_a_warning():
    with pytest.warns(DeprecationWarning, match="COMM_NPF_IDX"):
        assert const.COMM_CUSTOM_IDX == const.COMM_NPF_IDX == "Comm NPF Idx"
    with pytest.warns(DeprecationWarning):
        assert const.LB_CUSTOM == const.LB_NPF
    with pytest.warns(DeprecationWarning):
        from cotmetrics.constants import LARGE_CUSTOM_IDX_NORM
    assert LARGE_CUSTOM_IDX_NORM == const.LARGE_NPF_IDX_NORM


def test_every_old_constant_has_a_new_twin():
    for old, new in const._DEPRECATED_CUSTOM.items():
        assert "CUSTOM" in old and new == old.replace("CUSTOM", "NPF")
        assert new in vars(const), new


def test_an_unknown_constant_is_still_an_attribute_error():
    with pytest.raises(AttributeError):
        const.NOT_A_CONSTANT  # noqa: B018


def test_the_custom_lookback_argument_warns_and_reads_the_same_columns():
    with pytest.warns(DeprecationWarning, match='"NPF"'):
        old = models.RAW_PF.leg_columns("Custom")
    assert old == ("Comm Custom Idx", "Lrg Spec Custom Idx", "Sml Spec Custom Idx")
    assert models.RAW_PF.leg_columns("NPF") == ("Comm NPF Idx", "Lrg Spec NPF Idx",
                                                "Sml Spec NPF Idx")
    assert const.is_npf_lookback("NPF") and const.is_npf_lookback("Custom")
    assert not const.is_npf_lookback("CMR") and not const.is_npf_lookback("52")


def test_the_header_string_knows_both_names():
    assert const.get_lookback_header_str(["NPF", 30]) == " NPF"
    assert const.get_lookback_header_str(["Custom", 30]) == " Custom"
    assert const.get_lookback_header_str(["CMR", 30]) == " CMR"
    assert const.get_lookback_header_str(["", 52]) == " 52"


def test_instrument_custom_lookback_is_a_deprecated_alias():
    inst = Instrument("Metals", "Gold", "GC", "088691", 24)
    assert inst.npf_lookback == 24 and inst.cmr_lookback == 24
    with pytest.warns(DeprecationWarning, match="npf_lookback"):
        assert inst.custom_lookback == 24


# ── params.yaml: both keys, never a silent disagreement ──────────────────────────

def test_params_new_key_reads_silently():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert npf_lookback_weeks({"Symbol": "GC", "NpfLookbackWeeks": 24}) == 24


def test_params_old_key_still_reads_and_warns():
    with pytest.warns(DeprecationWarning, match="NpfLookbackWeeks"):
        assert npf_lookback_weeks({"Symbol": "GC", "CustomLookbackWeeks": 24}) == 24


def test_params_both_keys_agreeing_is_fine():
    assert npf_lookback_weeks({"Symbol": "GC", "NpfLookbackWeeks": 24,
                               "CustomLookbackWeeks": 24}) == 24


def test_params_both_keys_disagreeing_is_refused():
    with pytest.raises(ValueError, match="disagrees"):
        npf_lookback_weeks({"Symbol": "GC", "NpfLookbackWeeks": 24,
                            "CustomLookbackWeeks": 26})


def test_params_with_neither_key_is_refused():
    with pytest.raises(KeyError, match="NpfLookbackWeeks"):
        npf_lookback_weeks({"Symbol": "GC"})
