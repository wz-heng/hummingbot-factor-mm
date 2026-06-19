# Factor MM (BTC Perp Testnet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and deploy a factor-driven market-making bot for `BTC-USDT` USDT-M perpetual on Binance testnet, packaged as a Hummingbot v2 Controller, with a custom Streamlit dashboard and a Tokyo VPS deployment.

**Architecture:** A custom subclass of Hummingbot's `MarketMakingControllerBase` overrides `update_processed_data` to compute a Micro-price + OBI factor and an inventory-penalty skew, then sets a `reference_price` that drives Hummingbot's built-in quoting machinery. All pure computation (factor math, skew, halt logic) lives in plain functions in `controllers/market_making/processed_data.py` for unit testing without Hummingbot installed. Metrics are written to a separate SQLite (`data/factor_metrics.sqlite`) read by a Streamlit dashboard. Deployment is source-install on a Tokyo VPS (Vultr High Frequency or AWS Lightsail) with two systemd services.

**Tech Stack:** Python 3.10+, Hummingbot v2 (Strategy V2 Controllers), Pydantic v2, SQLite (via `sqlite3` stdlib), Streamlit, Plotly, pytest, pytest-asyncio, systemd, Tailscale.

## Global Constraints

- **Spec reference:** `docs/superpowers/specs/2026-06-19-factor-mm-binance-perp-design.md` — every numeric default and design decision originates here. If a task needs a value, look in the spec.
- **Trading pair:** `BTC-USDT` only (USDT-M Perpetual Futures), testnet first.
- **Connector name:** `binance_perpetual_testnet`.
- **Hummingbot fork:** master branch as of 2026-06-19. API surface verified for `MarketMakingControllerConfigBase`, `MarketMakingControllerBase.update_processed_data` (async), `PositionExecutorConfig`, `TripleBarrierConfig`, `ControllerBase.get_active_executors()`.
- **API keys:** **never** in git; place under `conf/connectors/` (gitignored); Binance API must have IP whitelist = VPS public IP and **withdrawal disabled**.
- **Dashboard binding:** `127.0.0.1:8501` only; public access via Tailscale, never via public port.
- **Risk parameters:** all defaults from spec §6.6. Do not invent new defaults; if a parameter must change, update the spec first.
- **Commit cadence:** one commit per task minimum. Never bundle unrelated changes.
- **No code on VPS edits:** all source changes happen on the dev machine, pushed to git, pulled on VPS via `pull_and_restart.sh`.
- **Decimal everywhere for prices/quantities** — `float` only for unitless ratios (OBI, time durations).

---

## File Map

```
hummingbot-factor-mm/
├── pyproject.toml                                  [Task 1]
├── README.md                                       [Task 1, expanded Task 11]
├── controllers/
│   └── market_making/
│       ├── __init__.py                             [Task 1]
│       ├── factor_math.py                          [Task 2]
│       ├── health.py                               [Task 3]
│       ├── metrics_sink.py                         [Task 4]
│       ├── processed_data.py                       [Task 5]
│       └── factor_mm_btc_perp.py                   [Task 6]
├── conf/
│   └── controllers/
│       └── factor_mm_btc.yml.example               [Task 7]
├── deploy/
│   ├── bootstrap_vps.sh                            [Task 8]
│   ├── hummingbot.service                          [Task 8]
│   ├── factor-dashboard.service                    [Task 8]
│   └── pull_and_restart.sh                         [Task 8]
├── dashboard/
│   ├── __init__.py                                 [Task 9]
│   ├── queries.py                                  [Task 9]
│   └── app.py                                      [Task 10]
└── tests/
    ├── __init__.py                                 [Task 1]
    ├── conftest.py                                 [Task 5]
    ├── test_factor_math.py                         [Task 2]
    ├── test_health.py                              [Task 3]
    ├── test_metrics_sink.py                        [Task 4]
    ├── test_processed_data.py                      [Task 5]
    └── test_queries.py                             [Task 9]
```

**Responsibility boundaries:**

- `factor_math.py` — pure math: micro-price, OBI, factor combination, inventory skew, reservation price. No I/O, no Hummingbot imports.
- `health.py` — pure predicates: orderbook freshness, clock drift OK. No I/O beyond timestamp comparisons.
- `metrics_sink.py` — single class `MetricsSink` that opens a sqlite file and inserts rows. No business logic.
- `processed_data.py` — orchestrator `compute_processed_data(...)` that ties factor math + health + kill switch into one pure function returning a dict matching Hummingbot's `processed_data` shape.
- `factor_mm_btc_perp.py` — `FactorMMConfig` + `FactorMMBtcPerp` controller class. **Thin adapter**: reads Hummingbot state, calls `compute_processed_data`, writes results. ~100 LOC.
- `dashboard/queries.py` — read-only sqlite query functions.
- `dashboard/app.py` — Streamlit layout calling `queries`.

---

## Task Map (M-level mapping to spec §10)

| Task | Spec milestone | Output |
|---:|---|---|
| 1 | M0 | Repo scaffolding, pytest empty-run green |
| 2 | M1 | `factor_math.py` + 8 unit tests |
| 3 | M1 | `health.py` + tests |
| 4 | M1 | `metrics_sink.py` + tests |
| 5 | M2 | `processed_data.py` + integration tests (no Hummingbot needed) |
| 6 | M2 | `factor_mm_btc_perp.py` controller (adapter; runtime-tested in M4) |
| 7 | M2 | `factor_mm_btc.yml.example` config template |
| 8 | M3 | `deploy/` scripts and systemd units |
| 9 | M5 | `dashboard/queries.py` + tests |
| 10 | M5 | `dashboard/app.py` Streamlit UI |
| 11 | M3–M5 | `README.md` first-run runbook |

M4 (testnet bring-up), M6/M7 (testnet observation), M8 (Go/No-go review), M9 (mainnet) are operational — covered by the runbook in Task 11, not by separate implementation tasks.

---

### Task 1: Project Scaffolding (M0)

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `controllers/market_making/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: a `pip install -e .[dev]` installable package; `pytest` exits 0 with "no tests ran" or runs an empty test.

- [ ] **Step 1: Write `pyproject.toml`**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "factor-mm"
version = "0.1.0"
description = "Factor-driven market making controller for Hummingbot v2 on Binance USDT-M perpetuals"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
dev = [
  "pytest>=7",
  "pytest-asyncio>=0.21",
  "pandas>=2",
  "streamlit>=1.30",
  "plotly>=5",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools]
packages = ["controllers", "controllers.market_making", "dashboard"]
```

