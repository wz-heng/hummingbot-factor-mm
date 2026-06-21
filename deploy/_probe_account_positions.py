"""One-off: peek into the live Hummingbot process's connector to find
the right API for perpetual position. Runs against the live bot's pickled
MarketsRecorder state via sqlite — actually we can't introspect the live
process directly, so instead we check the connector class to see what
attribute exists.
"""

import inspect


def probe():
    from hummingbot.connector.derivative.binance_perpetual.binance_perpetual_derivative import (
        BinancePerpetualDerivative,
    )

    print("--- BinancePerpetualDerivative position-related attributes ---")
    for name in dir(BinancePerpetualDerivative):
        if any(k in name.lower() for k in ("position", "balance", "account")) and not name.startswith("_"):
            print(f"  {name}")

    print()
    print("--- account_positions property/method? ---")
    cls = BinancePerpetualDerivative
    for cls_check in (cls, *cls.__mro__):
        attr = cls_check.__dict__.get("account_positions")
        if attr is not None:
            print(f"  Found on {cls_check.__name__}: {type(attr).__name__}")
            if hasattr(attr, "fget"):  # @property
                try:
                    print(inspect.getsource(attr.fget))
                except Exception as e:
                    print("  src err:", e)
            break
    else:
        print("  (not directly defined; might be inherited attribute)")

    print()
    print("--- Position dataclass shape ---")
    try:
        from hummingbot.connector.perpetual_trading import Position
        for name in dir(Position):
            if not name.startswith("_"):
                print(f"  {name}")
    except Exception as e:
        print("  err:", e)


if __name__ == "__main__":
    probe()
