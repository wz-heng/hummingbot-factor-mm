from decimal import Decimal

from controllers.market_making.processed_data import compute_processed_data


def test_reference_price_in_spread_for_healthy_balanced_book(default_params, healthy_snapshot):
    result = compute_processed_data(healthy_snapshot, default_params)
    assert result["halt_reason"] is None
    assert result["spread_multiplier"] == Decimal("1")
    # balanced book, zero inventory, zero factor → reservation == mid
    assert result["reference_price"] == Decimal("65000.5")


def test_long_inventory_pushes_reservation_down(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.net_base = Decimal("0.005")  # net long
    result = compute_processed_data(snap, default_params)
    assert result["halt_reason"] is None
    assert result["reference_price"] < Decimal("65000.5")
    assert result["inv_skew"] < 0


def test_thick_ask_pulls_micro_price_down_factor_skew_negative(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.bid_qty = Decimal("1")
    snap.ask_qty = Decimal("9")
    # thick ask → micro_price < mid → micro_signal < 0 → factor < 0 → reservation < mid
    result = compute_processed_data(snap, default_params)
    assert result["halt_reason"] is None
    assert result["factor"] < 0
    assert result["factor_skew"] < 0
    assert result["reference_price"] < Decimal("65000.5")


def test_kill_switch_engages_on_daily_loss(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.daily_pnl = Decimal("-100")  # below -50 limit
    result = compute_processed_data(snap, default_params)
    assert result["halt_reason"] == "daily_loss"
    assert result["spread_multiplier"] == Decimal("0")


def test_health_halts_on_stale_orderbook(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.snapshot_ts_sec = 990.0  # 10.5s ago
    result = compute_processed_data(snap, default_params)
    assert result["halt_reason"] == "stale_orderbook"
    assert result["spread_multiplier"] == Decimal("0")


def test_health_halts_on_clock_drift(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.exchange_ts_sec = 999.0  # 1.5s off from local 1000.5
    result = compute_processed_data(snap, default_params)
    assert result["halt_reason"] == "clock_drift"
    assert result["spread_multiplier"] == Decimal("0")


def test_zero_total_qty_halts(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.bid_qty = Decimal("0")
    snap.ask_qty = Decimal("0")
    result = compute_processed_data(snap, default_params)
    assert result["halt_reason"] == "empty_book"
    assert result["spread_multiplier"] == Decimal("0")
