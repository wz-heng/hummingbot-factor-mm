"""Pure math for factor computation, inventory skew, and reservation price.

No I/O, no Hummingbot imports. Every function takes Decimals and returns a
Decimal so callers can rely on exact rational arithmetic.
"""

from decimal import Decimal


def micro_price(
    bid_px: Decimal,
    bid_qty: Decimal,
    ask_px: Decimal,
    ask_qty: Decimal,
) -> Decimal:
    """Volume-weighted mid: (bid_px*ask_qty + ask_px*bid_qty) / (bid_qty + ask_qty).

    The thicker side pulls the micro-price *away from itself* (a thick bid
    means a buy-side imbalance has already happened; next print is more
    likely on the ask).
    """
    total = bid_qty + ask_qty
    if total == 0:
        raise ZeroDivisionError("micro_price called with bid_qty + ask_qty == 0")
    return (bid_px * ask_qty + ask_px * bid_qty) / total


def obi(bid_qty: Decimal, ask_qty: Decimal) -> Decimal:
    """Order book imbalance in [-1, 1]. +1 = all bid, -1 = all ask."""
    total = bid_qty + ask_qty
    if total == 0:
        return Decimal("0")
    return (bid_qty - ask_qty) / total


def combine_factor(
    micro_signal: Decimal,
    obi_value: Decimal,
    obi_weight: Decimal,
) -> Decimal:
    """Weighted average of two signals.

    micro_signal is already a fraction of mid (typical ~1e-4).
    obi_value is in [-1, 1]; we rescale it by 1e-4 here so it lives on the
    same scale as micro_signal (about 1 bp at full deflection).
    """
    obi_rescaled = obi_value * Decimal("0.0001")
    return (Decimal("1") - obi_weight) * micro_signal + obi_weight * obi_rescaled


def inventory_skew(
    net_base: Decimal,
    target: Decimal,
    penalty_bps: Decimal,
    mid: Decimal,
) -> Decimal:
    """Price shift to drive net_base back toward target.

    penalty_bps is bp of mid per 1 unit of base deviation.
    Net long (positive deviation) → negative skew (push reservation down,
    attract sells, repel buys).
    """
    deviation = net_base - target
    return -deviation * penalty_bps * mid / Decimal("10000")


def reservation_price(
    mid: Decimal,
    factor: Decimal,
    factor_scale_bps: Decimal,
    inv_skew: Decimal,
) -> Decimal:
    """Reservation price = mid + factor_skew + inv_skew.

    factor is a fraction of mid (e.g., 0.0001 = 1 bp).
    factor_scale_bps is the dimensionless amplifier: 1bp factor with
    factor_scale_bps=2 produces a 2bp shift on top of mid.
    inv_skew is already a price-unit value.
    """
    factor_skew = factor * factor_scale_bps * mid
    return mid + factor_skew + inv_skew
