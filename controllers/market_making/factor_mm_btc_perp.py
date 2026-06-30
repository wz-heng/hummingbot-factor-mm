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
from controllers.market_making.exchange_time import (
    BINANCE_FUTURES_MAINNET_TIME_URL,
    BINANCE_FUTURES_TESTNET_TIME_URL,
    estimate_exchange_time_sec,
    fetch_binance_futures_server_time_sec,
)
from controllers.market_making.exchange_health import (
    count_recent_order_failures,
    evaluate_exchange_health,
)


# Where to write factor_metrics.sqlite (relative to Hummingbot working dir, i.e., /home/botuser/hummingbot)
_METRICS_DB_PATH = Path("data") / "factor_metrics.sqlite"
# Hummingbot's recorder writes Order/TradeFill here (named after controller config).
_TRADES_DB_PATH = Path("data") / "factor_mm.sqlite"


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

    # Exchange health (added 2026-06-30 after Binance Testnet 5h outage)
    exchange_failure_threshold: int = Field(default=20)             # failures in window → halt
    exchange_failure_window_sec: float = Field(default=300.0)       # 5 min lookback
    exchange_recovery_window_sec: float = Field(default=300.0)      # 5 min no failures → recover


class FactorMMBtcPerp(MarketMakingControllerBase):
    """Thin adapter from Hummingbot v2 controller surface to compute_processed_data."""

    def __init__(self, config: FactorMMConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self._metrics = MetricsSink(_METRICS_DB_PATH)
        self._action_log: list[float] = []           # V2: rate limit enforcement; never appended to in V1
        self._kill_switch_engaged: bool = False
        self._last_metrics_emit: float = 0.0
        # Exchange server-time cache: (local_at_fetch_sec, server_at_fetch_sec).
        # (0.0, 0.0) means "never fetched"; refreshed at most once per
        # max_clock_drift_sec window (default 300s).
        self._exch_time_cache: tuple[float, float] = (0.0, 0.0)
        self._exch_time_url = (
            BINANCE_FUTURES_TESTNET_TIME_URL
            if config.connector_name.endswith("_testnet")
            else BINANCE_FUTURES_MAINNET_TIME_URL
        )
        # Exchange health gate state (recomputed every 30s, not every tick)
        self._exchange_halted: bool = False
        self._exch_health_last_check: float = 0.0
        self._exch_health_cached_failures: int = 0
        self._exch_health_last_failure_ts: float = 0.0

    # ------------------------------------------------------------------
    async def update_processed_data(self) -> None:
        snap = self._build_snapshot()
        params = self._build_params()
        result = compute_processed_data(snap, params)

        # Exchange health gate (independent of compute_processed_data)
        self._refresh_exchange_health()

        if result["halt_reason"] == "daily_loss":
            if not self._kill_switch_engaged:
                self.logger().critical(
                    f"KILL SWITCH ENGAGED: daily PnL {snap.daily_pnl} "
                    f"< -{params.daily_loss_limit_usdt}"
                )
            self._kill_switch_engaged = True
        elif result["halt_reason"] is not None:
            self.logger().warning(f"Halting tick: {result['halt_reason']}")

        # If exchange health gate fires, override to halt regardless of factor result
        if self._exchange_halted:
            result = dict(result)
            result["spread_multiplier"] = Decimal("0")
            result["halt_reason"] = "exchange_failures"

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
        # Hummingbot exposes the book via bid_entries() / ask_entries() iterators
        # of OrderBookRow(price, amount, update_id). Take the first row of each.
        try:
            best_bid = next(iter(ob.bid_entries()))
            best_ask = next(iter(ob.ask_entries()))
            bid_px = Decimal(str(best_bid.price))
            bid_qty = Decimal(str(best_bid.amount))
            ask_px = Decimal(str(best_ask.price))
            ask_qty = Decimal(str(best_ask.amount))
        except StopIteration:
            # Empty side(s); compute_processed_data will halt with empty_book
            bid_px = ask_px = Decimal("0")
            bid_qty = ask_qty = Decimal("0")

        now = time.time()
        snapshot_ts = getattr(ob, "snapshot_uid_time", now)  # best-effort; verify at M4

        exchange_ts, self._exch_time_cache = estimate_exchange_time_sec(
            cache=self._exch_time_cache,
            now_sec=now,
            fetcher=lambda: fetch_binance_futures_server_time_sec(self._exch_time_url),
        )

        return MarketSnapshot(
            bid_px=bid_px,
            bid_qty=bid_qty,
            ask_px=ask_px,
            ask_qty=ask_qty,
            net_base=self._get_perp_position(),
            daily_pnl=self._read_daily_pnl(),
            snapshot_ts_sec=float(snapshot_ts),
            now_sec=now,
            local_ts_sec=now,
            exchange_ts_sec=exchange_ts,
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

    def _refresh_exchange_health(self) -> None:
        """Update self._exchange_halted based on recent Order failures.

        sqlite query throttled to once per 30s — running it every tick
        would pointlessly contend with Hummingbot's recorder.
        """
        now = time.time()
        if now - self._exch_health_last_check < 30.0:
            # Use cached state but still let recovery logic fire on every check
            halted, _ = evaluate_exchange_health(
                n_recent_failures=self._exch_health_cached_failures,
                last_failure_ts_sec=self._exch_health_last_failure_ts,
                now_sec=now,
                halted_state=self._exchange_halted,
                threshold=self.config.exchange_failure_threshold,
                recovery_window_sec=self.config.exchange_recovery_window_sec,
            )
            if halted != self._exchange_halted and not halted:
                self.logger().info(
                    "EXCHANGE RECOVERY: no failures within window — resuming"
                )
            self._exchange_halted = halted
            return

        self._exch_health_last_check = now
        cutoff_ms = int(
            (now - self.config.exchange_failure_window_sec) * 1000
        )
        n, last_ts = count_recent_order_failures(_TRADES_DB_PATH, cutoff_ms)
        self._exch_health_cached_failures = n
        if last_ts > 0:
            self._exch_health_last_failure_ts = last_ts

        previous = self._exchange_halted
        halted, _ = evaluate_exchange_health(
            n_recent_failures=n,
            last_failure_ts_sec=self._exch_health_last_failure_ts,
            now_sec=now,
            halted_state=previous,
            threshold=self.config.exchange_failure_threshold,
            recovery_window_sec=self.config.exchange_recovery_window_sec,
        )
        if halted and not previous:
            self.logger().critical(
                f"EXCHANGE HALT: {n} order failures in last "
                f"{int(self.config.exchange_failure_window_sec)}s — pausing quotes"
            )
        elif previous and not halted:
            self.logger().info(
                "EXCHANGE RECOVERY: no failures within window — resuming"
            )
        self._exchange_halted = halted

    def _get_perp_position(self) -> Decimal:
        """Return signed net base position on this perpetual.

        The base class's get_current_base_position() iterates over
        self.positions_held — a SPOT concept. For perpetual contracts,
        positions_held is always empty (Hummingbot explicitly skips
        spot-style rebalancing for perps in check_position_rebalance).

        The real derivative position lives on the connector:
        connector.account_positions is Dict[str, Position]. We sum
        amount over all entries matching our trading_pair (handles
        both ONEWAY — one entry — and HEDGE — LONG + SHORT entries).
        Position.amount is signed: positive = long, negative = short.
        """
        try:
            conn = self.market_data_provider.connectors[self.config.connector_name]
            total = Decimal("0")
            for pos in conn.account_positions.values():
                if pos.trading_pair == self.config.trading_pair:
                    total += Decimal(str(pos.amount))
            return total
        except Exception as exc:
            self.logger().warning(f"_get_perp_position: read failed: {exc}")
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