- [ ] **Step 2: Write minimal `README.md`**

Create `README.md`:

```markdown
# factor-mm

Factor-driven market-making controller for Binance USDT-M perpetual on Hummingbot v2.

See `docs/superpowers/specs/2026-06-19-factor-mm-binance-perp-design.md` for full design.

## Quick start (dev machine)

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Quick start (VPS)

See "Deployment runbook" section below (added in Task 11).
```

- [ ] **Step 3: Create empty package init files**

Create empty file `controllers/market_making/__init__.py` (zero bytes).
Create empty file `tests/__init__.py` (zero bytes).

- [ ] **Step 4: Install dev environment and verify pytest runs**

Run:

```bash
cd D:/vibe-coding/hummingbot-factor-mm
python -m venv .venv
.venv/Scripts/activate    # Git Bash on Windows; on Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Expected output (key line): `no tests ran in 0.0Xs`. Exit code 0.

If `pip install` fails on Windows due to compilation of an optional dep (e.g., a Pydantic C build), record the failure verbatim and stop — do not silently work around it.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md controllers/ tests/
git commit -m "chore: project scaffolding (M0)

- pyproject.toml with dev extras (pytest, streamlit, pandas, plotly)
- empty package and test directories
- one-paragraph README pointing at spec"
```

---

### Task 2: Factor Math Module (M1)

**Files:**
- Create: `controllers/market_making/factor_math.py`
- Create: `tests/test_factor_math.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `micro_price(bid_px: Decimal, bid_qty: Decimal, ask_px: Decimal, ask_qty: Decimal) -> Decimal`
  - `obi(bid_qty: Decimal, ask_qty: Decimal) -> Decimal`  (range `[-1, 1]`)
  - `combine_factor(micro_signal: Decimal, obi_value: Decimal, obi_weight: Decimal) -> Decimal`
  - `inventory_skew(net_base: Decimal, target: Decimal, penalty_bps: Decimal, mid: Decimal) -> Decimal`
  - `reservation_price(mid: Decimal, factor: Decimal, factor_scale_bps: Decimal, inv_skew: Decimal) -> Decimal`

All return `Decimal`. All accept `Decimal`. No `float`, no Hummingbot import.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factor_math.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_factor_math.py -v
```

Expected: ImportError or 8 failures, all with `ModuleNotFoundError` or `ImportError` for `controllers.market_making.factor_math`.

- [ ] **Step 3: Implement `factor_math.py`**

Create `controllers/market_making/factor_math.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_factor_math.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add controllers/market_making/factor_math.py tests/test_factor_math.py
git commit -m "feat(factor_math): pure functions for factor + skew + reservation price (M1)

- micro_price, obi, combine_factor, inventory_skew, reservation_price
- 8 unit tests covering equality, boundaries, sign conventions, monotonicity
- no I/O, no Hummingbot imports; runnable on any Python 3.10+ env"
```

---

### Task 3: Health Check Helpers (M1)

**Files:**
- Create: `controllers/market_making/health.py`
- Create: `tests/test_health.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `orderbook_age_ok(snapshot_ts_sec: float, now_sec: float, max_age_sec: float) -> bool`
  - `clock_drift_ok(local_ts_sec: float, exchange_ts_sec: float, max_drift_sec: float) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_health.py`:

```python
from controllers.market_making.health import (
    orderbook_age_ok,
    clock_drift_ok,
)


def test_orderbook_fresh_within_limit():
    assert orderbook_age_ok(snapshot_ts_sec=1000.0, now_sec=1001.5, max_age_sec=2.0) is True


def test_orderbook_stale_over_limit():
    assert orderbook_age_ok(snapshot_ts_sec=1000.0, now_sec=1003.0, max_age_sec=2.0) is False


def test_orderbook_exact_boundary_is_ok():
    # equal to max_age_sec is still considered ok (use strict >)
    assert orderbook_age_ok(snapshot_ts_sec=1000.0, now_sec=1002.0, max_age_sec=2.0) is True


def test_clock_drift_within_limit():
    assert clock_drift_ok(local_ts_sec=1000.0, exchange_ts_sec=1000.3, max_drift_sec=0.5) is True


def test_clock_drift_over_limit_positive():
    assert clock_drift_ok(local_ts_sec=1000.0, exchange_ts_sec=1001.0, max_drift_sec=0.5) is False


def test_clock_drift_over_limit_negative():
    assert clock_drift_ok(local_ts_sec=1001.0, exchange_ts_sec=1000.0, max_drift_sec=0.5) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_health.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `health.py`**

Create `controllers/market_making/health.py`:

```python
"""Health-check predicates for orderbook freshness and clock sync.

Pure functions; no I/O, no clock reads. Callers pass timestamps in.
"""


def orderbook_age_ok(
    snapshot_ts_sec: float,
    now_sec: float,
    max_age_sec: float,
) -> bool:
    """True iff the orderbook snapshot is at most max_age_sec old."""
    age = now_sec - snapshot_ts_sec
    return age <= max_age_sec


def clock_drift_ok(
    local_ts_sec: float,
    exchange_ts_sec: float,
    max_drift_sec: float,
) -> bool:
    """True iff |local - exchange| <= max_drift_sec."""
    drift = abs(local_ts_sec - exchange_ts_sec)
    return drift <= max_drift_sec
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_health.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add controllers/market_making/health.py tests/test_health.py
git commit -m "feat(health): orderbook freshness and clock drift predicates (M1)

- orderbook_age_ok, clock_drift_ok
- 6 tests covering inside, over, and boundary conditions"
```

---

### Task 4: Metrics Sink (M1)

**Files:**
- Create: `controllers/market_making/metrics_sink.py`
- Create: `tests/test_metrics_sink.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MetricsSink` class with:
    - `__init__(self, db_path: str | Path) -> None`
    - `write(self, snapshot: dict) -> None`
    - `close(self) -> None`
  - Snapshot dict keys (all required): `ts_ms`, `mid`, `micro_price`, `obi`, `factor_bp`, `net_base`, `factor_skew_bp`, `inv_skew_bp`, `reference_price`, `ob_age_sec`, `clock_drift_sec`, `actions_60s`, `kill_engaged`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics_sink.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from controllers.market_making.metrics_sink import MetricsSink


