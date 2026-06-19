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


def load_recent_fills(
    db_path: Union[str, Path],
    limit: int = 50,
) -> pd.DataFrame:
    """Load recent fills from Hummingbot's trades.sqlite.

    Hummingbot's trade table schema may evolve; tolerate missing tables.
    """
    try:
        with sqlite3.connect(str(db_path)) as conn:
            df = pd.read_sql(
                "SELECT timestamp, trading_pair, trade_type, price, amount "
                "FROM TradeFill ORDER BY timestamp DESC LIMIT ?",
                conn,
                params=(limit,),
            )
        return df
    except (sqlite3.OperationalError, pd.io.sql.DatabaseError):
        return pd.DataFrame(
            columns=["timestamp", "trading_pair", "trade_type", "price", "amount"]
        )
