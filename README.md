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
