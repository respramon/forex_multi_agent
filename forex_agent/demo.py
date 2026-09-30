"""Deterministic synthetic prices. All frames aggregate the SAME M5 path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from .models import SECONDS, iso, pair_name


def make_snapshot(pair: str = "EUR/USD", scenario: str = "bullish") -> dict:
    pair = pair_name(pair)
    end = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    steps = 330 * 288
    scale = {"EUR/USD": 1.0, "GBP/USD": 1.16, "AUD/USD": 0.61, "USD/JPY": 136.0}[pair]
    frames = {tf: [] for tf in SECONDS}
    buckets: dict = {}
    previous = None
    for i in range(steps + 1):
        # A rising background with nested waves; no historical or real quotes.
        t = i - steps
        value = 1.10 + 10 * (0.0000006 * t + 0.00014 * math.sin(t / 17 + 1.5) + 0.000045 * math.sin(t / 3.2))
        if scenario == "range":
            value = 1.1 + 0.001 * math.sin(t / 5)
        value *= scale
        if previous is None:
            previous = value
            continue
        stamp = end + timedelta(minutes=5 * t)
        c = {"time": iso(stamp), "open": previous,
             "high": max(previous, value) + 0.0002 * scale,
             "low": min(previous, value) - 0.0002 * scale,
             "close": value, "volume": 25, "complete": True}
        for tf, sec in SECONDS.items():
            bucket = buckets.get(tf)
            if bucket is None:
                bucket = dict(c)
                buckets[tf] = bucket
            else:
                bucket.update(time=c["time"], high=max(bucket["high"], c["high"]),
                              low=min(bucket["low"], c["low"]), close=c["close"], volume=bucket["volume"] + c["volume"])
            if int(stamp.timestamp()) % sec == 0:
                frames[tf].append(bucket)
                if len(frames[tf]) > 300:
                    frames[tf].pop(0)
                buckets[tf] = None
        previous = value
    mid = frames["M5"][-1]["close"]
    spread = 0.00002 * scale
    quote_currency = pair.split("/")[1]
    loss_factor = 1 / mid if quote_currency == "JPY" else 1
    pip = 0.01 if pair == "USD/JPY" else 0.0001
    tick = 0.001 if pair == "USD/JPY" else 0.00001
    fundamental = {"status": "ok", "as_of": iso(end), "source": "SYNTHETIC TEST CALENDAR",
                   "coverage_from": iso(end - timedelta(hours=24)), "coverage_to": iso(end + timedelta(hours=24)),
                   "currencies": pair.split("/"), "events": [],
                   "sentiment": []}
    if scenario == "news":
        fundamental["events"] = [{"time": iso(end + timedelta(minutes=15)), "currency": "USD",
                                  "impact": "high", "title": "Rilis inflasi contoh (fiktif)",
                                  "source": "SYNTHETIC", "actual": None, "forecast": "contoh", "previous": "contoh"}]
    return {"pair": pair, "source": "SYNTHETIC — not market data", "simulated": True,
            "as_of": iso(end), "frames": frames,
            "quote": {"bid": mid - spread / 2, "ask": mid + spread / 2,
                      "time": iso(end - timedelta(hours=2)) if scenario == "stale" else iso(end), "tradeable": True},
            "instrument": {"pair": pair, "pip_size": pip, "tick_size": tick,
                           "contract_size": 100000, "units_step": 1000,
                           "min_units": 1000, "max_units": 1000000,
                           "margin_rate": 0.05, "spec_source": "SYNTHETIC BROKER — replace for real use",
                           "commission_per_unit_roundtrip": 0, "min_commission_roundtrip": 0},
            "account": {"currency": "USD", "equity": 10000, "free_margin": 10000,
                        "day_start_equity": 10000, "open_trade_count": 0, "as_of": iso(end)},
            "conversion": {"account_currency": "USD", "quote_currency": quote_currency,
                           "loss_factor": loss_factor, "gain_factor": loss_factor,
                           "position_factor": loss_factor, "time": iso(end)}, "fundamentals": fundamental}
