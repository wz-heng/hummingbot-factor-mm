from decimal import Decimal

import pytest

from controllers.market_making.processed_data import FactorParams, MarketSnapshot


@pytest.fixture
def default_params():
    return FactorParams(
        obi_weight=Decimal("0.5"),
        factor_scale_bps=Decimal("2"),
        inventory_target=Decimal("0"),
        inventory_penalty_bps=Decimal("300"),
        daily_loss_limit_usdt=Decimal("50"),
        max_orderbook_age_sec=2.0,
        max_clock_drift_sec=0.5,
    )


@pytest.fixture
def healthy_snapshot():
    return MarketSnapshot(
        bid_px=Decimal("65000"),
        bid_qty=Decimal("5"),
        ask_px=Decimal("65001"),
        ask_qty=Decimal("5"),
        net_base=Decimal("0"),
        daily_pnl=Decimal("0"),
        snapshot_ts_sec=1000.0,
        now_sec=1000.5,
        local_ts_sec=1000.5,
        exchange_ts_sec=1000.5,
    )
