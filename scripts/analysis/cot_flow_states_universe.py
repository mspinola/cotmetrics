"""COT flow states across the 42-market non-heldout universe: the gold design replicated
unchanged, one market at a time, then pooled.

Origin: docs/analysis/2026-09-26-cot-flow-states-gold.md and its reproducer
scripts/analysis/cot_flow_states.py. This script is a replication at a FIXED configuration,
not a search. Every parameter below was fixed before any universe result was seen and is
identical to the gold script:

  Z_WIN = 52, Z_MIN = 26, Z_ACT = 1.0, horizons 4 and 13 weeks
  z_c      = dNet_c / rolling_std(dNet_c, 52w, min 26w)          (no mean subtraction)
  active   = |z_c| > 1.0
  state    = (sign z_TREND, sign z_VALUE, sign z_RETAIL), 0 when not active
  straddle = dGross_c > 2 * rolling_std(dGross_c) and |dNet_c| < 0.25 * dGross_c
  derisk   = dSpread_TREND > 1 * rolling_std(dSpread_TREND) and dNet_TREND < 0

Cohort roles per report, fixed before results. The gold script names the three opinion
cohorts MM / Other / NonRep; here they are generic so the same state vocabulary spans both
reports (the gold state NAMES are kept verbatim for comparability, so "MM_ALONE_BUY" reads
as "TREND_ALONE_BUY" on a TFF market):

  role          disagg (physical commodities)         tff (financials)
  TREND         managed_money                         leveraged
  VALUE         other_reportable                      asset_manager
  RETAIL        nonreportable                         nonreportable
  COUNTERPARTY  producer_merchant + swap              dealer
  OTHER         (not carried)                         other_reportable, dNet and z only,
                                                      NOT in the state

Forward returns are log returns of the Tuesday close on the report date, from the
cot-analyzer price cache, exactly as the gold script measures them. The COT release is the
Friday after, so those returns include three sessions during which the positions were not
public. An optional diagnostic re-anchors the 13-week return at the first daily close on or
after report_date + 3 days, using the marketdata futures store, for two pooled rows only.

Statistics: n, mean, median, hit rate, the plain t the gold doc reports, and a Newey-West
HAC t (Bartlett kernel, lag h-1, computed within each market and summed across markets)
because h-week returns sampled weekly overlap.

Variants NOT tried here (threshold 0.5, 26-week window, 8-week horizon, two-cohort states,
levels instead of changes) must go into a SearchSpaceLog before any claim about them. This
run records one 'tried' entry per (market, report, fixed params) so the denominator of any
later gauntlet includes the 42 markets looked at.

Usage:
  COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \\
  COTMETRICS_PARAMS=~/code/trading_workspace/cotmetrics-config/params.yaml \\
  python scripts/analysis/cot_flow_states_universe.py \\
      --params ../cotmetrics-config/params.yaml \\
      --prices ../cot-analyzer/data_cache --out docs/analysis
"""

import argparse
import json
import os
import sys
import time
import traceback

import cotdata
import numpy as np
import pandas as pd
import yaml
from crucible.validation import SearchSpaceLog

from cotmetrics import categories as cat

PREFIX = "2026-09-26-cot-flow-states-universe"
SCOPE = "cot_flow_states:universe-2026-09-26"

Z_WIN, Z_MIN, Z_ACT = 52, 26, 1.0
HORIZONS = (4, 13)
PRICE_TOL = pd.Timedelta("3D")
RELEASE_LAG = pd.Timedelta("3D")
SMALL_OI_CONTRACTS = 100
SMALL_OI_SIGMA = 0.5

ROLES = ("TREND", "VALUE", "RETAIL", "COUNTERPARTY")
SPEC_ROLES = ("TREND", "VALUE", "RETAIL")
ROLE_MAP = {
    "disagg": {
        "TREND": ["managed_money"],
        "VALUE": ["other_reportable"],
        "RETAIL": ["nonreportable"],
        "COUNTERPARTY": ["producer_merchant", "swap"],
    },
    "tff": {
        "TREND": ["leveraged"],
        "VALUE": ["asset_manager"],
        "RETAIL": ["nonreportable"],
        "COUNTERPARTY": ["dealer"],
        "OTHER": ["other_reportable"],
    },
}
ROLE_LABELS = {
    "disagg": {"TREND": "Managed Money", "VALUE": "Other Reportable",
               "RETAIL": "Non-Reportable", "COUNTERPARTY": "Commercials (Prod+Swap)"},
    "tff": {"TREND": "Leveraged Funds", "VALUE": "Asset Manager",
            "RETAIL": "Non-Reportable", "COUNTERPARTY": "Dealer"},
}

