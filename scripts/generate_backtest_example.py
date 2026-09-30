"""Regenerate a deterministic example; all prices are synthetic."""

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path


def main():
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    values = [1.1 + 0.0006 * math.sin(i / 5) + i * 0.000002 for i in range(181)]
    rows = []
    for i in range(180):
        opening, closing = values[i], values[i + 1]
        rows.append({"time": (start + timedelta(minutes=5 * (i + 1))).isoformat().replace("+00:00", "Z"),
                     "open": opening, "high": max(opening, closing) + 0.00006,
                     "low": min(opening, closing) - 0.00006, "close": closing,
                     "volume": 1, "complete": True})
    example = {"simulated": True, "timeframe": "M5", "initial_equity": 10000,
               "account_currency": "USD", "bars": {"EUR/USD": rows},
               "instruments": {"EUR/USD": {"pair": "EUR/USD", "pip_size": 0.0001,
                                           "tick_size": 0.00001, "contract_size": 100000,
                                           "units_step": 1000, "min_units": 1000,
                                           "max_units": 1000000, "margin_rate": 0.05}},
               "assumptions": {"spread": {"EUR/USD": 0.00002},
                               "slippage": {"EUR/USD": 0.00001},
                               "max_drawdown_fraction": 0.1}}
    target = Path(__file__).resolve().parents[1] / "examples" / "backtest.synthetic.json"
    target.write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
