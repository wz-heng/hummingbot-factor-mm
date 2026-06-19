from decimal import Decimal

from controllers.market_making.factor_math import (
    micro_price,
    obi,
    combine_factor,
    inventory_skew,
    reservation_price,
)


D = Decimal


def test_micro_price_equal_qty_returns_mid():
    # equal sizes → micro_price == mid
    result = micro_price(D("100"), D("5"), D("101"), D("5"))
    assert result == D("100.5")


def test_micro_price_skewed_toward_thicker_side():
    # bigger ask qty → micro_price pulled toward bid (toward the side with more depth)
    # formula: (bid_px*ask_qty + ask_px*bid_qty) / (bid_qty + ask_qty)
    # = (100*9 + 101*1) / 10 = 1001/10 = 100.1
    result = micro_price(D("100"), D("1"), D("101"), D("9"))
    assert result == D("100.1")
    assert result < D("100.5")  # below mid


def test_micro_price_zero_total_qty_raises():
    # zero on both sides should raise rather than divide-by-zero crash
    import pytest
    with pytest.raises(ZeroDivisionError):
        micro_price(D("100"), D("0"), D("101"), D("0"))


def test_obi_boundary_values():
    assert obi(D("10"), D("0")) == D("1")     # all bid
    assert obi(D("0"), D("10")) == D("-1")    # all ask
    assert obi(D("5"), D("5")) == D("0")      # balanced


def test_combine_factor_weights():
    # micro_signal = 0.0001 (1 bp), obi = 0.5, weight = 0.5
    # combined = 0.5 * 0.0001 + 0.5 * (0.5 * 0.0001) = 0.00005 + 0.000025 = 0.000075
    result = combine_factor(
        micro_signal=D("0.0001"),
        obi_value=D("0.5"),
        obi_weight=D("0.5"),
    )
    assert result == D("0.000075")


def test_inventory_skew_sign_long_position_negative():
    # net long → skew should push reservation DOWN (negative)
    result = inventory_skew(
        net_base=D("0.01"),
        target=D("0"),
        penalty_bps=D("300"),
        mid=D("65000"),
    )
    # = -0.01 * 300 * 65000 / 10000 = -19.5
    assert result == D("-19.5")


def test_inventory_skew_sign_short_position_positive():
    # net short → skew should push reservation UP (positive)
    result = inventory_skew(
        net_base=D("-0.01"),
        target=D("0"),
        penalty_bps=D("300"),
        mid=D("65000"),
    )
    assert result == D("19.5")


def test_reservation_price_monotonic_in_factor():
    # holding all else equal, larger factor → larger reservation_price
    r1 = reservation_price(mid=D("100"), factor=D("0.0001"), factor_scale_bps=D("2"), inv_skew=D("0"))
    r2 = reservation_price(mid=D("100"), factor=D("0.0002"), factor_scale_bps=D("2"), inv_skew=D("0"))
    assert r2 > r1