STATE_NAMES = {
    (1, 1, 1): "BROAD_ACCUM", (1, 1, -1): "INST_BUY_RETAIL_SELL",
    (1, -1, 1): "TREND+RETAIL_BUY", (1, -1, -1): "MM_ALONE_BUY",
    (-1, 1, 1): "MM_SELL_OTHERS_BUY", (-1, 1, -1): "VALUE_ACCUM",
    (-1, -1, 1): "RETAIL_ALONE_BUY", (-1, -1, -1): "BROAD_LIQUID",
}
DIVERGENCE_STATES = ("RETAIL_ALONE_BUY", "VALUE_ACCUM")

CONFIG = dict(z_win=Z_WIN, z_min=Z_MIN, z_act=Z_ACT, horizons=list(HORIZONS),
              z_definition="dNet / rolling_std(dNet, 52w, min 26w), no mean subtraction",
              straddle="dGross > 2*rolling_std(dGross) and |dNet| < 0.25*dGross",
              derisk="dSpread_TREND > 1*rolling_std(dSpread_TREND) and dNet_TREND < 0",
              price_source="cot-analyzer/data_cache/<SYM>.parquet 'Closing Price' on the "
                           "Tuesday report date, nearest within 3 days",
              hac="Newey-West Bartlett kernel, lag h-1, within market, summed across markets",
              small_oi_flag=f"{SMALL_OI_CONTRACTS} contracts > {SMALL_OI_SIGMA} sigma of dNet "
                            "at the latest date",
              state_names_note="gold names kept verbatim; MM_* reads as TREND_* on tff")


# --- universe -------------------------------------------------------------------------

def load_universe(params_path):
    """[(asset_class, symbol, name)] from params.yaml, skipping Role: heldout."""
    with open(params_path) as fh:
        cfg = yaml.safe_load(fh)
    default_role = (cfg.get("roles") or {}).get("default", "deploy")
    out = []
    for block in cfg["AssetClasses"]:
        for klass, items in block.items():
            class_role = (cfg.get("roles") or {}).get(klass, default_role)
            for it in items:
                role = it.get("Role", class_role)
                if role == "heldout":
                    continue
                out.append((klass, it["Symbol"], it["Name"]))
    return out


def load_positions(symbol):
    """(report, frame): whichever of disagg / tff the store serves for this symbol."""
    for report in ("disagg", "tff"):
        df = cotdata.get_cot(symbol, report=report)
        if df is not None and len(df):
            return report, df.sort_index()
    raise ValueError("no disagg or tff rows in the store")


def load_prices(prices_dir, symbol):
    px = pd.read_parquet(os.path.join(prices_dir, f"{symbol}.parquet"))
    px = px[["Report_Date_as_MM_DD_YYYY", "Closing Price"]].copy()
    px.columns = ["date", "close"]
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna().drop_duplicates("date").set_index("date")["close"].astype(float)
    # The cache column is an ADDITIVELY back-adjusted series and goes non-positive on long
    # commodity histories (HO, OJ, RB, ZM, ZS, CT, HE, ZL, KC, CC, CL). A log return is
    # undefined there and explodes near zero, so those closes are masked and counted; the
    # ratio-adjusted marketdata tier is run beside it as a price-basis check.
    nonpos = int((px <= 0).sum())
    px = px.where(px > 0)
    return px.sort_index(), nonpos


# --- derivation, the gold design ------------------------------------------------------

def _roll_std(s):
    return s.rolling(Z_WIN, min_periods=Z_MIN).std()


