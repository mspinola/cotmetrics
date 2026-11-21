"""Compare an 0.18.0 dump (" Custom") against an 0.19.0 dump (" NPF" + " Custom" copy).

Exact equality, NaN-aware, on every column and every row. Exits 1 on any difference.

    python compare_family.py OLD_DIR NEW_DIR
"""
import sys
from pathlib import Path

import pandas as pd

old_dir, new_dir = Path(sys.argv[1]), Path(sys.argv[2])
bad, cells, frames = [], 0, 0
olds = sorted(p.name for p in old_dir.glob("*.parquet"))
news = sorted(p.name for p in new_dir.glob("*.parquet"))
if olds != news:
    bad.append(f"frame sets differ: {set(olds) ^ set(news)}")
for name in olds:
    if name not in news:
        continue
    o, n = pd.read_parquet(old_dir / name), pd.read_parquet(new_dir / name)
    frames += 1
    if len(o) != len(n):
        bad.append(f"{name}: {len(o)} rows vs {len(n)}")
        continue
    fam = [c for c in o.columns if " Custom" in c]
    if any(" NPF" in c for c in o.columns):
        bad.append(f"{name}: the old dump already has NPF columns, wrong tree?")
    for c in fam:
        for twin in (c, c.replace(" Custom", " NPF")):
            if twin not in n.columns:
                bad.append(f"{name}: missing {twin!r}")
                continue
            a, b = o[c], n[twin]
            same = (a == b) | (a.isna() & b.isna())
            cells += len(a)
            if not same.all():
                bad.append(f"{name}: {twin!r} differs on {(~same).sum()} rows")
    extra = {c for c in n.columns if " NPF" in c} - {c.replace(" Custom", " NPF") for c in fam}
    if extra:
        bad.append(f"{name}: NPF columns with no Custom original: {sorted(extra)}")
print(f"{frames} frames, {cells} cells compared")
for b in bad:
    print("DIFF", b)
sys.exit(1 if bad else 0)
