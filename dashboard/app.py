"""Factor MM dashboard.

Run:
  streamlit run dashboard/app.py

Reads sqlite paths from env:
  METRICS_DB  (default: data/factor_metrics.sqlite)
  TRADES_DB   (default: data/trades.sqlite)
"""

import os
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.queries import (
    CLOSE_TYPE_LABELS,
    latest_snapshot,
    load_metrics,
    load_pnl_summary,
    load_recent_fills,
)


METRICS_DB = Path(os.environ.get("METRICS_DB", "data/factor_metrics.sqlite"))
TRADES_DB = Path(os.environ.get("TRADES_DB", "data/trades.sqlite"))

REFRESH_SEC = 2
WINDOW_SEC = 600  # 10 minutes of metrics history


st.set_page_config(page_title="Factor MM", layout="wide")

# Top banner
snap = latest_snapshot(METRICS_DB) if METRICS_DB.exists() else None
kill_on = bool(snap and snap.get("kill_engaged"))
banner_color = "#7a1f1f" if kill_on else "#0e1117"
st.markdown(
    f"<div style='background:{banner_color};padding:8px 16px;"
    f"color:white;font-weight:600'>Factor MM · BTC-USDT Perp · TESTNET"
    f" — Kill: {'ON' if kill_on else 'OFF'}</div>",
    unsafe_allow_html=True,
)

# PnL row (from Hummingbot's Executors table)
pnl = load_pnl_summary(TRADES_DB) if TRADES_DB.exists() else None
pcols = st.columns(4)
if pnl and pnl["n_fills"] > 0:
    pcols[0].metric(
        "Cumulative PnL (USDT)",
        f"{pnl['total_pnl']:+.2f}",
        delta=f"{pnl['total_pnl'] / max(pnl['total_notional'], 1) * 10000:+.1f} bp of notional",
    )
    pcols[1].metric(
        "Today's PnL (USDT)",
        f"{pnl['today_pnl']:+.2f}",
        delta=f"{pnl['today_n_fills']} fills today",
    )
    pcols[2].metric("Cumulative Fees (USDT)", f"{pnl['total_fees']:.2f}")
    pcols[3].metric(
        "Fills (all-time)",
        f"{pnl['n_fills']}",
        delta=f"notional {pnl['total_notional']/1000:.1f}k USDT",
    )
else:
    for c in pcols:
        c.metric("—", "no PnL data yet")

# Market state row
cols = st.columns(6)
if snap:
    cols[0].metric("Mid", f"{snap['mid']:.2f}")
    cols[1].metric("Net Base (BTC)", f"{snap['net_base']:+.4f}")
    cols[2].metric("Reservation", f"{snap['reference_price']:.2f}")
    cols[3].metric("Factor (bp)", f"{snap['factor_bp']:+.2f}")
    cols[4].metric("Actions/60s", f"{snap['actions_60s']}")
    cols[5].metric("OB age (s)", f"{snap['ob_age_sec']:.2f}")
else:
    for c in cols:
        c.metric("—", "no data")

# Time-series rows
df = load_metrics(METRICS_DB, window_sec=WINDOW_SEC) if METRICS_DB.exists() else pd.DataFrame()

if not df.empty:
    df["t"] = pd.to_datetime(df["ts"], unit="ms")

    # Row 1: factor signals
    fig1 = make_subplots(specs=[[{"secondary_y": True}]])
    fig1.add_trace(
        go.Scatter(x=df["t"], y=df["factor_bp"], name="Factor (bp)"),
        secondary_y=False,
    )
    fig1.add_trace(
        go.Scatter(x=df["t"], y=df["obi"], name="OBI", line=dict(dash="dot")),
        secondary_y=True,
    )
    fig1.update_layout(height=240, margin=dict(l=20, r=20, t=30, b=20),
                       title="Factor signal (bp) + OBI")
    st.plotly_chart(fig1, use_container_width=True)

    # Row 2: inventory + skews
    fig2 = make_subplots(specs=[[{"secondary_y": True}]])
    fig2.add_trace(
        go.Scatter(x=df["t"], y=df["net_base"], name="Net base (BTC)"),
        secondary_y=False,
    )
    fig2.add_trace(
        go.Scatter(x=df["t"], y=df["factor_skew_bp"], name="Factor skew (bp)"),
        secondary_y=True,
    )
    fig2.add_trace(
        go.Scatter(x=df["t"], y=df["inv_skew_bp"], name="Inv skew (bp)"),
        secondary_y=True,
    )
    fig2.update_layout(height=240, margin=dict(l=20, r=20, t=30, b=20),
                       title="Inventory + skew")
    st.plotly_chart(fig2, use_container_width=True)

    # Row 3: health
    fig3 = make_subplots(rows=1, cols=3,
                         subplot_titles=("OB age (s)", "Clock drift (s)", "Actions/60s"))
    fig3.add_trace(go.Scatter(x=df["t"], y=df["ob_age_sec"], name="ob_age"),
                   row=1, col=1)
    fig3.add_trace(go.Scatter(x=df["t"], y=df["clock_drift_sec"], name="drift"),
                   row=1, col=2)
    fig3.add_trace(go.Scatter(x=df["t"], y=df["actions_60s"], name="actions"),
                   row=1, col=3)
    fig3.update_layout(height=240, showlegend=False,
                       margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("No metrics yet. Waiting for the bot to write rows to "
            f"{METRICS_DB}.")

# PnL breakdown by close_type
if pnl and pnl["by_close_type"]:
    st.subheader("PnL by close type")
    pdf = pd.DataFrame(
        [
            {
                "close_type": CLOSE_TYPE_LABELS.get(ct, f"?{ct}"),
                "n": n,
                "total_pnl": round(p, 4),
                "avg_pnl": round(p / n, 5) if n else 0.0,
            }
            for (ct, n, p) in pnl["by_close_type"]
        ]
    )
    st.dataframe(pdf, use_container_width=True, hide_index=True)

# Row 4: recent fills
fills = load_recent_fills(TRADES_DB, limit=50) if TRADES_DB.exists() else pd.DataFrame()
st.subheader("Recent fills (last 50)")
if fills.empty:
    st.text("No fills yet.")
else:
    st.dataframe(fills, use_container_width=True, height=300)

# Refresh
time.sleep(REFRESH_SEC)
st.rerun()
