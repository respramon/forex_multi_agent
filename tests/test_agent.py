from copy import deepcopy
from datetime import timedelta
import unittest
from forex_agent.agent import ForexAgent, format_report
from forex_agent.demo import make_snapshot
from forex_agent.journal import Journal
from forex_agent.models import iso, utc


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = make_snapshot()

    def setUp(self):
        self.data = deepcopy(self.fixture)
        self.journal = Journal()
        self.agent = ForexAgent(self.journal)

    def tearDown(self):
        self.journal.close()

    def signal(self):
        return self.agent.analyze(self.data, "M15", "signal")

    def assert_blocked(self, report):
        self.assertEqual(report["status"], "NO_TRADE", report["reasons"])
        for field in ("entry_area", "stop_loss", "take_profit", "risk_reward"):
            self.assertIsNone(report[field])

    def test_demo_issues_a_sized_signal(self):
        r = self.signal()
        self.assertEqual(r["status"], "BUY", r["reasons"])
        self.assertGreaterEqual(r["risk_reward"], 2)
        self.assertLessEqual(r["risk"]["estimated_loss"], 100 + 1e-8)
        self.assertTrue(r["simulated"])
        self.assertIn("RISIKO YANG PERLU DIPERHATIKAN:", format_report(r))

    def test_duplicate_signal_is_blocked(self):
        self.assertEqual(self.signal()["status"], "BUY")
        self.assert_blocked(self.signal())

    def test_analyst_has_no_entry(self):
        r = self.agent.analyze(self.data, "M15", "analyst")
        self.assertEqual(r["status"], "ANALYSIS_ONLY")
        self.assertIsNone(r["entry_area"])

    def test_unknown_calendar_is_veto(self):
        self.data["fundamentals"] = {"status": "unknown"}
        self.assert_blocked(self.signal())

    def test_high_impact_news_is_veto(self):
        self.data["fundamentals"]["events"] = [{"time": self.data["as_of"], "currency": "USD", "impact": "high",
                                               "title": "Synthetic CPI", "source": "test"}]
        self.assert_blocked(self.signal())

    def test_stale_and_future_data(self):
        for minutes in (-5, 5):
            self.data["quote"]["time"] = iso(utc(self.data["as_of"]) + timedelta(minutes=minutes))
            self.assert_blocked(self.signal())

    def test_future_candle_is_rejected(self):
        self.data["frames"]["H4"][-1]["time"] = iso(utc(self.data["as_of"]) + timedelta(hours=4))
        self.assert_blocked(self.signal())

    def test_missing_higher_timeframe(self):
        del self.data["frames"]["H4"]
        self.assert_blocked(self.signal())

    def test_partial_duplicate_and_nan_candles(self):
        for mutation in ("partial", "duplicate", "nan"):
            self.data = deepcopy(self.fixture)
            if mutation == "partial":
                self.data["frames"]["M15"][-1]["complete"] = False
            elif mutation == "duplicate":
                self.data["frames"]["M15"][-1]["time"] = self.data["frames"]["M15"][-2]["time"]
            else:
                self.data["frames"]["M15"][-1]["close"] = float("nan")
            self.assert_blocked(self.signal())

    def test_cadence_gap_anywhere_in_history_is_rejected(self):
        self.data["frames"]["M15"].pop(10)
        self.assert_blocked(self.signal())

    def test_snapshot_cutoff_rejects_context_after_as_of(self):
        self.data["frames"]["H1"][-1]["time"] = iso(utc(self.data["as_of"]) + timedelta(hours=1))
        self.assert_blocked(self.signal())

    def test_common_cutoff_rejects_account_after_snapshot(self):
        self.data["simulated"] = False
        cutoff = utc(self.data["as_of"])
        self.data["account"]["as_of"] = iso(cutoff + timedelta(seconds=30))
        self.data["broker_open_trades"] = []
        report = self.agent.analyze(self.data, "M15", "signal", clock=cutoff + timedelta(minutes=1))
        self.assert_blocked(report)

    def test_spread_and_daily_loss_veto(self):
        self.data["quote"]["ask"] += .01
        self.assert_blocked(self.signal())
        self.data = deepcopy(self.fixture)
        self.data["account"]["equity"] = 9600
        self.assert_blocked(self.signal())

    def test_pair_spec_and_conversion_must_match(self):
        self.data["instrument"]["pair"] = "GBP/USD"
        self.assert_blocked(self.signal())
        self.data = deepcopy(self.fixture)
        self.data["conversion"]["quote_currency"] = "JPY"
        self.assert_blocked(self.signal())

    def test_synthetic_data_cannot_silently_be_live(self):
        self.data["simulated"] = False
        r = self.agent.analyze(self.data, "M15", "signal", clock=utc("2026-09-25T10:00:00Z"))
        self.assert_blocked(r)

    def test_real_signal_requires_broker_tickets_even_if_counts_match(self):
        self.data["simulated"] = False
        clock = utc(self.data["as_of"])
        self.assert_blocked(self.agent.analyze(self.data, "M15", "signal", clock=clock))
        self.data["broker_open_trades"] = []
        self.assertEqual(self.agent.analyze(self.data, "M15", "signal", clock=clock)["status"], "BUY")

    def test_bearish_signal_symmetric_path(self):
        for frame in self.data["frames"].values():
            for c in frame:
                c["open"], c["close"], c["high"], c["low"] = 2.2-c["open"], 2.2-c["close"], 2.2-c["low"], 2.2-c["high"]
        q = self.data["quote"]
        q["bid"], q["ask"] = 2.2-q["ask"], 2.2-q["bid"]
        r = self.signal()
        self.assertEqual(r["status"], "SELL", r["reasons"])

    def test_risk_manager_rejects_excess_units(self):
        r = self.signal()
        proposal = {"side": "BUY", "entry": r["entry_area"][1], "stop": r["stop_loss"],
                    "target": r["take_profit"], "units": 1000000}
        result = self.agent.analyze(self.data, "M15", "risk", proposal)
        self.assertEqual(result["status"], "REJECTED")
        self.assertFalse(result["risk_evaluation"]["approved"])


if __name__ == "__main__":
    unittest.main()