@pytest.fixture
def sink(tmp_path):
    db_path = tmp_path / "metrics.sqlite"
    s = MetricsSink(db_path)
    yield s
    s.close()


def _snapshot(**overrides):
    base = dict(
        ts_ms=1_700_000_000_000,
        mid=65000.0,
        micro_price=65000.5,
        obi=0.1,
        factor_bp=0.5,
        net_base=0.001,
        factor_skew_bp=1.0,
        inv_skew_bp=-0.2,
        reference_price=65001.0,
        ob_age_sec=0.3,
        clock_drift_sec=0.05,
        actions_60s=4,
        kill_engaged=0,
    )
    base.update(overrides)
    return base


def test_write_inserts_row(sink, tmp_path):
    sink.write(_snapshot())
    db_path = tmp_path / "metrics.sqlite"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ts, mid, obi, kill_engaged FROM metrics").fetchall()
    assert rows == [(1_700_000_000_000, 65000.0, 0.1, 0)]


def test_write_multiple_rows(sink, tmp_path):
    sink.write(_snapshot(ts_ms=1, kill_engaged=0))
    sink.write(_snapshot(ts_ms=2, kill_engaged=1))
    db_path = tmp_path / "metrics.sqlite"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ts, kill_engaged FROM metrics ORDER BY ts").fetchall()
    assert rows == [(1, 0), (2, 1)]


def test_write_rejects_missing_required_key(sink):
    snap = _snapshot()
    del snap["mid"]
    with pytest.raises(KeyError):
        sink.write(snap)


def test_close_is_idempotent(sink):
    sink.close()
    sink.close()  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_metrics_sink.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `metrics_sink.py`**

Create `controllers/market_making/metrics_sink.py`:

```python
"""SQLite writer for factor / inventory / health metrics.

One row per call to write(). Schema is created on first connect.
Caller is responsible for downsampling (typically 1 Hz).
"""

import sqlite3
from pathlib import Path
from typing import Union


_REQUIRED_KEYS = (
    "ts_ms",
    "mid",
    "micro_price",
    "obi",
    "factor_bp",
    "net_base",
    "factor_skew_bp",
    "inv_skew_bp",
    "reference_price",
    "ob_age_sec",
    "clock_drift_sec",
    "actions_60s",
    "kill_engaged",
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
  ts                  INTEGER PRIMARY KEY,
  mid                 REAL,
  micro_price         REAL,
  obi                 REAL,
  factor_bp           REAL,
  net_base            REAL,
  factor_skew_bp      REAL,
  inv_skew_bp         REAL,
  reference_price     REAL,
  ob_age_sec          REAL,
  clock_drift_sec     REAL,
  actions_60s         INTEGER,
  kill_engaged        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
"""


_INSERT = """
INSERT OR REPLACE INTO metrics (
  ts, mid, micro_price, obi, factor_bp, net_base,
  factor_skew_bp, inv_skew_bp, reference_price,
  ob_age_sec, clock_drift_sec, actions_60s, kill_engaged
) VALUES (
  :ts_ms, :mid, :micro_price, :obi, :factor_bp, :net_base,
  :factor_skew_bp, :inv_skew_bp, :reference_price,
  :ob_age_sec, :clock_drift_sec, :actions_60s, :kill_engaged
)
"""


class MetricsSink:
    """Thin sqlite writer for factor/inventory/health snapshots."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit
        self._conn.executescript(_SCHEMA)
        self._closed = False

    def write(self, snapshot: dict) -> None:
        for key in _REQUIRED_KEYS:
            if key not in snapshot:
                raise KeyError(f"MetricsSink.write: missing required key {key!r}")
        self._conn.execute(_INSERT, snapshot)

    def close(self) -> None:
        if self._closed:
            return
        self._conn.close()
        self._closed = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_metrics_sink.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add controllers/market_making/metrics_sink.py tests/test_metrics_sink.py
git commit -m "feat(metrics_sink): sqlite writer for factor metrics (M1)

- MetricsSink: open/write/close, autocommit, schema-on-connect
- Required-key validation guards against silent drops
- 4 tests via tmp_path fixture"
```

---

### Task 5: Processed Data Orchestrator (M2)

**Files:**
- Create: `controllers/market_making/processed_data.py`
- Create: `tests/test_processed_data.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes:
  - `factor_math.micro_price`, `obi`, `combine_factor`, `inventory_skew`, `reservation_price`
  - `health.orderbook_age_ok`, `clock_drift_ok`
- Produces:
  - `@dataclass FactorParams` (all the spec §4.2 new fields + risk fields)
  - `@dataclass MarketSnapshot` (raw inputs read from Hummingbot)
  - `compute_processed_data(snap: MarketSnapshot, params: FactorParams) -> dict`
  - Output dict keys: `reference_price` (Decimal), `spread_multiplier` (Decimal), `factor` (Decimal), `factor_skew` (Decimal), `inv_skew` (Decimal), `halt_reason` (Optional[str]).
  - When `halt_reason` is set (any health/kill failure), `spread_multiplier == 0`.

- [ ] **Step 1: Write `tests/conftest.py`**

Create `tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_processed_data.py`:

```python
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


def test_thick_bid_pulls_micro_price_down_factor_skew_negative(default_params, healthy_snapshot):
    snap = healthy_snapshot
    snap.bid_qty = Decimal("9")
    snap.ask_qty = Decimal("1")
    # thick bid → micro_price < mid → micro_signal < 0 → factor < 0 → reservation < mid
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/test_processed_data.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `processed_data.py`**

Create `controllers/market_making/processed_data.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
pytest tests/test_processed_data.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Run full test suite (regression)**

Run:

```bash
pytest -v
```

Expected: 25 passed total (8 factor_math + 6 health + 4 metrics_sink + 7 processed_data).

- [ ] **Step 7: Commit**

```bash
git add controllers/market_making/processed_data.py tests/test_processed_data.py tests/conftest.py
git commit -m "feat(processed_data): orchestrator + kill/health gates (M2)

