"""Hummingbot v2 MarketMakingController adapter.

The class is intentionally thin: it reads Hummingbot state, converts it into a
MarketSnapshot, calls compute_processed_data, and writes the result into
self.processed_data. All math, kill logic, and health checks live in
processed_data.py and its dependencies.
"""

import time
from decimal import Decimal
from pathlib import Path

from pydantic import Field

# Hummingbot imports — assumed available because this file is loaded by Hummingbot itself
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    PositionExecutorConfig,
)
from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction

from controllers.market_making.metrics_sink import MetricsSink
from controllers.market_making.processed_data import (
    FactorParams,
    MarketSnapshot,
    compute_processed_data,
)
from controllers.market_making import factor_math


# Where to write factor_metrics.sqlite (relative to Hummingbot working dir, i.e., /home/botuser/hummingbot)
_METRICS_DB_PATH = Path("data") / "factor_metrics.sqlite"


class FactorMMConfig(MarketMakingControllerConfigBase):
    controller_name: str = "factor_mm_btc_perp"
    connector_name: str = "binance_perpetual_testnet"
    trading_pair: str = "BTC-USDT"

    # Factor + inventory
    obi_weight: Decimal = Field(default=Decimal("0.5"))
    factor_scale_bps: Decimal = Field(default=Decimal("2"))
    inventory_target: Decimal = Field(default=Decimal("0"))
    inventory_penalty_bps: Decimal = Field(default=Decimal("300"))
    inventory_soft_cap: Decimal = Field(default=Decimal("0.01"))
    inventory_hard_cap: Decimal = Field(default=Decimal("0.02"))

    # Risk
    daily_loss_limit_usdt: Decimal = Field(default=Decimal("50"))
    max_actions_per_minute: int = Field(default=30)
    max_orderbook_age_sec: float = Field(default=2.0)
    max_clock_drift_sec: float = Field(default=0.5)


class FactorMMBtcPerp(MarketMakingControllerBase):
    """Thin adapter from Hummingbot v2 controller surface to compute_processed_data."""

    def __init__(self, config: FactorMMConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self._metrics = MetricsSink(_METRICS_DB_PATH)
        self._action_log: list[float] = []           # V2: rate limit enforcement; never appended to in V1
        self._kill_switch_engaged: bool = False
        self._last_metrics_emit: float = 0.0

    # ------------------------------------------------------------------
    async def update_processed_data(self) -> None:
        snap = self._build_snapshot()
        params = self._build_params()
        result = compute_processed_data(snap, params)

        if result["halt_reason"] == "daily_loss":
            if not self._kill_switch_engaged:
                self.logger().critical(
                    f"KILL SWITCH ENGAGED: daily PnL {snap.daily_pnl} "
                    f"< -{params.daily_loss_limit_usdt}"
                )
            self._kill_switch_engaged = True
        elif result["halt_reason"] is not None:
            self.logger().warning(f"Halting tick: {result['halt_reason']}")

        self.processed_data = {
            "reference_price": result["reference_price"],
            "spread_multiplier": result["spread_multiplier"],
        }

        # 1 Hz metrics downsampling (skip if halted to avoid confusing dashboard)
        now = time.time()
        if result["halt_reason"] is None and now - self._last_metrics_emit >= 1.0:
            self._emit_metrics(snap, params, result, now)
            self._last_metrics_emit = now

    # ------------------------------------------------------------------
    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=self.get_trade_type_from_level_id(level_id),
        )

    # ------------------------------------------------------------------
    def executors_to_early_stop(self):
        if not self._kill_switch_engaged:
            return []
        return [
            StopExecutorAction(executor_id=e.id, controller_id=self.config.id)
            for e in self.get_active_executors()
        ]

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _build_snapshot(self) -> MarketSnapshot:
        ob = self.market_data_provider.get_order_book(
            self.config.connector_name, self.config.trading_pair
        )
        # Guard against empty bids/asks (testnet reconnect resilience)
        if not ob.bids or not ob.asks:
            bid_px = ask_px = Decimal("0")
            bid_qty = ask_qty = Decimal("0")
        else:
            bid_px = Decimal(str(ob.bids[0].price))
            bid_qty = Decimal(str(ob.bids[0].amount))
            ask_px = Decimal(str(ob.asks[0].price))
            ask_qty = Decimal(str(ob.asks[0].amount))

        now = time.time()
        snapshot_ts = getattr(ob, "snapshot_uid_time", now)  # best-effort; verify at M4

        return MarketSnapshot(
            bid_px=bid_px,
            bid_qty=bid_qty,
            ask_px=ask_px,
            ask_qty=ask_qty,
            net_base=Decimal(str(self.get_current_base_position())),
            daily_pnl=self._read_daily_pnl(),
            snapshot_ts_sec=float(snapshot_ts),
            now_sec=now,
            local_ts_sec=now,
            exchange_ts_sec=now,  # TODO M4: wire real exchange server time
        )

    def _build_params(self) -> FactorParams:
        c = self.config
        # V2: inventory_soft_cap and inventory_hard_cap from self.config will be
        # plumbed into FactorParams here when L2/L3 tier logic ships.
        return FactorParams(
            obi_weight=c.obi_weight,
            factor_scale_bps=c.factor_scale_bps,
            inventory_target=c.inventory_target,
            inventory_penalty_bps=c.inventory_penalty_bps,
            daily_loss_limit_usdt=c.daily_loss_limit_usdt,
            max_orderbook_age_sec=c.max_orderbook_age_sec,
            max_clock_drift_sec=c.max_clock_drift_sec,
        )

    def _read_daily_pnl(self) -> Decimal:
        # M4 will wire this to Hummingbot trades.sqlite; until then return 0
        return Decimal("0")

    def _emit_metrics(self, snap, params, result, now: float) -> None:
        mid = (snap.bid_px + snap.ask_px) / 2
        mp = factor_math.micro_price(snap.bid_px, snap.bid_qty, snap.ask_px, snap.ask_qty)
        snapshot = {
            "ts_ms": int(now * 1000),
            "mid": float(mid),
            "micro_price": float(mp),
            "obi": float(
                (snap.bid_qty - snap.ask_qty) / (snap.bid_qty + snap.ask_qty)
                if (snap.bid_qty + snap.ask_qty)
                else 0
            ),
            "factor_bp": float(result["factor"] * 10000),
            "net_base": float(snap.net_base),
            "factor_skew_bp": float(result["factor_skew"] / mid * 10000) if mid else 0.0,
            "inv_skew_bp": float(result["inv_skew"] / mid * 10000) if mid else 0.0,
            "reference_price": float(result["reference_price"]),
            "ob_age_sec": snap.now_sec - snap.snapshot_ts_sec,
            "clock_drift_sec": abs(snap.local_ts_sec - snap.exchange_ts_sec),
            "actions_60s": len([t for t in self._action_log if now - t < 60]),
            "kill_engaged": 1 if self._kill_switch_engaged else 0,
        }
        try:
            self._metrics.write(snapshot)
        except Exception as exc:
            self.logger().error(f"metrics write failed: {exc}")
