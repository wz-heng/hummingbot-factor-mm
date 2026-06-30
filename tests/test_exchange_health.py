import sqlite3

from controllers.market_making.exchange_health import (
    count_recent_order_failures,
    evaluate_exchange_health,
)


# ─────────────────────── evaluate_exchange_health ───────────────────────


def test_no_halt_when_failures_below_threshold():
    halt, reason = evaluate_exchange_health(
        n_recent_failures=10,
        last_failure_ts_sec=999.0,
        now_sec=1000.0,
        halted_state=False,
        threshold=20,
    )
    assert halt is False
    assert reason is None


def test_halt_engages_at_threshold():
    halt, reason = evaluate_exchange_health(
        n_recent_failures=20,
        last_failure_ts_sec=999.0,
        now_sec=1000.0,
        halted_state=False,
        threshold=20,
    )
    assert halt is True
    assert reason == "exchange_failures"


def test_halt_stays_within_recovery_window():
    # 60s since last failure, 300s window — still halted
    halt, reason = evaluate_exchange_health(
        n_recent_failures=0,
        last_failure_ts_sec=940.0,
        now_sec=1000.0,
        halted_state=True,
        recovery_window_sec=300.0,
    )
    assert halt is True
    assert reason == "exchange_failures"


def test_recovery_after_window():
    # 301s since last failure
    halt, reason = evaluate_exchange_health(
        n_recent_failures=0,
        last_failure_ts_sec=699.0,
        now_sec=1000.0,
        halted_state=True,
        recovery_window_sec=300.0,
    )
    assert halt is False
    assert reason is None


def test_halted_with_no_prior_failure_recovers():
    # Edge case: halted=True but last_failure_ts_sec=0 (e.g. cache cleared).
    halt, reason = evaluate_exchange_health(
        n_recent_failures=0,
        last_failure_ts_sec=0.0,
        now_sec=1000.0,
        halted_state=True,
    )
    assert halt is False
    assert reason is None


# ─────────────────────── count_recent_order_failures ───────────────────


def _build_order_table(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'CREATE TABLE "Order" ('
            'id TEXT, last_status TEXT, last_update_timestamp INTEGER'
            ')'
        )


def test_count_zero_when_no_failures(tmp_path):
    db = tmp_path / "trades.sqlite"
    _build_order_table(db)
    n, last_ts = count_recent_order_failures(db, window_start_ms=0)
    assert n == 0
    assert last_ts == 0.0


def test_count_only_failures_in_window(tmp_path):
    db = tmp_path / "trades.sqlite"
    _build_order_table(db)
    with sqlite3.connect(db) as conn:
        conn.executemany(
            'INSERT INTO "Order" VALUES (?, ?, ?)',
            [
                ("o1", "FAILED", 1000000),  # outside window
                ("o2", "FILLED", 2000000),  # not a failure
                ("o3", "FAILED", 2000500),
                ("o4", "FAILED", 2000800),
                ("o5", "FAILED", 2001000),  # latest
            ],
        )
    n, last_ts = count_recent_order_failures(db, window_start_ms=2000000)
    assert n == 3
    assert last_ts == 2001.0  # 2001000 / 1000


def test_count_tolerates_missing_table(tmp_path):
    db = tmp_path / "empty.sqlite"
    sqlite3.connect(db).close()  # creates an empty file with no tables
    n, last_ts = count_recent_order_failures(db, window_start_ms=0)
    assert n == 0
    assert last_ts == 0.0
