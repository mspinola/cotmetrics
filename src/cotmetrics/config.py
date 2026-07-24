"""
cotmetrics.config — filesystem locations for the metrics layer.

As an installed package cotmetrics can't anchor paths to a repo checkout, so
locations come from env vars (mirroring cotdata's COTDATA_STORE convention) with
per-user defaults:

  COTMETRICS_CACHE   derived per-instrument parquet cache (also `constants.CACHE_DIR`)
  COTMETRICS_PARAMS  instrument/params config; defaults to the packaged SAMPLE params.yaml
  COTMETRICS_DATA    real_test_data (fixture) exports
"""
import logging as _logging
import os
from importlib import resources
from pathlib import Path

import cotmetrics.constants as _const

_sample_params_warned = False


def cache_dir() -> str:
    """Derived-cache directory (per-instrument parquet). Same value as constants.CACHE_DIR."""
    return _const.CACHE_DIR


def citpy_dir() -> str:
    return _const.CITPY_DIR


def data_dir() -> str:
    """Working data dir for real_test_data (fixture) exports."""
    d = os.environ.get("COTMETRICS_DATA")
    return d if d else str(Path(cache_dir()).parent / "cotmetrics_data")


def params_path() -> str:
    """Path to the instrument/params config. Defaults to the generic SAMPLE
    params.yaml shipped with the package; override with COTMETRICS_PARAMS to
    supply a real instrument universe."""
    p = os.environ.get("COTMETRICS_PARAMS")
    if p:
        return p
    global _sample_params_warned
    if not _sample_params_warned:
        _sample_params_warned = True
        _logging.getLogger("cotmetrics").warning(
            "COTMETRICS_PARAMS is not set; using the packaged SAMPLE params.yaml "
            "(a small generic universe with untuned lookbacks). Point "
            "COTMETRICS_PARAMS at a real config for production use."
        )
    return str(resources.files("cotmetrics") / "params.yaml")
