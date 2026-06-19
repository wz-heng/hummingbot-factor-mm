from controllers.market_making.exchange_time import estimate_exchange_time_sec


def test_first_call_with_empty_cache_invokes_fetcher():
    cache = (0.0, 0.0)
    estimate, new_cache = estimate_exchange_time_sec(
        cache=cache,
        now_sec=1_000_000.0,
        fetcher=lambda: 1_000_001.5,  # exchange is 1.5s ahead
    )
    assert estimate == 1_000_001.5
    assert new_cache == (1_000_000.0, 1_000_001.5)


def test_fresh_cache_does_not_call_fetcher_and_interpolates():
    fetch_calls = []

    def boom():
        fetch_calls.append(1)
        raise RuntimeError("should not be called")

    cache = (1_000_000.0, 1_000_001.5)
    # 10s after last fetch, well inside default 300s window
    estimate, new_cache = estimate_exchange_time_sec(
        cache=cache,
        now_sec=1_000_010.0,
        fetcher=boom,
    )
    # Interpolation: server_at_fetch + (now - local_at_fetch)
    # = 1_000_001.5 + (1_000_010 - 1_000_000) = 1_000_011.5
    assert estimate == 1_000_011.5
    assert new_cache == cache
    assert fetch_calls == []


def test_stale_cache_triggers_refresh():
    cache = (1_000_000.0, 1_000_001.5)
    # 400s after last fetch, past the 300s default window
    estimate, new_cache = estimate_exchange_time_sec(
        cache=cache,
        now_sec=1_000_400.0,
        fetcher=lambda: 1_000_402.0,
    )
    assert estimate == 1_000_402.0
    assert new_cache == (1_000_400.0, 1_000_402.0)


def test_fetcher_failure_with_empty_cache_falls_back_to_now():
    def boom():
        raise RuntimeError("network down")

    cache = (0.0, 0.0)
    estimate, new_cache = estimate_exchange_time_sec(
        cache=cache,
        now_sec=1_000_000.0,
        fetcher=boom,
    )
    # Degraded path: estimate == now, cache unchanged
    assert estimate == 1_000_000.0
    assert new_cache == cache


def test_fetcher_failure_with_stale_cache_uses_stale_estimate():
    def boom():
        raise RuntimeError("network blip")

    cache = (1_000_000.0, 1_000_001.5)
    # 500s past last fetch, fetcher fails — should keep using stale cache
    estimate, new_cache = estimate_exchange_time_sec(
        cache=cache,
        now_sec=1_000_500.0,
        fetcher=boom,
    )
    # Interpolated from the stale cache
    assert estimate == 1_000_501.5
    assert new_cache == cache  # cache stays as-is so next tick retries
