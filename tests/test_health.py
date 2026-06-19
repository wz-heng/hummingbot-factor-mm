from controllers.market_making.health import (
    orderbook_age_ok,
    clock_drift_ok,
)


def test_orderbook_fresh_within_limit():
    assert orderbook_age_ok(snapshot_ts_sec=1000.0, now_sec=1001.5, max_age_sec=2.0) is True


def test_orderbook_stale_over_limit():
    assert orderbook_age_ok(snapshot_ts_sec=1000.0, now_sec=1003.0, max_age_sec=2.0) is False


def test_orderbook_exact_boundary_is_ok():
    # equal to max_age_sec is still considered ok (use strict >)
    assert orderbook_age_ok(snapshot_ts_sec=1000.0, now_sec=1002.0, max_age_sec=2.0) is True


def test_clock_drift_within_limit():
    assert clock_drift_ok(local_ts_sec=1000.0, exchange_ts_sec=1000.3, max_drift_sec=0.5) is True


def test_clock_drift_over_limit_positive():
    assert clock_drift_ok(local_ts_sec=1000.0, exchange_ts_sec=1001.0, max_drift_sec=0.5) is False


def test_clock_drift_over_limit_negative():
    assert clock_drift_ok(local_ts_sec=1001.0, exchange_ts_sec=1000.0, max_drift_sec=0.5) is False
