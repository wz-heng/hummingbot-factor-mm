"""One-off: dump position-related methods on MarketMakingControllerBase
plus the source of get_current_base_position and check_position_rebalance.
"""

import inspect

from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
)

print("--- MarketMakingControllerBase methods containing position/balance/base ---")
for m in dir(MarketMakingControllerBase):
    if any(k in m.lower() for k in ("position", "balance", "base")):
        print(f"  {m}")

print()
print("--- get_current_base_position source ---")
try:
    print(inspect.getsource(MarketMakingControllerBase.get_current_base_position))
except Exception as e:
    print("err:", e)

print()
print("--- check_position_rebalance source (first 60 lines) ---")
try:
    src = inspect.getsource(MarketMakingControllerBase.check_position_rebalance)
    print("\n".join(src.splitlines()[:60]))
except Exception as e:
    print("err:", e)
