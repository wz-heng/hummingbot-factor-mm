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
    """Cumulative PnL with MTM of any open inventory (ground truth).

    Pure realized cash flow (sum SELL - sum BUY - fees) **jumps by ~one
    order's notional on every fill** because the bot is constantly mid-
    cycle: after a BUY but before its paired SELL, realized cash flow is
    ~-$120 even though the bot is holding $120 of BTC (worth ~$120).
    That made the cumulative-PnL Big Number swing ±$200 between
    consecutive fills.

    Correct accounting:
        PnL = (sum SELL value) - (sum BUY value)
              + (net_base × current_mid)   ← mark-to-market of open inventory
              - sum(fees)

    `current_mid` is approximated by the most recent fill's price. For a
    market-making bot quoting ±5-10 bp around mid, this is accurate to
    well under a basis point — far below normal PnL motion.

    Caveats:
      - For "today's PnL" we still report realized cash flow only (the
        MTM correction is a stock, not a flow, so splitting by day is
        awkward). It's labelled "today fills realized" in the dashboard.
      - by_close_type still reads Executors for the decomposition view;
        if Executors lags TradeFill (observed M4 behaviour), the
        breakdown is informational.
    """
    import datetime as _dt

    today_start_ms = int(
        _dt.datetime.combine(_dt.date.today(), _dt.time()).timestamp() * 1000
    )

    with sqlite3.connect(str(db_path)) as conn:
        try:
            row = conn.execute(
                """
                SELECT
                    count(*),
                    coalesce(sum(CASE WHEN trade_type='SELL' THEN amount*price/1e12 ELSE 0 END), 0) AS sell_value,
                    coalesce(sum(CASE WHEN trade_type='BUY'  THEN amount*price/1e12 ELSE 0 END), 0) AS buy_value,
                    coalesce(sum(CASE WHEN trade_type='SELL' THEN amount/1e6        ELSE 0 END), 0) AS sell_qty,
                    coalesce(sum(CASE WHEN trade_type='BUY'  THEN amount/1e6        ELSE 0 END), 0) AS buy_qty,
                    coalesce(sum(trade_fee_in_quote/1e6), 0) AS fees
                FROM TradeFill
                """
            ).fetchone()
            n_total = row[0]
            sell_value = float(row[1])
            buy_value = float(row[2])
            sell_qty = float(row[3])
            buy_qty = float(row[4])
            total_fees = float(row[5])

            net_base = buy_qty - sell_qty  # positive = net long
            total_notional = buy_value + sell_value

            last_price_row = conn.execute(
                "SELECT price/1e6 FROM TradeFill ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            current_mid = float(last_price_row[0]) if last_price_row else 0.0

            mtm_value = net_base * current_mid
            realized_cash_flow = sell_value - buy_value
            total_pnl = realized_cash_flow + mtm_value - total_fees

            today_row = conn.execute(
                """
                SELECT
                    count(*),
                    coalesce(sum(CASE WHEN trade_type='SELL' THEN amount*price/1e12 ELSE 0 END), 0)
                  - coalesce(sum(CASE WHEN trade_type='BUY'  THEN amount*price/1e12 ELSE 0 END), 0)
                  - coalesce(sum(trade_fee_in_quote/1e6), 0)
                FROM TradeFill WHERE timestamp >= ?
                """,
                (today_start_ms,),
            ).fetchone()
            today_n = today_row[0]
            today_realized = float(today_row[1])

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
                "current_net_base": 0.0,
                "current_mid": 0.0,
                "mtm_value": 0.0,
                "realized_cash_flow": 0.0,
                "by_close_type": [],
            }

    return {
        "n_fills": n_total,
        "total_pnl": total_pnl,
        "realized_cash_flow": realized_cash_flow,
        "mtm_value": mtm_value,
        "current_net_base": net_base,
        "current_mid": current_mid,
        "total_fees": total_fees,
        "total_notional": total_notional,
        "today_n_fills": today_n,
        "today_pnl": today_realized,  # realized only, no MTM by design
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
            # Show times in Asia/Shanghai (CST, UTC+8) so they match the operator's
            # wall clock. VPS runs in UTC; without conversion, "10:41" displayed
            # actually means "18:41" Beijing time — confusing.
            df["time"] = (
                pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                .dt.tz_convert("Asia/Shanghai")
                .dt.strftime("%m-%d %H:%M:%S")
            )
            df = df[["time", "trading_pair", "trade_type", "order_type",
                     "position", "price", "amount"]]
        return df
    except (sqlite3.OperationalError, pd.io.sql.DatabaseError):
        return pd.DataFrame(
            columns=["time", "trading_pair", "trade_type", "order_type",
                     "position", "price", "amount"]
        )
