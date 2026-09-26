import os
import warnings, json
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import cotdata
from cotdata import get_cot, store
from cotdata.registry import REGISTRY, hist_code_scales
from cotmetrics import categories as cat
print("cotdata", cotdata.__file__)
print("cotmetrics.categories", cat.__file__)

DISAGG = "GF HE LE CT CC KC LBR OJ SB HG GC PA PL SI CL NG RB HO ZC ZS ZM ZL ZW".split()
TFF = "ZB ZN ZF ZT YM NQ RTY ES BTC ETH 6A 6B 6C 6S 6E 6J 6M 6N DX".split()
TRIPLE = {"disagg": ["managed_money", "other_reportable", "nonreportable"],
          "tff": ["leveraged", "asset_manager", "nonreportable"]}
W, MP = 52, 26

def legs(df, report):
    """per-category long/short/spread as float series (spread None when the spec has no leg)"""
    out = {}
    for s in cat.categories_for(report):
        lo = cat._numeric(cat._resolve(df, s.long_col)).astype(float)
        sh = cat._numeric(cat._resolve(df, s.short_col)).astype(float)
        sp = None
        if s.spread_col:
            r = cat._resolve(df, s.spread_col)
            sp = cat._numeric(r).astype(float) if r is not None else None
        out[s.key] = (lo, sh, sp)
    return out

rows = []; ac = {"disagg": {}, "tff": {}}; ac_lvl = {"disagg": {}, "tff": {}}
ident = {}
for report, syms in (("disagg", DISAGG), ("tff", TFF)):
    for sym in syms:
        df = get_cot(sym, report=report)
        if df.empty:
            rows.append(dict(sym=sym, report=report, rows=0)); continue
        idx = pd.DatetimeIndex(df.index)
        gaps = pd.Series(idx).diff().dt.days
        big = gaps[gaps > 8]
        reg = REGISTRY[sym]
        stitched = False; seam_notes = []
        if reg.hist_codes:
            fn = {"disagg": store.read_cot_disagg, "tff": store.read_cot_tff}[report]
            prim = fn(f"{sym}_{reg.cftc_code}")
            for hc, scale in hist_code_scales(reg.hist_codes):
                h = fn(f"{sym}_{hc}")
                if h.empty: continue
                stitched = True
                pi, hi = pd.DatetimeIndex(prim.index), pd.DatetimeIndex(h.index)
                overlap = pi.intersection(hi)
                seam_notes.append(f"hist {hc} x{scale}: {hi.min().date()}..{hi.max().date()} n={len(h)}; primary {pi.min().date()}..{pi.max().date()} n={len(prim)}; overlap {len(overlap)} wks")
        L = legs(df, report)
        oi = pd.to_numeric(df["Open_Interest_All"], errors="coerce").astype(float)
        net = {k: (lo - sh) for k, (lo, sh, sp) in L.items()}
        dnet = {k: v.diff() for k, v in net.items()}
        sum_dnet = sum(dnet.values())
        sum_long = sum(lo for lo, sh, sp in L.values()); sum_short = sum(sh for lo, sh, sp in L.values())
        sum_spr = sum(sp for lo, sh, sp in L.values() if sp is not None).fillna(0)
        resid_oi = (sum_long + sum_short + 2 * sum_spr - 2 * oi)
        resid_long = (sum_long + sum_spr - oi)
        ident[sym] = dict(max_abs_sum_dnet=float(sum_dnet.abs().max()), n_nonzero=int((sum_dnet.abs() > 0).sum()),
                          max_abs_resid_2oi=float(resid_oi.abs().max()), n_nonzero_2oi=int((resid_oi.abs() > 0).sum()),
                          max_abs_resid_long=float(resid_long.abs().max()))
        per = {}
        flags = []
        for k in TRIPLE[report]:
            sd = dnet[k].rolling(W, min_periods=MP).std()
            latest = sd.iloc[-1]; p5 = sd.quantile(0.05); med = sd.median()
            per[k] = (latest, p5, med)
            if latest < 200: flags.append(f"SMALL_OI_NOW:{k}(100c={100/latest:.2f}sd)")
            elif p5 < 200: flags.append(f"SMALL_OI_HIST5:{k}(p5={p5:.0f})")
        for k, v in dnet.items():
            ac[report].setdefault(k, {})[sym] = float(v.dropna().autocorr(1))
            ac_lvl[report].setdefault(k, {})[sym] = float(net[k].dropna().autocorr(1))
        # seam dNet check
        if stitched:
            for hc, scale in hist_code_scales(reg.hist_codes):
                h = fn(f"{sym}_{hc}")
                if h.empty: continue
                pi, hi = pd.DatetimeIndex(prim.index), pd.DatetimeIndex(h.index)
                # seams = dates in combined index where the source switches
                src = pd.Series(np.where(idx.isin(pi), "P", "H"), index=idx)
                sw = src[src != src.shift(1)].index[1:]
                for d in sw:
                    parts = []
                    for k in TRIPLE[report] + (["producer_merchant", "swap"] if report == "disagg" else ["dealer"]):
                        sd = dnet[k].rolling(W, min_periods=MP).std()
                        z = dnet[k].loc[d] / sd.loc[d] if sd.loc[d] and not np.isnan(sd.loc[d]) else np.nan
                        parts.append(f"{k}:dNet={dnet[k].loc[d]:.0f},z={z:.2f}")
                    seam_notes.append(f"seam {d.date()} ({src.shift(1).loc[d]}->{src.loc[d]}): " + " ".join(parts) + f"; |sum dNet|={abs(sum_dnet.loc[d]):.0f}")
        if idx.max() < pd.Timestamp("2026-09-22"): flags.append(f"LAGGING:last={idx.max().date()}")
        if len(big): flags.append(f"GAPS>8d:{len(big)}(max={int(big.max())}d)")
        rows.append(dict(sym=sym, report=report, rows=len(df), first=str(idx.min().date()), last=str(idx.max().date()),
                         stitched=stitched, seam="; ".join(seam_notes), per=per, flags=flags,
                         oi_latest=float(oi.iloc[-1]), oi_med=float(oi.median())))

