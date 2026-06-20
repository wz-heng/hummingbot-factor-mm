"""Read-only sqlite queries powering the Streamlit dashboard.

All paths are accepted as str or Path. Returns pandas DataFrames so the UI
layer can chart directly. The dashboard process never writes to either db.
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional, Union

import pandas as pd


def load_metrics(
    db_path: Union[str, Path],
    window_sec: int = 600,
) -> pd.DataFrame:
    """Load metric rows within the last window_sec seconds."""
    cutoff_ms = int((time.time() - window_sec) * 1000)
    with sqlite3.connect(str(db_path)) as conn:
        df = pd.read_sql(
            "SELECT * FROM metrics WHERE ts >= ? ORDER BY ts",
            conn,
            params=(cutoff_ms,),
        )
    return df


def latest_snapshot(db_path: Union[str, Path]) -> Optional[dict]:
    """Return the most recent metrics row as a dict, or None if table is empty."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM metrics ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


_PRICE_AMOUNT_SCALE = 1_000_000  # Hummingbot TradeFill stores price/amount as int*1e6


def load_pnl_summary(db_path: Union[str, Path]) -> dict:
    """Cumulative + today PnL aggregated from the Executors table.

    `Executors` is Hummingbot's per-PositionExecutor record with floats
    `net_pnl_quote`, `cum_fees_quote`, `filled_amount_quote` already in
    quote-currency units. Each closed executor represents one open→close
    position cycle.

    "Today" is reckoned in local time, midnight-to-midnight.

    Returns a dict with zeros if the table is missing (early bring-up).
    """
    import datetime as _dt

    today_start_ts = _dt.datetime.combine(_dt.date.today(), _dt.time()).timestamp()

    with sqlite3.connect(str(db_path)) as conn:
        try:
            tot = conn.execute(
                "SELECT count(*), "
                "       coalesce(sum(net_pnl_quote), 0), "
                "       coalesce(sum(cum_fees_quote), 0), "
                "       coalesce(sum(filled_amount_quote), 0) "
                "FROM Executors"
            ).fetchone()
            today = conn.execute(
                "SELECT count(*), coalesce(sum(net_pnl_quote), 0) "
                "FROM Executors "
                "WHERE close_timestamp >= ?",
                (today_start_ts,),
            ).fetchone()
            by_type = conn.execute(
                "SELECT close_type, count(*), coalesce(sum(net_pnl_quote), 0) "
                "FROM Executors WHERE is_active = 0 "
                "GROUP BY close_type ORDER BY count(*) DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            return {
                "total_pnl": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "n_executors": 0,
                "today_pnl": 0.0,
                "today_n": 0,
                "by_close_type": [],
            }

    return {
        "n_executors": tot[0],
        "total_pnl": float(tot[1]),
        "total_fees": float(tot[2]),
        "total_notional": float(tot[3]),
        "today_n": today[0],
        "today_pnl": float(today[1]),
        "by_close_type": [(r[0], r[1], float(r[2])) for r in by_type],
    }


# Map close_type int → human label. Names come from Hummingbot's
# CloseType enum (hummingbot/strategy_v2/models/executors_info.py).
CLOSE_TYPE_LABELS = {
    0: "TIME_LIMIT",
    1: "STOP_LOSS",
    2: "TAKE_PROFIT",
    3: "TRAILING_STOP",
    4: "EXPIRED",
    5: "EARLY_STOP",
    6: "COMPLETED",
    7: "FAILED",
    8: "INSUFFICIENT_BALANCE",
    9: "POSITION_HOLD",
}


def load_recent_fills(
    db_path: Union[str, Path],
    limit: int = 50,
) -> pd.DataFrame:
    """Load recent fills from Hummingbot's trades sqlite.

    Schema notes (Hummingbot master @ 2026-06-20):
      - Table: `TradeFill`
      - Pair column is `symbol` (not `trading_pair`); we alias for display.
      - `price`, `amount` stored as BIGINT scaled by 1e6 → divide for display.
      - `position` is OPEN / CLOSE; `order_type` is LIMIT / MARKET.

    Tolerates missing table during early bring-up.
    """
    try:
        with sqlite3.connect(str(db_path)) as conn:
            df = pd.read_sql(
                "SELECT timestamp, symbol AS trading_pair, trade_type, order_type, "
                "       position, price, amount "
                "FROM TradeFill ORDER BY timestamp DESC LIMIT ?",
                conn,
                params=(limit,),
            )
        if not df.empty:
            df["price"] = df["price"] / _PRICE_AMOUNT_SCALE
            df["amount"] = df["amount"] / _PRICE_AMOUNT_SCALE
            df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df[["time", "trading_pair", "trade_type", "order_type",
                     "position", "price", "amount"]]
        return df
    except (sqlite3.OperationalError, pd.io.sql.DatabaseError):
        return pd.DataFrame(
            columns=["time", "trading_pair", "trade_type", "order_type",
                     "position", "price", "amount"]
        )