def derive(raw, report):
    """Per-role dNet / dGross / z / flags / state for one market. Mirrors the gold derive()."""
    specs = {s.key: s for s in cat.categories_for(report)}
    out = pd.DataFrame(index=pd.DatetimeIndex(raw.index).rename("date"))
    oi = cat._numeric(cat._resolve(raw, "Open_Interest_All"))
    out["OI"] = oi

    per_key = {}
    spread_total = pd.Series(0.0, index=out.index)
    for key, spec in specs.items():
        lo = cat._numeric(cat._resolve(raw, spec.long_col))
        sh = cat._numeric(cat._resolve(raw, spec.short_col))
        if lo is None or sh is None:
            raise ValueError(f"category {key} missing long/short columns")
        lo, sh = lo.astype(float), sh.astype(float)
        sp = cat._numeric(cat._resolve(raw, spec.spread_col))
        if sp is not None:
            spread_total = spread_total + sp.astype(float).fillna(0)
        per_key[key] = dict(net=lo - sh, dnet=(lo - sh).diff(),
                            dgross=lo.diff().abs() + sh.diff().abs(),
                            dspread=sp.astype(float).diff() if sp is not None else None)
    out["OI_less_spread"] = out["OI"] - spread_total
    # identity: every long has a short, so the sum of dNet over ALL categories is 0
    out["identity"] = sum(v["dnet"] for v in per_key.values())

    for role, keys in ROLE_MAP[report].items():
        dnet = sum(per_key[k]["dnet"] for k in keys)
        dgross = sum(per_key[k]["dgross"] for k in keys)
        out[f"net_{role}"] = sum(per_key[k]["net"] for k in keys)
        out[f"dNet_{role}"] = dnet
        out[f"dGross_{role}"] = dgross
        out[f"z_{role}"] = dnet / _roll_std(dnet)
        gsd = _roll_std(dgross)
        out[f"straddle_{role}"] = (dgross > 2 * gsd) & (dnet.abs() < 0.25 * dgross)
        dsp = per_key[keys[0]]["dspread"] if len(keys) == 1 else None
        if dsp is not None:
            out[f"dSpread_{role}"] = dsp
    for role in ROLES:
        if f"z_{role}" not in out:
            out[f"z_{role}"] = np.nan
    if "z_OTHER" not in out:
        out["z_OTHER"] = np.nan

    dsp = out.get("dSpread_TREND")
    if dsp is not None:
        out["derisk_TREND"] = (dsp > _roll_std(dsp)) & (out["dNet_TREND"] < 0)
    else:
        out["derisk_TREND"] = False

    def sign(z):
        return np.where(z > Z_ACT, 1, np.where(z < -Z_ACT, -1, 0))

    for role in SPEC_ROLES:
        out[f"s_{role}"] = sign(out[f"z_{role}"])
    out["n_active"] = (out[[f"s_{r}" for r in SPEC_ROLES]] != 0).sum(axis=1)
    out["state"] = [STATE_NAMES.get((a, b, c), "PARTIAL" if (a, b, c) != (0, 0, 0) else "QUIET")
                    for a, b, c in zip(out["s_TREND"], out["s_VALUE"], out["s_RETAIL"])]
    return out


def attach_returns(out, px):
    p = px.reindex(out.index, method="nearest", tolerance=PRICE_TOL)
    out["close"] = p
    lp = np.log(p)
    for h in HORIZONS:
        out[f"fwd{h}"] = lp.shift(-h) - lp
    return out


# --- statistics -----------------------------------------------------------------------

def hac_se(values, groups, lag):
    """Newey-West (Bartlett) standard error of the pooled mean.

    `values` and `groups` are aligned arrays already sorted by (group, time). The long-run
    variance is computed within each group on residuals from the POOLED mean and summed,
    so a lag never straddles two markets. With one group this is the textbook estimator.
    """
    x = np.asarray(values, dtype=float)
    g = np.asarray(groups)
    n = len(x)
    if n < 3:
        return np.nan
    e = x - x.mean()
    s = 0.0
    for grp in pd.unique(g):
        r = e[g == grp]
        m = len(r)
        s += float(np.dot(r, r))
        for k in range(1, min(lag, m - 1) + 1):
            w = 1.0 - k / (lag + 1.0)
            s += 2.0 * w * float(np.dot(r[k:], r[:-k]))
    return np.sqrt(max(s, 0.0)) / n


def stats_row(sub, col, h, extra=None):
    """One table row: n, mean, median, hit, plain t, HAC t. `sub` sorted by (symbol, date)."""
    r = sub[col].dropna()
    row = dict(extra or {})
    row.update(n=int(len(r)), mean=r.mean() * 100 if len(r) else np.nan,
               median=r.median() * 100 if len(r) else np.nan,
               hit=(r > 0).mean() * 100 if len(r) else np.nan)
    if len(r) > 2:
        row["t"] = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
        se = hac_se(r.values, sub.loc[r.index, "symbol"].values, h - 1)
        row["t_hac"] = r.mean() / se if se and se > 0 else np.nan
    else:
        row["t"] = np.nan
        row["t_hac"] = np.nan
    return row


def state_table(pool, h):
    col = f"fwd{h}"
    rows = [stats_row(g, col, h, dict(state=st)) for st, g in pool.groupby("state", sort=False)]
    rows = [r for r in rows if r["n"] > 0]
    rows.append(stats_row(pool, col, h, dict(state="ALL")))
    return pd.DataFrame(rows).set_index("state").sort_values("n", ascending=False)


