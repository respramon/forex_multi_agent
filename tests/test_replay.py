from copy import deepcopy
from datetime import timedelta
import unittest

from forex_agent.backtest import Backtest
from forex_agent.demo import make_snapshot
from forex_agent.models import ValidationError, iso, utc


class AgentReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = make_snapshot()

    def data(self):
        snapshot = self.snapshot
        bars = deepcopy(snapshot["frames"]["M15"])
        next_bar = deepcopy(bars[-1])
        next_bar["time"] = iso(utc(next_bar["time"]) + timedelta(minutes=15))
        next_bar["open"] = bars[-1]["close"]
        next_bar["close"] = next_bar["open"]
        next_bar["high"] = next_bar["open"] + 0.00004
        next_bar["low"] = next_bar["open"] - 0.00004
        bars.append(next_bar)
        return {"simulated": True, "source": "SYNTHETIC TEST", "timeframe": "M15",
                "initial_equity": 10000, "account_currency": "USD",
                "bars": {"EUR/USD": bars},
                "instruments": {"EUR/USD": snapshot["instrument"]},
                "context_frames": {"EUR/USD": {tf: snapshot["frames"][tf] for tf in ("H1", "H4")}},
                "fundamentals_history": [snapshot["fundamentals"]],
                "assumptions": {"spread": {"EUR/USD": 0.00002},
                                "slippage": {"EUR/USD": 0}}}

    def test_shared_signal_rules_submit_and_fill_next_open(self):
        result = Backtest(self.data(), agent_replay=True).run()
        self.assertEqual(result["strategy"], "forex_agent_signal")
        self.assertEqual([item["kind"] for item in result["events"]],
                         ["order_submitted", "fill"])
        self.assertEqual(result["events"][0]["setup"], "TREND_FOLLOWING")
        self.assertEqual(result["open_positions"], ["EUR/USD"])

    def test_unknown_calendar_or_open_outside_entry_area_does_not_fill(self):
        no_calendar = self.data()
        no_calendar["fundamentals_history"][0] = {**no_calendar["fundamentals_history"][0],
                                                   "status": "unknown"}
        blocked = Backtest(no_calendar, agent_replay=True).run()
        self.assertEqual(blocked["events"], [])
        self.assertTrue(any("Kalender" in reason for reason in
                            blocked["decision_summary"]["blocks"]))
        gap = self.data()
        gap["bars"]["EUR/USD"][-1].update(open=1.12, high=1.121, low=1.119, close=1.12)
        result = Backtest(gap, agent_replay=True).run()
        self.assertEqual([item["kind"] for item in result["events"]],
                         ["order_submitted", "fill_rejected"])
        self.assertEqual(result["open_positions"], [])

    def test_future_actual_and_missing_context_are_rejected(self):
        data = self.data()
        data["fundamentals_history"][0] = deepcopy(data["fundamentals_history"][0])
        data["fundamentals_history"][0]["events"] = [{"time": data["bars"]["EUR/USD"][-1]["time"],
                                                       "currency": "USD", "impact": "high",
                                                       "source": "test", "title": "future", "actual": "5%"}]
        with self.assertRaisesRegex(ValidationError, "membocorkan"):
            Backtest(data, agent_replay=True)
        data = self.data()
        del data["context_frames"]["EUR/USD"]["H4"]
        with self.assertRaisesRegex(ValidationError, "H4"):
            Backtest(data, agent_replay=True)


if __name__ == "__main__":
    unittest.main()
