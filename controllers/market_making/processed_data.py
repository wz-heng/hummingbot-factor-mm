"""Pure orchestrator turning raw market state into Hummingbot's processed_data.

This module is the heart of the strategy. It is intentionally Hummingbot-free
so it is fully unit-testable. The thin controller class in
factor_mm_btc_perp.py reads Hummingbot state into a MarketSnapshot, calls
compute_processed_data, and writes the result back.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from controllers.market_making import factor_math, health


@dataclass
class FactorParams:
    """Configuration knobs needed by compute_processed_data."""

    obi_weight: Decimal
    factor_scale_bps: Decimal
    inventory_target: Decimal
    inventory_penalty_bps: Decimal
    daily_loss_limit_usdt: Decimal
    max_orderbook_age_sec: float
    max_clock_drift_sec: float


@dataclass
class MarketSnapshot:
    """Raw inputs read from Hummingbot at one tick.

    All Decimals are kept exact; timestamps are seconds-since-epoch floats.
    """

    bid_px: Decimal
    bid_qty: Decimal
    ask_px: Decimal
    ask_qty: Decimal
    net_base: Decimal
    daily_pnl: Decimal
    snapshot_ts_sec: float
    now_sec: float
    local_ts_sec: float
    exchange_ts_sec: float


def _halt(reason: str) -> dict:
    """Build a processed_data dict that halts the controller."""
    return {
        "reference_price": Decimal("0"),
        "spread_multiplier": Decimal("0"),
        "factor": Decimal("0"),
        "factor_skew": Decimal("0"),
        "inv_skew": Decimal("0"),
        "halt_reason": reason,
    }


def compute_processed_data(snap: MarketSnapshot, params: FactorParams) -> dict:
    """Turn a market snapshot + params into a processed_data dict.

    On any kill / health failure, returns a halt dict with spread_multiplier=0
    and a non-None halt_reason. The controller adapter is responsible for
    detecting halt_reason and acting on it (e.g., calling executors_to_early_stop).
    """
    # 1. Daily loss kill switch
    if snap.daily_pnl < -params.daily_loss_limit_usdt:
        return _halt("daily_loss")

    # 2. Health checks
    if not health.orderbook_age_ok(snap.snapshot_ts_sec, snap.now_sec, params.max_orderbook_age_sec):
        return _halt("stale_orderbook")
    if not health.clock_drift_ok(snap.local_ts_sec, snap.exchange_ts_sec, params.max_clock_drift_sec):
        return _halt("clock_drift")

    # 3. Empty book guard
    if snap.bid_qty + snap.ask_qty == 0:
        return _halt("empty_book")

    # 4. Mid + factor
    mid = (snap.bid_px + snap.ask_px) / 2
    mp = factor_math.micro_price(snap.bid_px, snap.bid_qty, snap.ask_px, snap.ask_qty)
    micro_signal = (mp - mid) / mid
    obi_value = factor_math.obi(snap.bid_qty, snap.ask_qty)
    factor = factor_math.combine_factor(micro_signal, obi_value, params.obi_weight)

    # 5. Inventory skew
    inv_skew = factor_math.inventory_skew(
        net_base=snap.net_base,
        target=params.inventory_target,
        penalty_bps=params.inventory_penalty_bps,
        mid=mid,
    )

    # 6. Reservation price
    ref = factor_math.reservation_price(
        mid=mid,
        factor=factor,
        factor_scale_bps=params.factor_scale_bps,
        inv_skew=inv_skew,
    )

    factor_skew = factor * params.factor_scale_bps * mid

    return {
        "reference_price": ref,
        "spread_multiplier": Decimal("1"),
        "factor": factor,
        "factor_skew": factor_skew,
        "inv_skew": inv_skew,
        "halt_reason": None,
    }
