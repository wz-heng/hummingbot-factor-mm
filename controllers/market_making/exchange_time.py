"""Exchange server time estimation with caching.

Wires the controller's `exchange_ts_sec` to Binance Futures `/fapi/v1/time`
so the clock-drift health check has real ground truth instead of always
seeing drift=0.

Design:
- `fetch_binance_futures_server_time_sec(url)` — synchronous REST call,
  stdlib only (`urllib`). Used at most once per `max_cache_age_sec`.
- `estimate_exchange_time_sec(cache, now, fetcher, ...)` — pure function:
  given a cache tuple, the current local time, and a fetcher callable,
  returns the best estimate of exchange time + an updated cache. Falls
  back gracefully when fetcher raises (uses stale cache; or `now` if
  cache is empty and the first fetch fails).
"""

import json
import urllib.request
from typing import Callable


BINANCE_FUTURES_TESTNET_TIME_URL = "https://testnet.binancefuture.com/fapi/v1/time"
BINANCE_FUTURES_MAINNET_TIME_URL = "https://fapi.binance.com/fapi/v1/time"

# `cache = (local_at_fetch_sec, server_at_fetch_sec)`. Both 0.0 means "never fetched".
ExchangeTimeCache = tuple[float, float]


def fetch_binance_futures_server_time_sec(url: str, timeout_sec: float = 5.0) -> float:
    """Return Binance Futures `serverTime` (seconds since epoch).

    Raises on any HTTP / JSON / network error. Caller decides how to fall back.
    """
    with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8")
    return float(json.loads(body)["serverTime"]) / 1000.0


def estimate_exchange_time_sec(
    cache: ExchangeTimeCache,
    now_sec: float,
    fetcher: Callable[[], float],
    max_cache_age_sec: float = 300.0,
) -> tuple[float, ExchangeTimeCache]:
    """Return `(estimated_exchange_time_sec, new_cache)`.

    If the cache is empty or stale, invoke `fetcher` and refresh.
    If `fetcher` raises:
      - and the cache is empty → degrade to `now_sec` (drift will read 0)
      - and the cache has data → keep using the stale cache (drift will reflect
        whatever drift existed at the last successful fetch + any local clock
        drift since)
    """
    local_at_fetch, server_at_fetch = cache
    cache_is_empty = local_at_fetch == 0.0
    cache_is_stale = (now_sec - local_at_fetch) > max_cache_age_sec

    if cache_is_empty or cache_is_stale:
        try:
            server_at_fetch = fetcher()
            new_cache: ExchangeTimeCache = (now_sec, server_at_fetch)
            return server_at_fetch, new_cache
        except Exception:
            if cache_is_empty:
                # No prior data and first fetch failed — degrade to `now`.
                return now_sec, cache
            # Fall through to use the stale cache.

    estimate = server_at_fetch + (now_sec - local_at_fetch)
    return estimate, cache
