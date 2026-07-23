"""Instrument role resolution + the plot-filtered indexer views.

Roles decouple data collection from what the dashboard renders: `deploy`/`watch`
plot, `heldout` is collected + indexed but quarantined out of the dashboard. These
tests are hermetic — `resolve_role` is pure, and the accessors are exercised via a
stand-in `self` so no CotIndexer boot (data store) is needed."""
from types import SimpleNamespace

import pytest

from cotmetrics.CotIndexer import (
    PLOTTED_ROLES,
    VALID_ROLES,
    CotIndexer,
    Instrument,
    resolve_role,
)


def _inst(name, asset_class, role):
    return Instrument(asset_class, name, name, name, 26, role)


# ── resolve_role: per-instrument > class default > global default > 'deploy' ──
def test_resolve_role_defaults_to_deploy():
    assert resolve_role({"Symbol": "GC"}, "Metals", {}) == "deploy"


def test_resolve_role_uses_global_default():
    assert resolve_role({"Symbol": "GC"}, "Metals", {"default": "watch"}) == "watch"


def test_resolve_role_class_default_beats_global():
    cfg = {"default": "deploy", "Dairy": "heldout"}
    assert resolve_role({"Symbol": "DC"}, "Dairy", cfg) == "heldout"
    assert resolve_role({"Symbol": "GC"}, "Metals", cfg) == "deploy"


def test_resolve_role_instrument_override_wins():
    cfg = {"default": "deploy", "Dairy": "heldout"}
    # explicit Role on the instrument beats the class default
    assert resolve_role({"Symbol": "DC", "Role": "watch"}, "Dairy", cfg) == "watch"


def test_resolve_role_rejects_unknown():
    with pytest.raises(ValueError):
        resolve_role({"Symbol": "GC", "Role": "plott"}, "Metals", {})
    assert PLOTTED_ROLES < VALID_ROLES and "heldout" not in PLOTTED_ROLES


# ── plot-filtered accessors (unbound, with a stand-in self) ──
def _fake_indexer():
    insts = {
        "m": _inst("Gold", "Metals", "deploy"),
        "w": _inst("Some Watch", "Metals", "watch"),
        "d": _inst("Class III Milk", "Dairy", "heldout"),
    }
    return SimpleNamespace(instruments=insts)


def test_plotted_instruments_excludes_heldout():
    plotted = CotIndexer.plotted_instruments(_fake_indexer())
    assert set(plotted) == {"m", "w"}          # heldout 'd' dropped


def test_plotted_asset_class_map_drops_all_heldout_class():
    acm = CotIndexer.plotted_asset_class_map(_fake_indexer())
    assert acm["Metals"] == {"Gold", "Some Watch"}
    assert "Dairy" not in acm                   # its only member is heldout


def test_instruments_with_role():
    idx = _fake_indexer()
    assert set(CotIndexer.instruments_with_role(idx, "heldout")) == {"d"}
    assert set(CotIndexer.instruments_with_role(idx, "deploy", "watch")) == {"m", "w"}


# ── the enumeration methods the dashboard + resolve_universe funnel through: held-out
#    is excluded by default (so it can't leak into the deployed universe), opt-in via flag ──
def _fake_with_map():
    insts = {
        "g": _inst("Gold", "Metals", "deploy"),
        "k": _inst("Milk", "Metals", "heldout"),      # heldout member of a live class
        "d": _inst("MSCI EM", "Dairy", "heldout"),    # class whose ONLY member is heldout
    }
    fake = SimpleNamespace(
        instruments=insts,
        asset_class_map={"Metals": {"Gold", "Milk"}, "Dairy": {"MSCI EM"}})
    # the enumeration methods call self.plotted_asset_class_map() internally
    fake.plotted_asset_class_map = lambda: CotIndexer.plotted_asset_class_map(fake)
    return fake


def test_get_assets_for_asset_class_excludes_heldout_by_default():
    fake = _fake_with_map()
    assert CotIndexer.get_assets_for_asset_class(fake, "Metals") == ["Gold"]
    assert set(CotIndexer.get_assets_for_asset_class(fake, "Metals", include_heldout=True)) \
        == {"Gold", "Milk"}


def test_get_asset_classes_drops_fully_heldout_class():
    fake = _fake_with_map()
    assert CotIndexer.get_asset_classes(fake) == ["Metals"]      # Dairy (all heldout) gone
    assert set(CotIndexer.get_asset_classes(fake, include_heldout=True)) == {"Metals", "Dairy"}
