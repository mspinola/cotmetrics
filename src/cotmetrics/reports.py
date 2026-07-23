"""
core/reports.py

Shared report generation logic, usable by both the Dash UI (heatmap.py)
and the background downloader (etl_scheduler.py) without importing
any Dash UI components.
"""
from datetime import datetime

import pandas as pd

import cotmetrics.constants as const
import cotmetrics.models as models
from cotmetrics.indexer import get_indexer
from cotmetrics.report_styles import _BEAR, _BULL, _DIM, _NEUTRAL, _cell_style, _fmt
from cotmetrics.synthesis import _collect_active_signals, generate_exhaustive_tape_synthesis


def get_matrix_data(asset_classes, lookback, target_date=None):
    """Build the Signal Matrix DataFrame. Shared between UI and email reports."""
    if not asset_classes:
        asset_classes = get_indexer().get_asset_classes()

    rows = []
    lookback_str = " " + lookback

    idx_col = const.COMM + lookback_str + const.IDX
    lrg_idx_col = const.LARGE + lookback_str + const.IDX
    sml_idx_col = const.SMALL + lookback_str + const.IDX

    # get_symbols_data returns the full frame, so the OI-normalized twins are already
    # on the same row as the raw ones. No second fetch, no second basis argument, which
    # is what lets one pass report both models side by side.
    #
    # These two are display columns now, not gate inputs. The gates ask the model which
    # columns they read (see setup_cls / setup_npf below). Only the Comm and Small legs
    # are shown because the normalized block exists to explain the NPF CS verdict, and
    # that gate drops Large Specs. The raw block still shows all three.
    norm_idx_col = idx_col + const.NORMALIZED
    norm_sml_idx_col = sml_idx_col + const.NORMALIZED

    z_col = const.COMM + lookback_str + const.ZSCORE

    const.WILLCO + lookback_str
    oi_z_col = const.OPEN_INTEREST + lookback_str + const.ZSCORE

    for ac in asset_classes:
        instruments = get_indexer().get_assets_for_asset_class(ac)
        for asset in instruments:
            df = get_indexer().get_symbols_data(asset, lookback)
            if df.empty:
                continue

            if target_date:
                matching_rows = df[df.index.strftime('%Y-%m-%d') == target_date]
                if matching_rows.empty:
                    continue
                latest = matching_rows.iloc[-1]
            else:
                latest = df.iloc[-1]

            instrument = get_indexer().get_instrument_from_name(asset)
            symbol_str = instrument.symbol if instrument else asset

            if isinstance(latest.name, pd.Timestamp):
                dt_str = latest.name.strftime('%Y-%m-%d')
            else:
                dt_str = str(latest.name)

            latest.get(idx_col)
            latest.get(lrg_idx_col)
            latest.get(sml_idx_col)

            bull_sig, bear_sig, debug_sig, _ = _collect_active_signals(latest, include_accumulation=True)
            all_sigs = bull_sig + bear_sig
            signals_str = ", ".join(all_sigs) if all_sigs else ""

            symbol_str = get_indexer().get_instrument_symbol_from_name(asset)
            synthesis = generate_exhaustive_tape_synthesis(latest, symbol_str=symbol_str, df=df)
            tape_bias = synthesis.get("tape_bias", "neutral").capitalize()

            try:
                from cotmetrics.options_data import get_max_pain_for_symbol
                res = get_max_pain_for_symbol(symbol_str, dt_str)
                max_pain, delta_iv, current_price = (res["max_pain"], res["delta_iv"], res["current_price"]) if res else (None, None, None)
                max_pain_pull = ((max_pain - current_price) / current_price) * 100 if max_pain and current_price else None
            except Exception:
                max_pain, delta_iv, max_pain_pull = None, None, None

            # Setup state is a property of the row, not of any one cell, so it is
            # resolved once here and carried as a column. Both the Dash heatmap and the
            # emailed HTML style from it, which keeps them from each re-deriving the
            # rules and drifting apart. The two bands are independent: Coffee is
            # currently an NPF CS setup while its CLS legs are only close.
            #
            # Each model reads its own columns off the row. This function used to name
            # them itself, correctly but by its own separate reasoning, while movers.py
            # named them differently and shipped a defect for it. Asking the model which
            # columns it gates on means the report and the dashboard cannot answer that
            # question two ways.
            is_equity = get_indexer().is_equity(asset)
            setup_cls = models.RAW_PF.setup_state_from(latest, lookback, is_equity)
            setup_npf = models.NPF.setup_state_from(latest, lookback, is_equity)

            row = {
                "Asset Class": ac,
                "Asset": asset,
                const.SETUP_CLS_COL: setup_cls,
                const.SETUP_NPF_COL: setup_npf,
                const.IS_EQUITY_COL: is_equity,
                "Date": dt_str,
                "Tape Bias": tape_bias,
                "Signals": signals_str,
                "Comm Index": round(latest.get(idx_col, 0), 0) if pd.notna(latest.get(idx_col)) else None,
                "Lrg Index": round(latest.get(lrg_idx_col, 0), 0) if pd.notna(latest.get(lrg_idx_col)) else None,
                "Sml Index": round(latest.get(sml_idx_col, 0), 0) if pd.notna(latest.get(sml_idx_col)) else None,
                "Comm Index Norm": round(latest.get(norm_idx_col, 0), 0) if pd.notna(latest.get(norm_idx_col)) else None,
                "Sml Index Norm": round(latest.get(norm_sml_idx_col, 0), 0) if pd.notna(latest.get(norm_sml_idx_col)) else None,
                "Comm Move": round(latest.get(const.COMM_MOMENTUM, 0), 0) if pd.notna(latest.get(const.COMM_MOMENTUM)) else None,
                "Lrg Move": round(latest.get(const.LRG_MOMENTUM, 0), 0) if pd.notna(latest.get(const.LRG_MOMENTUM)) else None,
                "Sml Move": round(latest.get(const.SML_MOMENTUM, 0), 0) if pd.notna(latest.get(const.SML_MOMENTUM)) else None,
                "Comm Z": round(latest.get(z_col, 0), 2) if pd.notna(latest.get(z_col)) else None,
                "WILLCO": round(latest.get(const.WILLCO_ALIAS, 0), 0) if pd.notna(latest.get(const.WILLCO_ALIAS)) else None,
                "Inst Sentiment": round(latest.get(const.LW_LRG_SENTIMENT, 0), 0) if pd.notna(latest.get(const.LW_LRG_SENTIMENT)) else None,
                "OI Z": round(latest.get(oi_z_col, 0), 2) if pd.notna(latest.get(oi_z_col)) else None,
                "Max Pain Pull": round(max_pain_pull, 2) if max_pain_pull is not None else None,
                "Delta IV": delta_iv,
            }
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(by=["Asset Class", "Asset"])