- FactorParams, MarketSnapshot dataclasses
- compute_processed_data: pure function, no Hummingbot dependency
- Halt paths: daily_loss, stale_orderbook, clock_drift, empty_book
- 7 integration tests using shared conftest fixtures
- Total suite now 25 tests, all green"
```

---

### Task 6: Controller Class (M2)

**Files:**
- Create: `controllers/market_making/factor_mm_btc_perp.py`

**Interfaces:**
- Consumes: `processed_data.compute_processed_data`, `metrics_sink.MetricsSink`.
- Produces:
  - `FactorMMConfig` (extends `MarketMakingControllerConfigBase`)
  - `FactorMMBtcPerp` (extends `MarketMakingControllerBase`)
  - The controller is a thin adapter — no business logic here. Runtime correctness is verified at M4 (live testnet bring-up).

**Note on testing:** This task has no automated tests. The class depends on Hummingbot which isn't necessarily installed in the dev env. All business logic was already tested in Task 5. Wiring correctness is verified at runtime in M4.

- [ ] **Step 1: Write `factor_mm_btc_perp.py`**

Create `controllers/market_making/factor_mm_btc_perp.py`:

```python
"""Hummingbot v2 MarketMakingController adapter.

The class is intentionally thin: it reads Hummingbot state, converts it into a
MarketSnapshot, calls compute_processed_data, and writes the result into
self.processed_data. All math, kill logic, and health checks live in
processed_data.py and its dependencies.
"""

import time
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

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
        self._action_log: list[float] = []
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

        # 1 Hz metrics downsampling
        now = time.time()
        if now - self._last_metrics_emit >= 1.0:
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
        mid = (snap.bid_px + snap.ask_px) / 2 if (snap.bid_qty + snap.ask_qty) else Decimal("0")
        mp = (
            (snap.bid_px * snap.ask_qty + snap.ask_px * snap.bid_qty)
            / (snap.bid_qty + snap.ask_qty)
            if (snap.bid_qty + snap.ask_qty)
            else Decimal("0")
        )
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
```

- [ ] **Step 2: Verify file syntax**

Run:

```bash
python -c "import ast; ast.parse(open('controllers/market_making/factor_mm_btc_perp.py').read())"
```

Expected: no output (success).

- [ ] **Step 3: Run full test suite (regression)**

Run:

```bash
pytest -v
```

Expected: 25 passed (controller has no tests yet; existing 25 should still pass).

- [ ] **Step 4: Commit**

```bash
git add controllers/market_making/factor_mm_btc_perp.py
git commit -m "feat(controller): FactorMMBtcPerp adapter for Hummingbot v2 (M2)

- FactorMMConfig: extends MarketMakingControllerConfigBase with 10 fields
- FactorMMBtcPerp: thin adapter; all business logic delegated to processed_data
- update_processed_data: builds snapshot, calls orchestrator, writes result
- get_executor_config: standard PositionExecutorConfig template
- executors_to_early_stop: drives kill switch via get_active_executors()
- 1 Hz metrics downsampling to factor_metrics.sqlite
- Runtime correctness verified at M4 on live testnet"
```

---

### Task 7: Config Template YAML (M2)

**Files:**
- Create: `conf/controllers/factor_mm_btc.yml.example`

**Interfaces:**
- Consumes: `FactorMMConfig` field names from Task 6.
- Produces: a user-copyable YAML template; the real `factor_mm_btc.yml` (without `.example`) is created on VPS by the user and gitignored.

- [ ] **Step 1: Write the YAML template**

Create `conf/controllers/factor_mm_btc.yml.example`:

```yaml
# Factor MM BTC perpetual — Hummingbot v2 controller config
#
# Copy this file to factor_mm_btc.yml (which is gitignored) and edit the
# numbers if you need to. The defaults match the spec §6.6 risk table.

controller_name: factor_mm_btc_perp
controller_type: market_making
manual_kill_switch: false

# Connector + market
connector_name: binance_perpetual_testnet
trading_pair: BTC-USDT
leverage: 5
position_mode: ONEWAY
total_amount_quote: 200       # USDT notional total

# Quoting (base class)
buy_spreads:   [0.0005, 0.0010]    # 5 bp, 10 bp
sell_spreads:  [0.0005, 0.0010]
buy_amounts_pct:  [0.5, 0.5]
sell_amounts_pct: [0.5, 0.5]
executor_refresh_time: 60
cooldown_time: 15

# Per-position risk (TripleBarrier)
stop_loss:   0.005
take_profit: 0.003
time_limit:  300

# Factor + inventory (our additions)
obi_weight:             0.5
factor_scale_bps:       2
inventory_target:       0
inventory_penalty_bps:  300
inventory_soft_cap:     0.01
inventory_hard_cap:     0.02

# Global risk (our additions)
daily_loss_limit_usdt:  50
max_actions_per_minute: 30
max_orderbook_age_sec:  2.0
max_clock_drift_sec:    0.5
```

- [ ] **Step 2: Commit**

```bash
git add conf/controllers/factor_mm_btc.yml.example
git commit -m "feat(config): controller YAML template (M2)

- All spec §6.6 defaults wired
- .example suffix; gitignore already excludes the real file
- Comments point operator at the spec"
```

---

### Task 8: Deploy Scripts and systemd Units (M3)

**Files:**
- Create: `deploy/bootstrap_vps.sh`
- Create: `deploy/hummingbot.service`
- Create: `deploy/factor-dashboard.service`
- Create: `deploy/pull_and_restart.sh`

**Interfaces:**
- Produces: a one-shot VPS bootstrap, two systemd units, and an idempotent pull/restart helper. These run on the VPS only; smoke is verified by following the README runbook (Task 11) on a real or rented Tokyo VPS.

- [ ] **Step 1: Write `bootstrap_vps.sh`**

Create `deploy/bootstrap_vps.sh`:

```bash
#!/usr/bin/env bash
# Idempotent VPS bootstrap. Re-run safely; existing state is detected.
#
# Pre-req: Ubuntu 22.04 LTS, run as root or with sudo, VPS in Tokyo region.
# Post-state: hummingbot source-installed under botuser, systemd units enabled
#             but NOT started (operator runs `systemctl start ...` after API
#             keys are configured).

set -euo pipefail

REPO_URL="${REPO_URL:?REPO_URL must be set; e.g. REPO_URL=git@github.com:you/factor-mm.git}"

