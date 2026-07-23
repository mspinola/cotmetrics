#!/usr/bin/env python3
"""Verify that installed workspace siblings satisfy this package's declared floors.

In this workspace the internal dependencies (cotdata, cotmetrics, crucible,
crucible-stack) are installed as editable checkouts of sibling repos, so pip
never checks the version constraints declared in pyproject.toml -- the install
comes from whatever HEAD the sibling happens to be on. This script closes that
gap: it reads the floors declared in THIS repo's pyproject.toml (the single
source of truth) and asserts that every internal dependency actually installed
satisfies its declared specifier.

Run it in CI right after the editable installs, and locally any time. It exits
non-zero with a clear message if a floor is unmet, so a stale sibling or a
lying pin fails loudly here instead of at runtime in a consumer.

Usage: python scripts/check_dep_floors.py
"""
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python < 3.11 (provided via the `dev` extra)
    import tomli as tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

# The workspace's own packages. Only these are installed from editable siblings
# rather than a package index, so only these need the extra check.
INTERNAL = {
    "cotdata",
    "cotmetrics",
    "crucible",
    "crucible-stack",
    "npf",
    "livebook",
    "cot-analyzer",
}
_INTERNAL_CANON = {canonicalize_name(name) for name in INTERNAL}

# pyproject.toml sits one level up from this scripts/ directory, regardless of cwd.
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def main() -> int:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    name = project.get("name", PYPROJECT.parent.name)
    declared = project.get("dependencies", [])

    failures = []
    checked = []
    for raw in declared:
        req = Requirement(raw)
        if canonicalize_name(req.name) not in _INTERNAL_CANON:
            continue
        try:
            installed = version(req.name)
        except PackageNotFoundError:
            failures.append(f"  {req.name}: declared '{req.specifier}' but NOT installed")
            continue
        if req.specifier.contains(installed, prereleases=True):
            checked.append(f"  {req.name} {installed} satisfies '{req.specifier}'")
        else:
            failures.append(
                f"  {req.name}: installed {installed} does NOT satisfy declared "
                f"'{req.specifier}'"
            )

    if checked:
        print(f"{name}: internal dependency floors OK")
        for line in checked:
            print(line)
    if failures:
        print(f"\n{name}: internal dependency floor check FAILED", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    if not checked:
        print(f"{name}: no internal dependencies declared (nothing to check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
