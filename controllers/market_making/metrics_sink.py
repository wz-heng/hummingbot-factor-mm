"""SQLite writer for factor / inventory / health metrics.

One row per call to write(). Schema is created on first connect.
Caller is responsible for downsampling (typically 1 Hz).
"""

import sqlite3
from pathlib import Path
from typing import Union


_REQUIRED_KEYS = (
    "ts_ms",
    "mid",
    "micro_price",
    "obi",
    "factor_bp",
    "net_base",
    "factor_skew_bp",
    "inv_skew_bp",
    "reference_price",
    "ob_age_sec",
    "clock_drift_sec",
    "actions_60s",
    "kill_engaged",
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
  ts                  INTEGER PRIMARY KEY,
  mid                 REAL,
  micro_price         REAL,
  obi                 REAL,
  factor_bp           REAL,
  net_base            REAL,
  factor_skew_bp      REAL,
  inv_skew_bp         REAL,
  reference_price     REAL,
  ob_age_sec          REAL,
  clock_drift_sec     REAL,
  actions_60s         INTEGER,
  kill_engaged        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
"""


_INSERT = """
INSERT OR REPLACE INTO metrics (
  ts, mid, micro_price, obi, factor_bp, net_base,
  factor_skew_bp, inv_skew_bp, reference_price,
  ob_age_sec, clock_drift_sec, actions_60s, kill_engaged
) VALUES (
  :ts_ms, :mid, :micro_price, :obi, :factor_bp, :net_base,
  :factor_skew_bp, :inv_skew_bp, :reference_price,
  :ob_age_sec, :clock_drift_sec, :actions_60s, :kill_engaged
)
"""


class MetricsSink:
    """Thin sqlite writer for factor/inventory/health snapshots."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit
        self._conn.executescript(_SCHEMA)
        self._closed = False

    def write(self, snapshot: dict) -> None:
        for key in _REQUIRED_KEYS:
            if key not in snapshot:
                raise KeyError(f"MetricsSink.write: missing required key {key!r}")
        self._conn.execute(_INSERT, snapshot)

    def close(self) -> None:
        if self._closed:
            return
        self._conn.close()
        self._closed = True
