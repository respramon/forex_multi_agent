"""Generate a deterministic demonstration of the live-rule replay data contract."""

import json
from datetime import timedelta
from pathlib import Path

from forex_agent.demo import make_snapshot
from forex_agent.models import iso, utc


def main():
    snapshot = make_snapshot()
    bars = list(snapshot["frames"]["M15"])
    last_close = bars[-1]["close"]
    for step in (1, 2):
        close = last_close if step == 1 else last_close - 0.004
        bars.append({"time": iso(utc(bars[-1]["time"]) + timedelta(minutes=15)),
                     "open": last_close, "high": last_close + 0.00004,
                     "low": min(last_close - 0.00004, close), "close": close,
                     "volume": 25, "complete": True})
    data = {"simulated": True, "source": "SYNTHETIC agent replay fixture",
            "timeframe": "M15", "initial_equity": 10000,
            "account_currency": "USD", "timezone": "Asia/Bangkok",
            "bars": {"EUR/USD": bars},
            "instruments": {"EUR/USD": snapshot["instrument"]},
            "context_frames": {"EUR/USD": {tf: snapshot["frames"][tf]
                                             for tf in ("H1", "H4")}},
            "fundamentals_history": [snapshot["fundamentals"]],
            "assumptions": {"spread": {"EUR/USD": 0.00002},
                            "slippage": {"EUR/USD": 0.00001}}}
    target = Path("examples/agent-replay.synthetic.json")
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(f"Generated {target}")


if __name__ == "__main__":
    main()
