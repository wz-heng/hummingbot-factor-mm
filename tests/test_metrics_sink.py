import sqlite3
from pathlib import Path

import pytest

from controllers.market_making.metrics_sink import MetricsSink


@pytest.fixture
def sink(tmp_path):
    db_path = tmp_path / "metrics.sqlite"
    s = MetricsSink(db_path)
    yield s
    s.close()


def _snapshot(**overrides):
    base = dict(
        ts_ms=1_700_000_000_000,
        mid=65000.0,
        micro_price=65000.5,
        obi=0.1,
        factor_bp=0.5,
        net_base=0.001,
        factor_skew_bp=1.0,
        inv_skew_bp=-0.2,
        reference_price=65001.0,
        ob_age_sec=0.3,
        clock_drift_sec=0.05,
        actions_60s=4,
        kill_engaged=0,
    )
    base.update(overrides)
    return base


def test_write_inserts_row(sink, tmp_path):
    sink.write(_snapshot())
    db_path = tmp_path / "metrics.sqlite"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ts, mid, obi, kill_engaged FROM metrics").fetchall()
    assert rows == [(1_700_000_000_000, 65000.0, 0.1, 0)]


def test_write_multiple_rows(sink, tmp_path):
    sink.write(_snapshot(ts_ms=1, kill_engaged=0))
    sink.write(_snapshot(ts_ms=2, kill_engaged=1))
    db_path = tmp_path / "metrics.sqlite"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ts, kill_engaged FROM metrics ORDER BY ts").fetchall()
    assert rows == [(1, 0), (2, 1)]


def test_write_rejects_missing_required_key(sink):
    snap = _snapshot()
    del snap["mid"]
    with pytest.raises(KeyError):
        sink.write(snap)


def test_close_is_idempotent(sink):
    sink.close()
    sink.close()  # should not raise
