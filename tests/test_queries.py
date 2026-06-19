import sqlite3
import time
from pathlib import Path

import pytest

from dashboard.queries import (
    load_metrics,
    latest_snapshot,
)


@pytest.fixture
def metrics_db(tmp_path):
    db = tmp_path / "metrics.sqlite"
    schema = """
    CREATE TABLE metrics (
      ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
      factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
      reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
      actions_60s INTEGER, kill_engaged INTEGER
    );
    """
    with sqlite3.connect(db) as conn:
        conn.executescript(schema)
        now_ms = int(time.time() * 1000)
        rows = [
            (now_ms - 5000, 65000.0, 65000.5, 0.1, 0.5, 0.0, 1.0, 0.0, 65001.0, 0.2, 0.05, 3, 0),
            (now_ms - 4000, 65010.0, 65010.5, 0.2, 0.6, 0.001, 1.1, -0.1, 65011.0, 0.2, 0.05, 4, 0),
            (now_ms - 3000, 65020.0, 65020.5, -0.1, -0.5, 0.002, -1.1, -0.2, 65019.0, 0.2, 0.05, 5, 0),
        ]
        conn.executemany(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
    return db


def test_load_metrics_returns_all_rows_in_window(metrics_db):
    df = load_metrics(metrics_db, window_sec=600)
    assert len(df) == 3
    assert list(df.columns)[0] == "ts"


def test_load_metrics_excludes_rows_outside_window(tmp_path):
    db = tmp_path / "metrics.sqlite"
    schema = """
    CREATE TABLE metrics (
      ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
      factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
      reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
      actions_60s INTEGER, kill_engaged INTEGER
    );
    """
    with sqlite3.connect(db) as conn:
        conn.executescript(schema)
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - 1_000_000  # well outside any reasonable window
        conn.execute(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (old_ms, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0),
        )
        conn.execute(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now_ms, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0),
        )
    df = load_metrics(db, window_sec=600)
    assert len(df) == 1


def test_latest_snapshot_returns_most_recent(metrics_db):
    snap = latest_snapshot(metrics_db)
    assert snap is not None
    assert snap["obi"] == -0.1   # the most recent row in the fixture


def test_latest_snapshot_returns_none_on_empty(tmp_path):
    db = tmp_path / "empty.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE metrics (
          ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
          factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
          reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
          actions_60s INTEGER, kill_engaged INTEGER
        );
        """)
    assert latest_snapshot(db) is None