# 0. Base tools + clock + auto-updates
apt update
apt install -y git ufw chrony unattended-upgrades curl wget
systemctl enable --now chrony
timedatectl set-ntp true

# 1. Firewall: deny incoming except SSH (Tailscale manages its own)
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# 2. Tailscale (operator runs `tailscale up` interactively after script)
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

# 3. Bot user + Hummingbot
id -u botuser >/dev/null 2>&1 || useradd -m -s /bin/bash botuser

sudo -u botuser bash <<'EOSU'
set -euo pipefail
cd ~

# 3a. Miniconda
if [ ! -d miniconda3 ]; then
  wget -qO /tmp/miniconda.sh \
    https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash /tmp/miniconda.sh -b -p ~/miniconda3
  rm /tmp/miniconda.sh
fi

# 3b. Hummingbot source
if [ ! -d hummingbot ]; then
  git clone https://github.com/hummingbot/hummingbot.git
  cd hummingbot
  ./install
  source ~/miniconda3/etc/profile.d/conda.sh
  conda activate hummingbot
  ./compile
fi
EOSU

# 4. Our project repo + symlinks
sudo -u botuser bash <<EOSU
set -euo pipefail
cd ~
if [ ! -d factor-mm ]; then
  git clone "${REPO_URL}" factor-mm
fi
ln -sf ~/factor-mm/controllers/market_making/factor_mm_btc_perp.py \
       ~/hummingbot/controllers/market_making/factor_mm_btc_perp.py
ln -sf ~/factor-mm/controllers/market_making/factor_math.py \
       ~/hummingbot/controllers/market_making/factor_math.py
ln -sf ~/factor-mm/controllers/market_making/health.py \
       ~/hummingbot/controllers/market_making/health.py
ln -sf ~/factor-mm/controllers/market_making/metrics_sink.py \
       ~/hummingbot/controllers/market_making/metrics_sink.py
ln -sf ~/factor-mm/controllers/market_making/processed_data.py \
       ~/hummingbot/controllers/market_making/processed_data.py
EOSU

# 5. systemd units
cp deploy/hummingbot.service /etc/systemd/system/
cp deploy/factor-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable hummingbot factor-dashboard

echo
echo "Bootstrap complete. Next steps:"
echo "  1. tailscale up   (interactive login)"
echo "  2. ssh as botuser; run ~/hummingbot/bin/hummingbot_quickstart.py"
echo "     to configure binance_perpetual_testnet API keys"
echo "  3. cp ~/factor-mm/conf/controllers/factor_mm_btc.yml.example \\"
echo "        ~/factor-mm/conf/controllers/factor_mm_btc.yml"
echo "  4. systemctl start hummingbot factor-dashboard"
echo "  5. journalctl -u hummingbot -f"
```

- [ ] **Step 2: Write `hummingbot.service`**

Create `deploy/hummingbot.service`:

```ini
[Unit]
Description=Hummingbot factor MM (BTC perp testnet)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/hummingbot
ExecStart=/home/botuser/miniconda3/envs/hummingbot/bin/python bin/hummingbot_quickstart.py -f conf/controllers/factor_mm_btc.yml
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write `factor-dashboard.service`**

Create `deploy/factor-dashboard.service`:

```ini
[Unit]
Description=Factor MM dashboard (Streamlit)
After=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/factor-mm
ExecStart=/home/botuser/miniconda3/envs/hummingbot/bin/streamlit run dashboard/app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true
Restart=on-failure
RestartSec=5
Environment=METRICS_DB=/home/botuser/hummingbot/data/factor_metrics.sqlite
Environment=TRADES_DB=/home/botuser/hummingbot/data/trades.sqlite

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Write `pull_and_restart.sh`**

Create `deploy/pull_and_restart.sh`:

```bash
#!/usr/bin/env bash
# Pull latest factor-mm code and restart both services.
# Run on VPS as botuser (services need sudo for systemctl).

set -euo pipefail

cd ~/factor-mm
git fetch --prune
git pull --ff-only

sudo systemctl restart hummingbot factor-dashboard

echo "Restarted. Tailing hummingbot journal (Ctrl-C to detach):"
sudo journalctl -u hummingbot -f
```

- [ ] **Step 5: Make shell scripts executable**

Run (in Git Bash on Windows):

```bash
chmod +x deploy/bootstrap_vps.sh deploy/pull_and_restart.sh
```

- [ ] **Step 6: Lint shell with bash -n**

Run:

```bash
bash -n deploy/bootstrap_vps.sh
bash -n deploy/pull_and_restart.sh
```

Expected: no output (no syntax errors). If `bash` is unavailable on the dev machine, skip this step and verify on the VPS at M3.

- [ ] **Step 7: Commit**

```bash
git add deploy/
git commit -m "feat(deploy): VPS bootstrap, systemd units, pull script (M3)

- bootstrap_vps.sh: idempotent install of chrony/ufw/tailscale/conda/hummingbot
- hummingbot.service: source-installed bot under botuser, auto-restart
- factor-dashboard.service: streamlit on 127.0.0.1:8501, headless
- pull_and_restart.sh: dev-loop helper for the VPS
- All controller files are symlinked into Hummingbot tree, not copied"
```

---

### Task 9: Dashboard Queries (M5)

**Files:**
- Create: `dashboard/__init__.py`
- Create: `dashboard/queries.py`
- Create: `tests/test_queries.py`

**Interfaces:**
- Consumes: sqlite file paths from env vars `METRICS_DB` and `TRADES_DB`.
- Produces:
  - `load_metrics(db_path, window_sec=600) -> pandas.DataFrame`
  - `load_recent_fills(db_path, limit=50) -> pandas.DataFrame`
  - `latest_snapshot(db_path) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_queries.py`:

```python
import sqlite3
import time
from pathlib import Path

import pytest

from dashboard.queries import (
    load_metrics,
    latest_snapshot,
)


