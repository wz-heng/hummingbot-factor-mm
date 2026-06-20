# Deploy notes — TODOs and field corrections discovered during M4 bring-up

## Status (2026-06-20)

M4 successfully reached: bot live on Binance USDT-M Futures Testnet via
Vultr Tokyo 2C/2G; Streamlit dashboard reachable on Tailscale.
Hummingbot version installed: master @ 2026-06-19.

## Fixes folded into the repo on M4 day, ready for next bring-up

### 1. Hummingbot install needs `conda-build` + `pre-commit` on newer Miniconda

Newer Miniconda (2024+) ships **without** `conda-build`, so `conda develop`
is missing; `pre-commit` is also not present. Hummingbot `./install` fails
with both. The `deploy/_recovery.sh` script handles this:

```bash
conda install -y conda-build
pip install pre-commit
```

`bootstrap_vps.sh` should be folded to do this BEFORE `./install` to make
the first-run clean. Currently the manual recovery covers it.

### 2. `bootstrap_vps.sh` step 3b is not idempotent on partial failure

`if [ ! -d hummingbot ]; then ... ./install ./compile ... fi` — if install
or compile fails after the clone succeeds, re-running bootstrap SKIPS the
recovery. Operator must run `deploy/_recovery.sh` or do it manually.

**Fix:** factor `./install` and `./compile` out of the clone guard with
sentinel files (e.g. `~/hummingbot/.install.ok`, `.compile.ok`).

### 3. Hummingbot V2 strategy launch needs an outer config in `conf/scripts/`

Our controller config in `conf/controllers/factor_mm_btc.yml` is loaded by
the wrapper `scripts/v2_with_controllers.py`. That wrapper needs a config
in `conf/scripts/`. We now ship `conf/scripts/factor_mm.yml` referencing
the controller.

systemd unit launches:
`hummingbot_quickstart.py --v2 factor_mm.yml --headless`

(The earlier `-f conf/controllers/factor_mm_btc.yml` approach does not
work for the V2 Controller framework.)

### 4. `MarketMakingControllerConfigBase` requires an `id` field

Added `id: factor_mm_btc_perp_v1` to the example YAML. Spec §4.2 model
listing missed this. Updates to spec §11 V1 should reflect this.

### 5. `MarketMakingControllerConfigBase.candles_config` / `markets` rejected

V2WithControllersConfig in current Hummingbot uses pydantic v2 with
`extra="forbid"`, so the older `candles_config: []` and `markets: {}`
fields from spec §11 V1 examples must be omitted from the outer config.
(They live inside `StrategyV2ConfigBase` but the V2WithControllers
subclass overrides with stricter validation.)

### 6. Binance Futures BTC-USDT min notional = 50 USDT

`total_amount_quote: 200` produced per-order notional ≈ $45 → orders
rejected by Binance API. Bumped default to `500` (each order ≈ $125).
Worth documenting this constraint in the spec parameter table.

### 7. `OrderBook` exposes data via `bid_entries()` / `ask_entries()`, not `.bids` / `.asks`

This was V8 in spec §11. Confirmed during M4. Controller's
`_build_snapshot` now uses iterators:

```python
best_bid = next(iter(ob.bid_entries()))
best_ask = next(iter(ob.ask_entries()))
```

### 8. Streamlit needs `PYTHONPATH=/home/botuser/factor-mm` and `streamlit pandas plotly` deps

Hummingbot conda env doesn't include streamlit/pandas/plotly. Installed via
`pip install streamlit pandas plotly` inside the env at M4.

`bootstrap_vps.sh` should run this pip install before enabling the
dashboard service. Also systemd dashboard unit now sets
`Environment=PYTHONPATH=/home/botuser/factor-mm` so `from dashboard.queries
import ...` resolves.

### 9. `--config-password=$VAR` on systemd ExecStart leaks the password

`systemd` expands `${VAR}` in ExecStart at unit-load time, and the
resulting argv is visible in `/proc/<pid>/cmdline`, `systemctl status`,
and `journalctl`. Replaced with a wrapper script (`deploy/run-hummingbot.sh`)
that reads `HUMMINGBOT_PASSWORD` from env and injects it into Python's
`sys.argv` AFTER process start (in-process memory only, not visible to
other processes via /proc).

### 10. Dashboard binds 0.0.0.0 + `ufw allow in on tailscale0`

Public 8501 stays blocked by ufw default-deny (only 22/tcp allowed from
public). Tailscale interface explicitly allowed via:
`ufw allow in on tailscale0`

Browser access: `http://<tailscale-ip>:8501` (Tailscale-only).

### 11. Hummingbot writes fills to `<config_name>.sqlite`, not `trades.sqlite`

The "Markets recorder" uses the controller / strategy file name as the
sqlite filename. For our setup that's `factor_mm.sqlite` (from
`conf/scripts/factor_mm.yml`'s file name minus extension), not the
default `trades.sqlite`. Fixed `TRADES_DB` env in
`deploy/factor-dashboard.service`.

### 12. TradeFill schema columns and scaling differ from naive expectation

Actual columns:
`config_file_path, strategy, market, symbol, base_asset, quote_asset,
timestamp, order_id, trade_type, order_type, price, amount, leverage,
trade_fee (json), trade_fee_in_quote, exchange_trade_id, position`

Notable:
- Pair column is `symbol` (not `trading_pair`)
- `price` and `amount` stored as BIGINT scaled ×1e6 — must divide for
  display (e.g. price 63624100000 → 63624.10 USDT)
- `timestamp` is unix ms
- `position` is OPEN / CLOSE

`dashboard/queries.py::load_recent_fills` updated accordingly.
