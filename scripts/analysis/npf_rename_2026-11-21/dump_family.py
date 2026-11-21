"""Dump every instrument's frozen-table family to parquet, for the 0.19.0 rename check.

Run once with the 0.18.0 tree on PYTHONPATH and once with 0.19.0, each against its own
fresh COTMETRICS_CACHE and the same COTDATA_STORE / COTMETRICS_PARAMS, then compare with
compare_family.py. The family infix was " Custom" in 0.18.0; 0.19.0 writes " NPF" and a
" Custom" copy. Both are dumped where present, keyed by infix.

    python dump_family.py OUT_DIR
"""
import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.simplefilter("ignore", DeprecationWarning)
from cotmetrics.indexer import get_indexer  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
ix = get_indexer()
n = 0
for code in sorted(ix.supported_instruments):
    inst = ix.instruments[code]
    for tag, frame in (("df", inst.df), ("emini", inst.emini_df)):
        if frame is None or frame.empty:
            continue
        cols = [c for c in frame.columns if " Custom" in c or " NPF" in c]
        keep = frame[[c for c in frame.columns if c == "Report_Date_as_MM_DD_YYYY"] + cols]
        keep.reset_index(drop=True).to_parquet(out / f"{inst.symbol}_{tag}.parquet")
        n += 1
print(f"{n} frames from {len(ix.supported_instruments)} instruments -> {out}")
