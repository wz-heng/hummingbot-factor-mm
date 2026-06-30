"""Exchange health gate: halt trading when Binance side fails repeatedly.

Closes the gap exposed on 2026-06-30 when Binance Testnet returned HTTP 408
for 5 hours and our bot just retried silently — no kill, no halt. With this
gate, sustained order failures put the bot into a halt state until the
exchange recovers.

Architecture:
- `evaluate_exchange_health` is a pure function (testable without DB) that
  takes the current observed failure count and last-failure timestamp and
  returns (new_halted_state, halt_reason).
- `count_recent_order_failures` queries Hummingbot's Order table for rows
  with last_status='FAILED' inside the configured window. Lives separately
  so the pure function stays sqlite-free.
"""

import sqlite3
from pathlib import Path
from typing import Optional, Union


def evaluate_exchange_health(
    n_recent_failures: int,
    last_failure_ts_sec: float,
    now_sec: float,
    halted_state: bool,
    threshold: int = 20,
    recovery_window_sec: float = 300.0,
) -> tuple[bool, Optional[str]]:
    """Decide whether the bot should be halted due to exchange-side failures.

    Returns ``(new_halted_state, halt_reason)``.
    ``halt_reason`` is the string ``"exchange_failures"`` when halted,
    otherwise ``None``.

    State machine:
      - Not halted + failures ≥ threshold → halt
      - Halted + last failure within recovery_window → stay halted
      - Halted + last failure older than recovery_window → recover
    """
    if not halted_state:
        if n_recent_failures >= threshold:
            return True, "exchange_failures"
        return False, None

    # Currently halted — check for recovery.
    if last_failure_ts_sec == 0.0:
        # No failure was ever recorded; treat as recovered.
        return False, None
    if now_sec - last_failure_ts_sec > recovery_window_sec:
        return False, None
    return True, "exchange_failures"


def count_recent_order_failures(
    db_path: Union[str, Path],
    window_start_ms: int,
) -> tuple[int, float]:
    """Return ``(failure_count, last_failure_ts_sec)`` from Hummingbot's
    Order table.

    ``last_failure_ts_sec`` is 0.0 if no failures are present in the window.
    Tolerates table-missing on early startup by returning (0, 0.0).
    """
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                'SELECT count(*), coalesce(max(last_update_timestamp), 0) '
                'FROM "Order" '
                'WHERE last_status = ? AND last_update_timestamp >= ?',
                ("FAILED", window_start_ms),
            ).fetchone()
        if row is None:
            return 0, 0.0
        return int(row[0]), float(row[1]) / 1000.0
    except sqlite3.OperationalError:
        return 0, 0.0