def single_cohort_table(pool, h):
    col = f"fwd{h}"
    rows = []
    for role in SPEC_ROLES:
        for s, lab in ((1, "buy"), (-1, "sell")):
            sub = pool[pool[f"s_{role}"] == s]
            rows.append(stats_row(sub, col, h, dict(role=role, move=lab)))
    return pd.DataFrame(rows)


def per_market_value_accum(pool, h=13):
    col = f"fwd{h}"
    rows = []
    for sym, g in pool.groupby("symbol", sort=False):
        base = g[col].dropna()
        va = g.loc[g["state"] == "VALUE_ACCUM", col].dropna()
        rows.append(dict(symbol=sym, asset_class=g["asset_class"].iloc[0], report=g["report"].iloc[0],
                         n=int(len(va)), mean=va.mean() * 100 if len(va) else np.nan,
                         hit=(va > 0).mean() * 100 if len(va) else np.nan,
                         uncond_n=int(len(base)), uncond_mean=base.mean() * 100,
                         above_uncond=bool(len(va) and va.mean() > base.mean())))
    return pd.DataFrame(rows).set_index("symbol")


# --- Friday-anchored diagnostic (optional) --------------------------------------------

def marketdata_returns(out, symbol, weeks=13):
    """Two things from the ratio-adjusted (propadj) marketdata daily close, which preserves
    percent returns and stays positive where the additive cache series does not:

    fwd13_fri : 13w log return from the first daily close ON OR AFTER report_date + 3 days
                (the Friday release) to the first daily close on or after anchor + 13 weeks.
    fwd4_pa, fwd13_pa : the gold design's Tuesday-anchored returns, same 3-day nearest
                reindex, on this price basis instead of the cache (price-basis check)."""
    from marketdata import get_bars

    bars = get_bars(symbol, "propadj", domain="futures")
    close = bars["Close"].astype(float)
    close = close[close > 0].dropna().sort_index()
    idx = close.index
    res = pd.DataFrame(index=out.index)
    p = close.reindex(out.index, method="nearest", tolerance=PRICE_TOL)
    lp = np.log(p)
    for h in HORIZONS:
        res[f"fwd{h}_pa"] = lp.shift(-h) - lp
    anchors = pd.DatetimeIndex(out.index) + RELEASE_LAG
    ends = anchors + pd.Timedelta(weeks=weeks)
    ia = idx.searchsorted(anchors, side="left")
    ie = idx.searchsorted(ends, side="left")
    vals = np.full(len(out), np.nan)
    ok = (ia < len(idx)) & (ie < len(idx))
    # the anchor must land within a week of the release, or the bar history does not cover it
    la = np.where(ok, idx.values[np.minimum(ia, len(idx) - 1)], np.datetime64("NaT"))
    ok &= (pd.DatetimeIndex(la) - anchors) <= pd.Timedelta("7D")
    vals[ok] = np.log(close.values[ie[ok]]) - np.log(close.values[ia[ok]])
    res["fwd13_fri"] = vals
    return res


# --- figures ----------------------------------------------------------------------------

BG, PAN, DIM, TXT = "#0e1116", "#12161c", "#8b97a5", "#d9e0e8"