pd.set_option("display.width", 250)
print("\n=== MARKET TABLE ===")
for r in rows:
    if r["rows"] == 0:
        print(f"{r['sym']} {r['report']} EMPTY"); continue
    per = " ".join(f"{k}:std52={v[0]:.0f}(p5={v[1]:.0f},med={v[2]:.0f})" for k, v in r["per"].items())
    print(f"{r['sym']} | {r['report']} | rows={r['rows']} | {r['first']}..{r['last']} | OI={r['oi_latest']:.0f} | {per} | stitched={r['stitched']} | flags={','.join(r['flags']) or '-'}")
    if r["seam"]: print("    SEAM:", r["seam"])

print("\n=== IDENTITY (all 42) ===")
for s, v in ident.items():
    print(s, v)

print("\n=== LAG-1 AUTOCORR of dNet, median across markets per cohort ===")
for report in ac:
    for k, d in ac[report].items():
        v = pd.Series(d)
        print(f"{report} {k}: median={v.median():.3f} min={v.min():.3f} max={v.max():.3f}  (levels median={pd.Series(ac_lvl[report][k]).median():.3f})")
    allv = pd.Series({(k, s): x for k, d in ac[report].items() for s, x in d.items()})
    print(f"{report} ALL cohorts pooled median={allv.median():.3f}")
print("\n=== per-market dNet autocorr (triple) ===")
for report in ac:
    for k in TRIPLE[report]:
        print(report, k, {s: round(x, 2) for s, x in ac[report][k].items()})
json.dump({"rows": [{**r, "per": {k: [float(x) for x in v] for k, v in r.get("per", {}).items()}} for r in rows], "ident": ident,
           "ac": ac, "ac_lvl": ac_lvl}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "coverage.json"), "w"), indent=1, default=str)
