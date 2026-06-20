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
    """Cumulative + today PnL computed directly from TradeFill (ground truth).

    TradeFill records every actual exchange fill (price, amount, fee). We
    sum the quote-currency cash flow:
      - BUY  → cash out  = -(price * amount) - fees
      - SELL → cash in   = +(price * amount) - fees
    realized_pnl = sum(cash flow)  (correct if net position ≈ 0)

    If the bot ends with non-zero net base, the unrealized P/L for that
    position is NOT included here — the caller can add it from the current
    mid + remaining_base.

    Also returns an Executors-table breakdown by close_type for the
    decomposition table; if Executors lag behind TradeFill (we have
    observed Hummingbot's V2 PositionExecutor stop writing new rows while
    the controller keeps trading), the realized PnL above is still
    correct because it comes from TradeFill.

    "Today" is reckoned in local time, midnight-to-midnight.
    """
    import datetime as _dt

    today_start_ms = int(
        _dt.datetime.combine(_dt.date.today(), _dt.time()).timestamp() * 1000
    )

    def _pnl_query(conn, where: str = "1=1", params: tuple = ()) -> tuple:
        """Return (n_fills, realized_pnl_quote, total_fees_quote, total_notional_quote)."""
        row = conn.execute(
            f"""
            SELECT
                count(*),
                coalesce(
                    sum(
                        CASE WHEN trade_type='SELL' THEN  amount * price / 1e12
                                                   ELSE -amount * price / 1e12
                        END
                    ),
                    0
                ),
                coalesce(sum(trade_fee_in_quote / 1e6), 0),
                coalesce(sum(amount * price / 1e12), 0)
            FROM TradeFill
            WHERE {where}
            """,
            params,
        ).fetchone()
        # realized = cash flow - fees
        return row[0], float(row[1]) - float(row[2]), float(row[2]), float(row[3])

    with sqlite3.connect(str(db_path)) as conn:
        try:
            n_total, total_pnl, total_fees, total_notional = _pnl_query(conn)
            n_today, today_pnl, _, _ = _pnl_query(
                conn, "timestamp >= ?", (today_start_ms,)
            )
            # Executors breakdown (may lag — for decomposition view only)
            by_type = []
            try:
                by_type = conn.execute(
                    "SELECT close_type, count(*), coalesce(sum(net_pnl_quote), 0) "
                    "FROM Executors WHERE is_active = 0 "
                    "GROUP BY close_type ORDER BY count(*) DESC"
                ).fetchall()
            except sqlite3.OperationalError:
                pass
            n_executors = 0
            try:
                n_executors = conn.execute(
                    "SELECT count(*) FROM Executors"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                pass
        except sqlite3.OperationalError:
            return {
                "total_pnl": 0.0,
                "total_fees": 0.0,
                "total_notional": 0.0,
                "n_fills": 0,
                "today_pnl": 0.0,
                "today_n_fills": 0,
                "n_executors": 0,
                "by_close_type": [],
            }

    return {
        "n_fills": n_total,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "total_notional": total_notional,
        "today_n_fills": n_today,
        "today_pnl": today_pnl,
        "n_executors": n_executors,
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