def plot_class(frames, klass, members, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    members = [m for m in members if m in frames]
    if not members:
        return None
    n = 52
    fig, axes = plt.subplots(len(members), 1, figsize=(15, 1.35 * len(members) + 1.2),
                             sharex=False, squeeze=False)
    fig.patch.set_facecolor(BG)
    norm = TwoSlopeNorm(vcenter=0, vmin=-3, vmax=3)
    im = None
    for ax, sym in zip(axes[:, 0], members):
        out = frames[sym]["frame"]
        report = frames[sym]["report"]
        last = out.iloc[-n:]
        Z = np.vstack([last[f"z_{r}"].values for r in ROLES])
        ax.set_facecolor(PAN)
        im = ax.imshow(Z, aspect="auto", cmap="RdBu", norm=norm)
        labs = [ROLE_LABELS[report][r] for r in ROLES]
        ax.set_yticks(range(len(ROLES)))
        ax.set_yticklabels(labs, color=TXT, fontsize=7.5)
        ax.tick_params(colors=DIM, labelsize=7.5, length=2)
        for i, st in enumerate(last["state"]):
            if st in DIVERGENCE_STATES:
                ax.add_patch(plt.Rectangle((i - .5, -.5), 1, len(ROLES), fill=False,
                                           ec="#f0c14b", lw=1.4))
        ax.set_title(f"{sym}  {frames[sym]['name']}  ({report})", color="#fff", loc="left",
                     fontsize=9.5, pad=3)
        if ax is axes[-1, 0]:
            xt = list(range(0, len(last), 4))
            ax.set_xticks(xt)
            ax.set_xticklabels([last.index[i].strftime("%b %d") for i in xt], color=DIM,
                               fontsize=8)
            ax.set_xlabel("report date (Tuesday)", color=DIM)
        else:
            ax.set_xticks([])
    cb = fig.colorbar(im, ax=axes[:, 0].tolist(), fraction=.015, pad=.01)
    cb.set_label("dNet / 52w std", color=DIM)
    plt.setp(cb.ax.get_yticklabels(), color=DIM)
    fig.suptitle(f"{klass}: week-over-week net change by cohort, last 52 weeks "
                 "(gold box = a divergence state)", color="#fff", x=0.01, ha="left",
                 fontsize=12)
    slug = klass.lower().replace(" ", "_")
    path = os.path.join(outdir, f"{PREFIX}-{slug}.png")
    plt.savefig(path, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close()
    return path


def plot_board(board, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    b = board.reset_index()
    Z = b[[f"z_{r}" for r in ROLES]].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(11, 0.32 * len(b) + 1.6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PAN)
    im = ax.imshow(Z, aspect="auto", cmap="RdBu", norm=TwoSlopeNorm(vcenter=0, vmin=-3, vmax=3))
    ax.set_xticks(range(len(ROLES)))
    ax.set_xticklabels(ROLES, color=TXT, fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(b)))
    ax.set_yticklabels([f"{r.asset_class}  {r.symbol}" for r in b.itertuples()], color=TXT,
                       fontsize=8)
    ax.tick_params(colors=DIM, length=0)
    for i, r in enumerate(b.itertuples()):
        for j, role in enumerate(ROLES):
            v = getattr(r, f"z_{role}")
            if pd.notna(v):
                ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=7,
                        color="#000" if abs(v) < 1.6 else "#fff")
        st = r.state
        colour = "#f0c14b" if st in DIVERGENCE_STATES else (DIM if st in ("QUIET", "PARTIAL") else TXT)
        ax.text(len(ROLES) - 0.4, i, f"{st}   {pd.Timestamp(r.date).strftime('%Y-%m-%d')}",
                va="center", ha="left", fontsize=7.5, color=colour)
    # separators between asset classes
    prev = None
    for i, k in enumerate(b["asset_class"]):
        if prev is not None and k != prev:
            ax.axhline(i - .5, color=BG, lw=2)
        prev = k
    ax.set_xlim(-.5, len(ROLES) + 3.2)
    for s in ("top", "right", "bottom", "left"):
        ax.spines[s].set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=.02, pad=.16)
    cb.set_label("latest week dNet / 52w std", color=DIM)
    plt.setp(cb.ax.get_yticklabels(), color=DIM)
    ax.set_title("Cross-asset flow board: latest report week, z per role, state annotated "
                 "(gold = divergence state)", color="#fff", loc="left", fontsize=11, pad=22)
    path = os.path.join(outdir, f"{PREFIX}-board.png")
    plt.savefig(path, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close()
    return path


# --- driver -----------------------------------------------------------------------------

def _jsonable(df, index=True):
    d = df.reset_index() if index else df
    recs = d.to_dict(orient="records")
    for r in recs:
        for k, v in list(r.items()):
            if isinstance(v, (pd.Timestamp, np.datetime64)):
                r[k] = str(pd.Timestamp(v).date())
            elif isinstance(v, (np.integer,)):
                r[k] = int(v)
            elif isinstance(v, (np.floating, float)):
                r[k] = None if pd.isna(v) else float(v)
            elif isinstance(v, (np.bool_,)):
                r[k] = bool(v)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True)
    ap.add_argument("--prices", required=True, help="cot-analyzer/data_cache directory")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-friday", action="store_true", help="skip the marketdata diagnostic")
    a = ap.parse_args()
    t0 = time.time()
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.float_format", lambda v: f"{v:,.2f}")

    universe = load_universe(a.params)
    print(f"universe: {len(universe)} non-heldout markets from {a.params}")
    print("role mapping (fixed before results):")
    for rep, m in ROLE_MAP.items():
        print(f"  {rep:7s} " + "  ".join(f"{k}={'+'.join(v)}" for k, v in m.items()))
    print()

    log = SearchSpaceLog(scope=SCOPE, path=os.path.join(a.out, f"{PREFIX}.searchlog.jsonl"))

    frames, skipped, per_market = {}, [], []
    for klass, sym, name in universe:
        try:
            report, raw = load_positions(sym)
            px, nonpos = load_prices(a.prices, sym)
            out = attach_returns(derive(raw, report), px)
        except Exception as exc:  # noqa: BLE001 - a broken market must not sink the run
            msg = f"{type(exc).__name__}: {exc}"
            print(f"SKIP {sym} ({klass}): {msg}")
            skipped.append(dict(symbol=sym, asset_class=klass, reason=msg))
            continue
        out["symbol"], out["report"], out["asset_class"] = sym, report, klass
        frames[sym] = dict(frame=out, report=report, name=name, klass=klass)
        log.record(dict(symbol=sym, report=report, **CONFIG), status="tried")
        latest = out.index.max()
        diag = dict(symbol=sym, asset_class=klass, report=report, weeks=int(len(out)),
                    first=str(out.index.min().date()), last=str(latest.date()),
                    priced=int(out["close"].notna().sum()), cache_nonpos_closes=nonpos,
                    big_fwd13=int((out["fwd13"].abs() > 0.5).sum()),
                    identity_max_abs=float(out["identity"].abs().max()),
                    latest_oi=float(out["OI"].iloc[-1]))
        for role in ROLES:
            d = out[f"dNet_{role}"]
            diag[f"ac1_{role}"] = float(d.autocorr(1)) if d.notna().sum() > 30 else np.nan
            sd = float(_roll_std(d).iloc[-1])
            diag[f"sd52_{role}"] = sd
            diag[f"small_oi_{role}"] = bool(SMALL_OI_CONTRACTS > SMALL_OI_SIGMA * sd) if pd.notna(sd) else True
        diag["straddle_TREND"] = int(out["straddle_TREND"].sum())
        diag["straddle_VALUE"] = int(out["straddle_VALUE"].sum())
        diag["straddle_RETAIL"] = int(out["straddle_RETAIL"].sum())
        diag["derisk_TREND"] = int(out["derisk_TREND"].sum())
        per_market.append(diag)

    diag_df = pd.DataFrame(per_market).set_index("symbol")
    print(f"loaded {len(frames)} markets, skipped {len(skipped)}  ({time.time() - t0:.0f}s)\n")

    keep = (["symbol", "report", "asset_class", "close"] + [f"z_{r}" for r in ROLES] + ["z_OTHER"]
            + [f"s_{r}" for r in SPEC_ROLES]
            + ["state", "n_active", "straddle_TREND", "straddle_VALUE", "straddle_RETAIL",
               "derisk_TREND", "identity"] + [f"fwd{h}" for h in HORIZONS])
    pool = pd.concat([f["frame"][keep] for f in frames.values()])
    pool.index.name = "date"
    pool = pool.reset_index().sort_values(["symbol", "date"]).reset_index(drop=True)

    # --- identity + diagnostics
    print("== identity check: max |sum dNet over all categories| per market (contracts) ==")
    print(diag_df["identity_max_abs"].to_string())
    print(f"  overall max = {diag_df['identity_max_abs'].max():.0f}\n")
    print("== lag-1 autocorrelation of dNet per role ==")
    ac_cols = [f"ac1_{r}" for r in ROLES]
    print(diag_df[["report"] + ac_cols].to_string())
    print("  median:", diag_df[ac_cols].median().round(3).to_dict(), "\n")
    print("== 52w std of dNet at the latest date, and small-OI flag (100 contracts > 0.5 sigma) ==")
    sd_cols = [f"sd52_{r}" for r in ROLES]
    so_cols = [f"small_oi_{r}" for r in ROLES]
    print(diag_df[["latest_oi"] + sd_cols + so_cols].to_string())
    small = diag_df[so_cols].any(axis=1)
    print(f"  markets with any small-OI flag: {int(small.sum())} -> {list(diag_df.index[small])}\n")
    print("== price basis: non-positive cache closes (masked) and |fwd13| > 50% weeks per market ==")
    hz = diag_df[["weeks", "priced", "cache_nonpos_closes", "big_fwd13"]]
    print(hz[(hz["cache_nonpos_closes"] > 0) | (hz["big_fwd13"] > 0)].to_string())
    print()

    # --- pooled tables
    tables = {}
    for label, sub in (("disagg", pool[pool["report"] == "disagg"]),
                       ("tff", pool[pool["report"] == "tff"]), ("all", pool)):
        if sub.empty:
            continue
        freq = sub["state"].value_counts()
        print(f"==== POOLED {label.upper()}: {sub['symbol'].nunique()} markets, "
              f"{len(sub)} market-weeks, {sub['fwd13'].notna().sum()} with fwd13 ====")
        print("-- state frequency --")
        fq = pd.DataFrame(dict(n=freq, pct=freq / freq.sum() * 100))
        print(fq.to_string())
        tables[label] = dict(state_frequency=_jsonable(fq.rename_axis("state")))
        for h in HORIZONS:
            st = state_table(sub, h)
            print(f"-- forward {h}w log return (%) by state --")
            print(st.to_string())
            tables[label][f"by_state_fwd{h}"] = _jsonable(st)
        sc = single_cohort_table(sub, 13)
        print("-- single-cohort baseline, fwd 13w --")
        print(sc.to_string(index=False))
        tables[label]["single_cohort_fwd13"] = _jsonable(sc, index=False)
        print()

    # --- per-market VALUE_ACCUM read
    pm = per_market_value_accum(pool, 13)
    print("== per-market VALUE_ACCUM at 13w vs the market's own unconditional mean (%) ==")
    print(pm.to_string())
    elig = pm[pm["n"] >= 5]
    sign_up = int(elig["above_uncond"].sum())
    print(f"\n  sign count (n>=5): {sign_up} of {len(elig)} markets have VALUE_ACCUM mean above "
          f"their own unconditional mean; {len(pm) - len(elig)} markets have n<5\n")

    # --- latest board
    latest_rows = []
    for sym, f in frames.items():
        o = f["frame"]
        last = o.iloc[-1]
        latest_rows.append(dict(asset_class=f["klass"], symbol=sym, report=f["report"],
                                date=o.index[-1], state=last["state"],
                                **{f"z_{r}": float(last[f"z_{r}"]) for r in ROLES},
                                z_OTHER=float(last["z_OTHER"]),
                                straddle_RETAIL=bool(last["straddle_RETAIL"]),
                                derisk_TREND=bool(last["derisk_TREND"])))
    board = pd.DataFrame(latest_rows)
    order = {k: i for i, k in enumerate(dict.fromkeys(u[0] for u in universe))}
    board["_o"] = board["asset_class"].map(order)
    board = board.sort_values(["_o", "symbol"]).drop(columns="_o").set_index("symbol")
    print("== latest week: state and z per role for every market ==")
    print(board.to_string())
    print()

    print("== flag counts per market ==")
    print(diag_df[["report", "weeks", "straddle_TREND", "straddle_VALUE", "straddle_RETAIL",
                   "derisk_TREND"]].to_string())
    print()

    # --- marketdata diagnostics: Friday anchor, and the price-basis check
    friday = dict(ran=False)
    basis = dict(ran=False)
    if not a.no_friday:
        tf = time.time()
        try:
            cols = []
            for sym, f in frames.items():
                r = marketdata_returns(f["frame"], sym, 13)
                r["symbol"] = sym
                cols.append(r.reset_index())
                if time.time() - tf > 900:
                    raise TimeoutError("marketdata diagnostic exceeded 15 minutes")
            md = pd.concat(cols)
            pf = pool.merge(md, on=["symbol", "date"], how="left")
            covered = int(md.groupby("symbol")["fwd13_pa"].apply(lambda x: x.notna().any()).sum())
            va = pf[pf["state"] == "VALUE_ACCUM"]
            rows = [stats_row(va, "fwd13_fri", 13, dict(row="VALUE_ACCUM", anchor="friday")),
                    stats_row(pf, "fwd13_fri", 13, dict(row="ALL", anchor="friday")),
                    stats_row(va, "fwd13_pa", 13, dict(row="VALUE_ACCUM", anchor="tuesday_propadj")),
                    stats_row(pf, "fwd13_pa", 13, dict(row="ALL", anchor="tuesday_propadj")),
                    stats_row(va, "fwd13", 13, dict(row="VALUE_ACCUM", anchor="tuesday_cache")),
                    stats_row(pf, "fwd13", 13, dict(row="ALL", anchor="tuesday_cache"))]
            ft = pd.DataFrame(rows)
            print("== Friday-anchored 13w diagnostic (marketdata propadj daily close, first close "
                  "on or after report date + 3 days) beside the two Tuesday anchors, pooled ALL ==")
            print(ft.to_string(index=False))
            print(f"  markets covered by marketdata: {covered}  ({time.time() - tf:.0f}s)\n")
            friday = dict(ran=True, table=_jsonable(ft, index=False), markets_covered=covered,
                          rows_with_friday_return=int(pf["fwd13_fri"].notna().sum()),
                          tier="propadj", anchor_rule="first daily close >= report_date + 3 days, "
                          "end = first daily close >= anchor + 13 weeks")
            log.record(dict(diagnostic="friday_anchored_fwd13", tier="propadj",
                            anchor="report_date+3d", rows=["VALUE_ACCUM", "ALL"], **CONFIG),
                       status="tried")

            # price-basis check: the gold tables again on the ratio-adjusted Tuesday close
            pa = pf.drop(columns=[f"fwd{h}" for h in HORIZONS]).rename(
                columns={f"fwd{h}_pa": f"fwd{h}" for h in HORIZONS})
            btabs = {}
            for label, sub in (("disagg", pa[pa["report"] == "disagg"]),
                               ("tff", pa[pa["report"] == "tff"]), ("all", pa)):
                if sub.empty:
                    continue
                print(f"==== PRICE-BASIS CHECK, POOLED {label.upper()} on marketdata propadj "
                      f"Tuesday close: {sub['fwd13'].notna().sum()} market-weeks with fwd13 ====")
                btabs[label] = {}
                for h in HORIZONS:
                    st = state_table(sub, h)
                    print(f"-- forward {h}w log return (%) by state --")
                    print(st.to_string())
                    btabs[label][f"by_state_fwd{h}"] = _jsonable(st)
                sc = single_cohort_table(sub, 13)
                print("-- single-cohort baseline, fwd 13w --")
                print(sc.to_string(index=False))
                btabs[label]["single_cohort_fwd13"] = _jsonable(sc, index=False)
                print()
            pm_pa = per_market_value_accum(pa, 13)
            pm["mean_propadj"] = pm_pa["mean"]
            pm["uncond_mean_propadj"] = pm_pa["uncond_mean"]
            pm["above_uncond_propadj"] = pm_pa["above_uncond"]
            elig_pa = pm_pa[pm_pa["n"] >= 5]
            sign_up_pa = int(elig_pa["above_uncond"].sum())
            print("== per-market VALUE_ACCUM at 13w, cache basis beside propadj basis (%) ==")
            print(pm[["report", "n", "mean", "uncond_mean", "above_uncond", "mean_propadj",
                      "uncond_mean_propadj", "above_uncond_propadj"]].to_string())
            print(f"\n  sign count on propadj basis (n>=5): {sign_up_pa} of {len(elig_pa)} markets\n")
            basis = dict(ran=True, pooled=btabs, per_market_value_accum_fwd13=_jsonable(pm_pa),
                         sign_count=dict(n_min=5, above=sign_up_pa, eligible=int(len(elig_pa)),
                                         total=int(len(pm_pa))))
            log.record(dict(diagnostic="price_basis_check", tier="propadj", anchor="tuesday",
                            **CONFIG), status="tried")
            pool = pf
        except Exception as exc:  # noqa: BLE001 - optional, skip cleanly
            print(f"marketdata diagnostics SKIPPED: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=2, file=sys.stdout)
            friday = dict(ran=False, reason=f"{type(exc).__name__}: {exc}")
            basis = dict(ran=False, reason=f"{type(exc).__name__}: {exc}")
            print()

    # --- figures
    figures = []
    by_class = {}
    for klass, sym, _ in universe:
        by_class.setdefault(klass, []).append(sym)
    for klass, members in by_class.items():
        p = plot_class(frames, klass, members, a.out)
        if p:
            figures.append(p)
    figures.append(plot_board(board, a.out))

    # --- outputs
    parquet_path = os.path.join(a.out, f"{PREFIX}.parquet")
    pool.to_parquet(parquet_path, index=False)
    summary = dict(
        generated=pd.Timestamp.now().isoformat(timespec="seconds"),
        origin="docs/analysis/2026-09-26-cot-flow-states-gold.md",
        config=CONFIG, role_map=ROLE_MAP, role_labels=ROLE_LABELS,
        state_names={"/".join(map(str, k)): v for k, v in STATE_NAMES.items()},
        universe=[dict(asset_class=k, symbol=s, name=n) for k, s, n in universe],
        loaded=list(frames), skipped=skipped,
        identity_max_abs_overall=float(diag_df["identity_max_abs"].max()),
        diagnostics=_jsonable(diag_df),
        median_ac1={r: float(diag_df[f"ac1_{r}"].median()) for r in ROLES},
        small_oi_markets=list(diag_df.index[small]),
        pooled=tables,
        per_market_value_accum_fwd13=_jsonable(pm),
        sign_count=dict(n_min=5, above=sign_up, eligible=int(len(elig)), total=int(len(pm))),
        latest_board=_jsonable(board),
        friday_anchored=friday,
        price_basis_check=basis,
        figures=figures, parquet=parquet_path,
        search_log=dict(path=log.path, n_variants=log.n_variants,
                        session_n_variants=log.session_n_variants),
    )
    json_path = os.path.join(a.out, f"{PREFIX}.json")
    with open(json_path, "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    print(f"SearchSpaceLog n_variants = {log.n_variants} (this session {log.session_n_variants})")
    print(f"wrote {json_path}\n      {parquet_path}\n      {len(figures)} figures")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