def generate_matrix_html(df: pd.DataFrame, report_date: str = None) -> str:
    """
    Render the Signal Matrix DataFrame as a self-contained HTML email table
    with dark theme, inline styling, and color-coded numeric cells.
    """
    if df.empty:
        return "<p>No matrix data available.</p>"

    if report_date is None:
        report_date = datetime.now().strftime("%Y-%m-%d")

    # Column groups for header rows
    groups = [
        ("",               ["Asset Class", "Asset", "Tape Bias", "Signals"]),
        # The two blocks are the two models, side by side. This is the one surface that
        # shows both rather than following a single choice, because comparing them is
        # what the Signal Matrix is for. Large Specs is absent from the NPF block
        # because the CS gate drops that leg.
        (f"Positioning · {models.RAW_PF.title}",
                           ["Comm Index", "Lrg Index", "Sml Index"]),
        (f"Positioning · {models.NPF.title}",
                           ["Comm Index Norm", "Sml Index Norm"]),
        ("Index Momentum", ["Comm Move", "Lrg Move", "Sml Move"]),
        ("Friction & Flow", ["WILLCO", "Inst Sentiment"]),
        ("Open Interest",  ["OI Z", "Max Pain Pull", "Delta IV"]),
    ]

    # The group header already says which basis the block is, so the column headers
    # drop the "Norm" suffix rather than repeating it three more times.
    display_names = {
        "Comm Index Norm": "Comm Index",
        "Sml Index Norm": "Sml Index",
    }

    # Flatten column order
    all_cols = [c for _, cols in groups for c in cols]

    # ── CSS ──────────────────────────────────────────────────────────────────
    style = """
    <style>
      body { background:#1a1a1a; color:#ABB8C9; font-family:Arial,sans-serif; font-size:12px; margin:0; padding:16px; }
      h2   { color:#E2E8F0; font-size:16px; margin-bottom:4px; }
      p.sub{ color:#657b83; font-size:11px; margin-top:0; margin-bottom:12px; }
      table{ border-collapse:collapse; width:100%; background:#1a1a1a; }
      th, td { padding:5px 8px; text-align:center; white-space:nowrap; border-bottom:1px solid rgba(171,184,201,0.12); }
      th   { background:#002b36; color:#E2E8F0; font-weight:600; font-size:11px; }
      th.group-hdr { background:#073642; color:#93a1a1; font-size:10px; text-transform:uppercase;
                     letter-spacing:0.05em; border-bottom:2px solid rgba(171,184,201,0.25); }
      td.label { text-align:left; color:#E2E8F0; }
      tr:nth-child(even) td { background:rgba(255,255,255,0.025); }
      .sep { border-right:2px solid rgba(171,184,201,0.25); }
      .bull { color:#10B981; }
      .bear { color:#EF4444; }
      .dim  { color:#657b83; }
    </style>
    """

    # Column → CSS class for label columns
    label_cols = {"Asset Class", "Asset", "Tape Bias", "Signals"}

    # Map col name → group (for separator detection)
    last_in_group = {cols[-1] for _, cols in groups if cols}

    # ── Table ─────────────────────────────────────────────────────────────────
    rows_html = []

    # Group header row
    group_row = "<tr>"
    for group_name, cols in groups:
        sep = " sep" if cols[-1] in last_in_group else ""
        colspan = len(cols)
        if group_name:
            group_row += f'<th class="group-hdr{sep}" colspan="{colspan}">{group_name}</th>'
        else:
            group_row += f'<th class="group-hdr{sep}" colspan="{colspan}"></th>'
    group_row += "</tr>"

    # Column name header row
    col_row = "<tr>"
    for col in all_cols:
        sep = " sep" if col in last_in_group else ""
        col_row += f'<th class="{sep.strip()}">{display_names.get(col, col)}</th>'
    col_row += "</tr>"

    # Data rows
    for _, row in df.iterrows():
        data_row = '<tr>'
        for col in all_cols:
            val = row.get(col)
            sep = " sep" if col in last_in_group else ""

            if col in label_cols:
                display = str(val) if val is not None else ""

                if col == "Tape Bias":
                    if display == "Bullish":
                        display = f'<span style="color:{_BULL}; font-weight:600;">Bullish</span>'
                    elif display == "Bearish":
                        display = f'<span style="color:{_BEAR}; font-weight:600;">Bearish</span>'
                    elif display:
                        display = f'<span style="color:{_DIM};">{display}</span>'

                elif col == "Signals" and display:
                    sig_html = []
                    for s in display.split(","):
                        s = s.strip()
                        if not s:
                            continue
                        s_upper = s.upper()
                        if any(x in s_upper for x in ["BULL", "BUY", "SQZ", "ACCUMULATION"]):
                            color = _BULL
                            bg = "rgba(16,185,129,0.15)"
                        elif any(x in s_upper for x in ["BEAR", "SELL", "EXHAUSTION", "CAPITULATION"]):
                            color = _BEAR
                            bg = "rgba(239,68,68,0.15)"
                        else:
                            color = _NEUTRAL
                            bg = "rgba(255,255,255,0.05)"

                        pill = f'<span style="color:{color}; background:{bg}; border:1px solid {color}40; padding:2px 6px; border-radius:4px; font-size:10px; margin-right:4px; white-space:nowrap; display:inline-block; font-weight:600;">{s}</span>'
                        sig_html.append(pill)
                    display = "".join(sig_html)

                cls = f"label{sep}"
                data_row += f'<td class="{cls}">{display}</td>'
            else:
                cell_style = _cell_style(col, val, row)
                display = _fmt(col, val)
                data_row += f'<td class="{sep.strip()}" style="{cell_style}">{display}</td>'

        data_row += "</tr>"
        rows_html.append(data_row)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">{style}</head>
<body>
  <h2>📊 COT Signal Matrix — {report_date}</h2>
  <p class="sub">Auto-generated after new CFTC Commitment of Traders data was processed. Full CSV attached.</p>
  <table>
    <thead>
      {group_row}
      {col_row}
    </thead>
    <tbody>
      {"".join(rows_html)}
    </tbody>
  </table>
  <p class="sub" style="margin-top:12px">cot-analyzer &bull; generated {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}</p>
</body>
</html>"""

    return html