@pytest.fixture
def metrics_db(tmp_path):
    db = tmp_path / "metrics.sqlite"
    schema = """
    CREATE TABLE metrics (
      ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
      factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
      reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
      actions_60s INTEGER, kill_engaged INTEGER
    );
    """
    with sqlite3.connect(db) as conn:
        conn.executescript(schema)
        now_ms = int(time.time() * 1000)
        rows = [
            (now_ms - 5000, 65000.0, 65000.5, 0.1, 0.5, 0.0, 1.0, 0.0, 65001.0, 0.2, 0.05, 3, 0),
            (now_ms - 4000, 65010.0, 65010.5, 0.2, 0.6, 0.001, 1.1, -0.1, 65011.0, 0.2, 0.05, 4, 0),
            (now_ms - 3000, 65020.0, 65020.5, -0.1, -0.5, 0.002, -1.1, -0.2, 65019.0, 0.2, 0.05, 5, 0),
        ]
        conn.executemany(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
    return db


def test_load_metrics_returns_all_rows_in_window(metrics_db):
    df = load_metrics(metrics_db, window_sec=600)
    assert len(df) == 3
    assert list(df.columns)[0] == "ts"


def test_load_metrics_excludes_rows_outside_window(tmp_path):
    db = tmp_path / "metrics.sqlite"
    schema = """
    CREATE TABLE metrics (
      ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
      factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
      reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
      actions_60s INTEGER, kill_engaged INTEGER
    );
    """
    with sqlite3.connect(db) as conn:
        conn.executescript(schema)
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - 1_000_000  # well outside any reasonable window
        conn.execute(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (old_ms, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0),
        )
        conn.execute(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now_ms, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0),
        )
    df = load_metrics(db, window_sec=600)
    assert len(df) == 1


def test_latest_snapshot_returns_most_recent(metrics_db):
    snap = latest_snapshot(metrics_db)
    assert snap is not None
    assert snap["obi"] == -0.1   # the most recent row in the fixture


def test_latest_snapshot_returns_none_on_empty(tmp_path):
    db = tmp_path / "empty.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE metrics (
          ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
          factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
          reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
          actions_60s INTEGER, kill_engaged INTEGER
        );
        """)
    assert latest_snapshot(db) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_queries.py -v
```

Expected: ImportError on `dashboard.queries`.

- [ ] **Step 3: Implement `dashboard/__init__.py` and `dashboard/queries.py`**

Create empty `dashboard/__init__.py`.

Create `dashboard/queries.py`:

```python
"""Read-only sqlite queries powering the Streamlit dashboard.

All paths are accepted as str or Path. Returns pandas DataFrames so the UI
layer can chart directly. The dashboard process never writes to either db.
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional, Union

import pandas as pd


def load_metrics(
    db_path: Union[str, Path],
    window_sec: int = 600,
) -> pd.DataFrame:
    """Load metric rows within the last window_sec seconds."""
    cutoff_ms = int((time.time() - window_sec) * 1000)
    with sqlite3.connect(str(db_path)) as conn:
        df = pd.read_sql(
            "SELECT * FROM metrics WHERE ts >= ? ORDER BY ts",
            conn,
            params=(cutoff_ms,),
        )
    return df


def latest_snapshot(db_path: Union[str, Path]) -> Optional[dict]:
    """Return the most recent metrics row as a dict, or None if table is empty."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM metrics ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def load_recent_fills(
    db_path: Union[str, Path],
    limit: int = 50,
) -> pd.DataFrame:
    """Load recent fills from Hummingbot's trades.sqlite.

    Hummingbot's trade table schema may evolve; tolerate missing tables.
    """
    try:
        with sqlite3.connect(str(db_path)) as conn:
            df = pd.read_sql(
                "SELECT timestamp, trading_pair, trade_type, price, amount "
                "FROM TradeFill ORDER BY timestamp DESC LIMIT ?",
                conn,
                params=(limit,),
            )
        return df
    except (sqlite3.OperationalError, pd.io.sql.DatabaseError):
        return pd.DataFrame(
            columns=["timestamp", "trading_pair", "trade_type", "price", "amount"]
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_queries.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

Run:

```bash
pytest -v
```

Expected: 29 passed (25 prior + 4 new).

- [ ] **Step 6: Commit**

```bash
git add dashboard/__init__.py dashboard/queries.py tests/test_queries.py
git commit -m "feat(dashboard): sqlite query layer + 4 tests (M5)

- load_metrics(window_sec), latest_snapshot, load_recent_fills
- Tolerates missing TradeFill table (early bring-up)
- Tests cover window inclusion/exclusion and empty-table case"
```

---

### Task 10: Dashboard Streamlit App (M5)

**Files:**
- Create: `dashboard/app.py`

**Interfaces:**
- Consumes: `dashboard.queries`.
- Produces: an `app.py` runnable with `streamlit run dashboard/app.py`. Reads metrics db path from env var `METRICS_DB` (default `data/factor_metrics.sqlite` relative to working dir) and trades db from `TRADES_DB`.

**Note on testing:** No automated tests. Streamlit apps are visual. Verification is local-run during this task and visual inspection on VPS at M5.

- [ ] **Step 1: Write `dashboard/app.py`**

Create `dashboard/app.py`:

```python
"""Factor MM dashboard.

Run:
  streamlit run dashboard/app.py

Reads sqlite paths from env:
  METRICS_DB  (default: data/factor_metrics.sqlite)
  TRADES_DB   (default: data/trades.sqlite)
