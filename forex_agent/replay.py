"""Historical adapter for the same multi-agent decision used by the CLI/API.

The caller supplies as-of calendar snapshots and completed higher-timeframe bars.
No future calendar revision or higher-timeframe candle is passed to the agent.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import asdict
from datetime import timedelta

from .agent import ForexCoordinator
from .journal import Journal
from .models import CONTEXT, Candle, SECONDS, ValidationError, iso, utc


class AgentReplay:
    def __init__(self, engine, dataset: dict):
        self.engine = engine
        self.context = {}
        self.context_times = {}
        raw_context = dataset.get("context_frames", {})
        for pair in engine.pairs:
            self.context[pair], self.context_times[pair] = {}, {}
            for timeframe in CONTEXT[engine.timeframe]:
                try:
                    rows = raw_context[pair][timeframe]
                except (KeyError, TypeError):
                    raise ValidationError(f"Replay sinyal membutuhkan context_frames {pair} {timeframe}.") from None
                if not isinstance(rows, list) or len(rows) < 250:
                    raise ValidationError(f"Context {pair} {timeframe} membutuhkan >=250 candle tutup.")
                bars = [Candle.parse(row) for row in rows]
                if any(b.time <= a.time for a, b in zip(bars, bars[1:])):
                    raise ValidationError("Context timeframe tidak urut atau duplikat.")
                interval = timedelta(seconds=SECONDS[timeframe])
                for previous, current in zip(bars, bars[1:]):
                    gap = current.time - previous.time
                    weekend = (previous.time.weekday() in (4, 5)
                               and current.time.weekday() in (6, 0)
                               and interval < gap <= timedelta(days=3))
                    if gap != interval and not weekend:
                        raise ValidationError(f"Context {pair} {timeframe} memiliki candle hilang.")
                self.context[pair][timeframe] = rows
                self.context_times[pair][timeframe] = [bar.time for bar in bars]
        history = dataset.get("fundamentals_history")
        if not isinstance(history, list) or not history:
            raise ValidationError("Replay sinyal membutuhkan fundamentals_history berurutan menurut as_of.")
        if any(not isinstance(item, dict) or "as_of" not in item for item in history):
            raise ValidationError("Setiap snapshot kalender memerlukan as_of.")
        self.calendars = history
        self.calendar_times = [utc(item["as_of"]) for item in history]
        if any(b <= a for a, b in zip(self.calendar_times, self.calendar_times[1:])):
            raise ValidationError("fundamentals_history harus urut dan tanpa timestamp duplikat.")
        for calendar, fetched in zip(history, self.calendar_times):
            for event in calendar.get("events", []):
                if utc(event["time"]) > fetched and event.get("actual") is not None:
                    raise ValidationError("Kalender historis membocorkan actual yang belum diumumkan.")
        self.journal = Journal(timezone=dataset.get("timezone", "Asia/Bangkok"))
        self.agent = ForexCoordinator(self.journal, engine.policy)
        self.status_counts = Counter()
        self.block_counts = Counter()

    def close(self):
        self.journal.close()

    def opened(self, position):
        self.journal.open_trade({"id": position.client_id, "pair": position.pair,
                                 "side": position.side, "opened_at": iso(position.opened_at),
                                 "units": position.units, "entry": position.entry,
                                 "stop": position.stop, "target": position.target,
                                 "initial_risk": position.initial_risk, "simulated": True,
                                 "setup": "AGENT_REPLAY"})

    def closed(self, position, when, net_pnl):
        self.journal.close_trade(position.client_id, net_pnl, when)

    def report(self, pair: str, index: int) -> dict | None:
        engine = self.engine
        if index < 249:
            self.status_counts["WARMUP"] += 1
            return None
        now = engine.times[index]
        frames = {engine.timeframe: engine.raw[pair][max(0, index - 4999):index + 1]}
        for timeframe in CONTEXT[engine.timeframe]:
            end = bisect_right(self.context_times[pair][timeframe], now)
            if end < 250:
                self.status_counts["WARMUP"] += 1
                return None
            frames[timeframe] = self.context[pair][timeframe][max(0, end - 5000):end]
        calendar_index = bisect_right(self.calendar_times, now) - 1
        fundamentals = self.calendars[calendar_index] if calendar_index >= 0 else {"status": "unknown"}
        account = engine._account(index)
        mid = engine.bars[pair][index].close
        spread = engine.spreads[pair][index]
        factor = engine._conversion(pair, index)
        snapshot = {"pair": pair, "source": engine.source, "simulated": True,
                    "as_of": iso(now), "frames": frames,
                    "quote": {"bid": mid - spread / 2, "ask": mid + spread / 2,
                              "time": iso(now), "tradeable": True},
                    "instrument": asdict(engine.instruments[pair]),
                    "account": {"currency": account.currency, "equity": account.equity,
                                "free_margin": account.free_margin,
                                "day_start_equity": account.day_start_equity,
                                "open_trade_count": len(engine.positions), "as_of": iso(now)},
                    "conversion": {"account_currency": account.currency,
                                   "quote_currency": pair.split("/")[1],
                                   "loss_factor": factor, "gain_factor": factor,
                                   "position_factor": factor, "time": iso(now)},
                    "fundamentals": fundamentals}
        report = self.agent.analyze(snapshot, engine.timeframe, "signal", clock=now)
        self.status_counts[report["status"]] += 1
        if report["status"] == "NO_TRADE":
            blocks = report.get("fundamentals", {}).get("blocks", [])
            if blocks:
                self.block_counts.update(blocks)
            elif report.get("reasons"):
                self.block_counts[report["reasons"][-1]] += 1
        return report
