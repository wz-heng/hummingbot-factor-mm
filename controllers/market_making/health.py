"""Health-check predicates for orderbook freshness and clock sync.

Pure functions; no I/O, no clock reads. Callers pass timestamps in.
"""


def orderbook_age_ok(
    snapshot_ts_sec: float,
    now_sec: float,
    max_age_sec: float,
) -> bool:
    """True iff the orderbook snapshot is at most max_age_sec old."""
    age = now_sec - snapshot_ts_sec
    return age <= max_age_sec


def clock_drift_ok(
    local_ts_sec: float,
    exchange_ts_sec: float,
    max_drift_sec: float,
) -> bool:
    """True iff |local - exchange| <= max_drift_sec."""
    drift = abs(local_ts_sec - exchange_ts_sec)
    return drift <= max_drift_sec