"""

import os
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.queries import latest_snapshot, load_metrics, load_recent_fills


METRICS_DB = Path(os.environ.get("METRICS_DB", "data/factor_metrics.sqlite"))
TRADES_DB = Path(os.environ.get("TRADES_DB", "data/trades.sqlite"))

REFRESH_SEC = 2
WINDOW_SEC = 600  # 10 minutes of metrics history


st.set_page_config(page_title="Factor MM", layout="wide")

# Top banner
snap = latest_snapshot(METRICS_DB) if METRICS_DB.exists() else None
kill_on = bool(snap and snap.get("kill_engaged"))
banner_color = "#7a1f1f" if kill_on else "#0e1117"
st.markdown(
    f"<div style='background:{banner_color};padding:8px 16px;"
    f"color:white;font-weight:600'>Factor MM · BTC-USDT Perp · TESTNET"
    f" — Kill: {'ON' if kill_on else 'OFF'}</div>",
    unsafe_allow_html=True,
)

# Big numbers
cols = st.columns(6)
if snap:
    cols[0].metric("Mid", f"{snap['mid']:.2f}")
    cols[1].metric("Net Base (BTC)", f"{snap['net_base']:+.4f}")
    cols[2].metric("Reservation", f"{snap['reference_price']:.2f}")
    cols[3].metric("Factor (bp)", f"{snap['factor_bp']:+.2f}")
    cols[4].metric("Actions/60s", f"{snap['actions_60s']}")
    cols[5].metric("OB age (s)", f"{snap['ob_age_sec']:.2f}")
else:
    for c in cols:
        c.metric("—", "no data")

# Time-series rows
df = load_metrics(METRICS_DB, window_sec=WINDOW_SEC) if METRICS_DB.exists() else pd.DataFrame()

if not df.empty:
    df["t"] = pd.to_datetime(df["ts"], unit="ms")

    # Row 1: factor signals
    fig1 = make_subplots(specs=[[{"secondary_y": True}]])
    fig1.add_trace(
        go.Scatter(x=df["t"], y=df["factor_bp"], name="Factor (bp)"),
        secondary_y=False,
    )
    fig1.add_trace(
        go.Scatter(x=df["t"], y=df["obi"], name="OBI", line=dict(dash="dot")),
        secondary_y=True,
    )
    fig1.update_layout(height=240, margin=dict(l=20, r=20, t=30, b=20),
                       title="Factor signal (bp) + OBI")
    st.plotly_chart(fig1, use_container_width=True)

    # Row 2: inventory + skews
    fig2 = make_subplots(specs=[[{"secondary_y": True}]])
    fig2.add_trace(
        go.Scatter(x=df["t"], y=df["net_base"], name="Net base (BTC)"),
        secondary_y=False,
    )
    fig2.add_trace(
        go.Scatter(x=df["t"], y=df["factor_skew_bp"], name="Factor skew (bp)"),
        secondary_y=True,
    )
    fig2.add_trace(
        go.Scatter(x=df["t"], y=df["inv_skew_bp"], name="Inv skew (bp)"),
        secondary_y=True,
    )
    fig2.update_layout(height=240, margin=dict(l=20, r=20, t=30, b=20),
                       title="Inventory + skew")
    st.plotly_chart(fig2, use_container_width=True)

    # Row 3: health
    fig3 = make_subplots(rows=1, cols=3,
                         subplot_titles=("OB age (s)", "Clock drift (s)", "Actions/60s"))
    fig3.add_trace(go.Scatter(x=df["t"], y=df["ob_age_sec"], name="ob_age"),
                   row=1, col=1)
    fig3.add_trace(go.Scatter(x=df["t"], y=df["clock_drift_sec"], name="drift"),
                   row=1, col=2)
    fig3.add_trace(go.Scatter(x=df["t"], y=df["actions_60s"], name="actions"),
                   row=1, col=3)
    fig3.update_layout(height=240, showlegend=False,
                       margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("No metrics yet. Waiting for the bot to write rows to "
            f"{METRICS_DB}.")

# Row 4: recent fills
fills = load_recent_fills(TRADES_DB, limit=50) if TRADES_DB.exists() else pd.DataFrame()
st.subheader("Recent fills (last 50)")
if fills.empty:
    st.text("No fills yet.")
else:
    st.dataframe(fills, use_container_width=True, height=300)

# Refresh
time.sleep(REFRESH_SEC)
st.rerun()
```

- [ ] **Step 2: Sanity-run locally with a stub metrics db**

Build a tiny stub file so the app has something to render:

```bash
python - <<'PY'
import sqlite3, time
from pathlib import Path
db = Path("data") / "factor_metrics.sqlite"
db.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(db) as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS metrics (
      ts INTEGER PRIMARY KEY, mid REAL, micro_price REAL, obi REAL,
      factor_bp REAL, net_base REAL, factor_skew_bp REAL, inv_skew_bp REAL,
      reference_price REAL, ob_age_sec REAL, clock_drift_sec REAL,
      actions_60s INTEGER, kill_engaged INTEGER
    );""")
    now_ms = int(time.time() * 1000)
    rows = [(now_ms - i*1000, 65000+i, 65000+i+0.5, 0.1*((-1)**i),
             0.3*((-1)**i), 0.001*((-1)**i), 0.5, -0.2,
             65001+i, 0.2, 0.05, 3, 0) for i in range(60)]
    c.executemany(
      "INSERT OR REPLACE INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
PY
```

Then run:

```bash
streamlit run dashboard/app.py
```

Expected: browser opens at `http://localhost:8501`; the page shows kill banner, 6 big numbers, 3 charts, and "No fills yet."

Stop with `Ctrl-C`. Delete `data/factor_metrics.sqlite` (it is gitignored).

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.py
git commit -m "feat(dashboard): Streamlit UI for factor + inventory + health (M5)

- 6 big-number top row, 3 time-series rows, recent-fills table
- Kill banner turns red when kill_engaged
- 2-second auto-refresh via st.rerun()
- Reads METRICS_DB / TRADES_DB from env, defaults relative to cwd"
```

---

### Task 11: README + Deployment Runbook (M3–M5)

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents the end-to-end first-run on a fresh VPS. No new code.

- [ ] **Step 1: Expand `README.md`**

Replace the entire `README.md` with:

```markdown
# factor-mm

Factor-driven market-making controller for `BTC-USDT` USDT-M perpetual on Hummingbot v2.

Design: `docs/superpowers/specs/2026-06-19-factor-mm-binance-perp-design.md`
Plan:   `docs/superpowers/plans/2026-06-19-factor-mm-binance-perp.md`

## What it does

- Computes a Micro-price + OBI factor each tick from L1 book state
- Adds an inventory-penalty skew that pulls net position back to target
- Sets Hummingbot's `reference_price` so the base class quotes around it
- Engages a kill switch on daily-loss / stale-book / clock-drift / empty-book
- Writes 1 Hz metrics to a separate sqlite for a Streamlit dashboard

This is a **learning project**, not a money printer. M9 (mainnet) is optional and always small.

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Expected: ~29 tests pass.

## Deployment (VPS, first run)

This is the end-to-end runbook. Plan ~60 minutes the first time.

### 1. Provision

- Provider: Vultr High Frequency Tokyo (or AWS Lightsail Tokyo). 2 vCPU / 4 GB / 30 GB SSD. Ubuntu 22.04.
- Record the public IPv4 in `~/.ssh/config` as `Host factor-vps`.

### 2. SSH baseline (your own dev machine)

```bash
ssh root@<vps-ip>
# Change SSH port, disable password auth, install ssh key. Skipped here for brevity.
```

### 3. Bootstrap the VPS

Copy and run the script:

```bash
scp deploy/bootstrap_vps.sh root@<vps-ip>:/root/
ssh root@<vps-ip>
REPO_URL=git@github.com:<you>/factor-mm.git bash /root/bootstrap_vps.sh
```

### 4. Bring Tailscale up

```bash
tailscale up    # interactive login
tailscale ip -4  # note the 100.x.x.x address
```

### 5. Configure Binance API key

In the Binance Futures Testnet console (https://testnet.binancefuture.com/):

- Generate API key
- Set **IP whitelist = VPS public IP** (the one you provisioned)
- Permissions: enable **Reading** and **Futures**; ensure **Withdrawal is DISABLED**

Then on the VPS:

```bash
sudo -iu botuser
cd ~/hummingbot
./bin/hummingbot_quickstart.py
# At the prompt:
> connect binance_perpetual_testnet
# Paste API key and secret when prompted. They are written to
# ~/hummingbot/conf/connectors/binance_perpetual_testnet.yml
> exit
```

Lock the file:

```bash
chmod 600 ~/hummingbot/conf/connectors/*.yml
```

### 6. Place the controller config

```bash
cp ~/factor-mm/conf/controllers/factor_mm_btc.yml.example \
   ~/factor-mm/conf/controllers/factor_mm_btc.yml
ln -sf ~/factor-mm/conf/controllers/factor_mm_btc.yml \
       ~/hummingbot/conf/controllers/factor_mm_btc.yml
```

Edit defaults only if you have a reason. Spec §6.6 is the source of truth.

### 7. Start the services

```bash
exit    # back to root
systemctl start hummingbot factor-dashboard
journalctl -u hummingbot -f
```

Expected within ~30 seconds:

- Log shows `connect binance_perpetual_testnet` succeeded
- Log shows `factor_mm_btc_perp` controller started
- Within a few minutes you see `CreateExecutorAction` / `StopExecutorAction` events as the bot quotes

### 8. Open the dashboard

From your dev machine (Tailscale connected):

```
http://<tailscale-100.x.x.x>:8501
```

You should see:

- Kill banner OFF
- Big numbers populated (Mid, Net Base, Reservation, Factor, Actions/60s, OB age)
- 3 time-series charts filling in over a couple of minutes
- "Recent fills" table populating after first fill

### 9. Day-to-day operations

**Pull and restart after code changes:**

```bash
ssh botuser@<vps-ip>
~/factor-mm/deploy/pull_and_restart.sh
```

**Stop everything:**

```bash
sudo systemctl stop hummingbot factor-dashboard
```

**Reset kill switch:** the kill is sticky in-process. Restart hummingbot to clear:

```bash
sudo systemctl restart hummingbot
```

**Check logs:**

```bash
sudo journalctl -u hummingbot -n 200 --no-pager
sudo journalctl -u factor-dashboard -n 50 --no-pager
```

## Milestones beyond first run

See spec §10 for M6 (7-day smoke), M7 (7-day tuning), M8 (Go/No-go review), M9 (optional mainnet small-amount).

## Memory

This is a learning project. M9 is optional and always small. If the factor stops working on mainnet, the right move is to go back to testnet to find a new factor, not add leverage.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): end-to-end deployment runbook (M3–M5)

- Provision → SSH baseline → bootstrap → Tailscale → API key →
  controller config → systemd start → dashboard verify → daily ops
- All hard-to-undo steps (API permissions, file modes) called out
- M6+ pointers to spec §10"
```

---

## Deferred to V2 (intentionally out of scope)

The plan delivers a working **V1**. The following spec features are deliberately deferred to a follow-up plan after V1 is running on testnet, so M0–M5 stays small enough to actually ship in a weekend. Each gap is documented in code via inline TODO comments or in the spec by `[需 testnet 验证]` markers.

| Spec ref | Deferred item | V1 substitute / known gap |
|---|---|---|
| §5.2 (L2 asymmetric sizing) | Override `get_price_and_amount` (or whatever hook Hummingbot exposes) to shrink size on the inventory-aligned side and grow on the opposite side when `|net_base| > inventory_soft_cap` | L1 software skew via `inventory_penalty_bps` is the only inventory force; base class quotes equally both sides |
| §5.3 (L3 forced flatten) | Emit `OrderExecutorConfig(MARKET)` when `|net_base| > inventory_hard_cap`; requires overriding `determine_executor_actions` to inject `CreateExecutorAction` | Manual intervention required if inventory exceeds hard cap |
| §6.4 (R3 rate limit enforcement) | Block new `CreateExecutorAction`s once `len(_action_log)` hits `max_actions_per_minute` | Counter recorded and surfaced in dashboard, but never blocks |
| ~~§6.5 (real exchange server time)~~ | ~~Wire `_build_snapshot`'s `exchange_ts_sec` to a periodically cached `binance.timev3` REST call~~ | **Done (2026-06-19, M4 prereq):** `controllers/market_making/exchange_time.py` provides `estimate_exchange_time_sec` (pure, 5-tested) + sync `urllib` REST fetch; cached 300s; falls back to stale-cache or `now` on fetcher failure |
| §4.2 V7 (Hummingbot Pydantic version) | If master uses Pydantic v2 syntax differently, adjust `Field` / validators in `FactorMMConfig` | Spec §4.2 uses `Field(default=...)` which works in both v1 and v2 |

Resolution path for the first three: a follow-up plan `docs/superpowers/plans/YYYY-MM-DD-factor-mm-v2-inventory-and-rate-limit.md` after M5 lands. The fourth is a M4 prerequisite: do not start the testnet bot without wiring real server time, otherwise the clock-drift health check is a no-op.

---

## After All Tasks

Final acceptance check on the dev machine:

```bash
pytest -v
```

Expected: 29 passed (8 + 6 + 4 + 7 + 4).

```bash
git log --oneline
```

Expected: 12 commits — initial spec commit + 11 task commits.

Spec milestones M0–M5 (and the runbook portions of M3–M5) are now implemented. Operational milestones M6 (1-week smoke), M7 (1-week tuning), M8 (Go/No-go review), M9 (optional small mainnet) are exercised by running the bot per the README, not by further coding.
