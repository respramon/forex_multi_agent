from datetime import timedelta
import tempfile
import unittest
from forex_agent.journal import Journal
from forex_agent.models import RiskPolicy, ValidationError, iso, utc


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.journal = Journal()
        self.now = utc("2026-01-15T16:30:00Z")

    def tearDown(self):
        self.journal.close()

    def trade(self, identifier, when, pair="EUR/USD"):
        return self.journal.open_trade({"id": identifier, "pair": pair, "side": "BUY", "opened_at": iso(when),
                  "units": 10000, "entry": 1.1, "stop": 1.09, "target": 1.12, "initial_risk": 100,
                  "setup": "PULLBACK", "simulated": True})

    def test_realized_metrics_use_net_pnl_and_initial_risk(self):
        for i, pnl in enumerate((200, -100, 50)):
            when = self.now - timedelta(hours=4-i)
            self.trade(str(i), when)
            self.journal.close_trade(str(i), pnl, when + timedelta(minutes=20))
        result = self.journal.summary(True)
        self.assertEqual(result["net_pnl"], 150)
        self.assertAlmostEqual(result["win_rate"], 2/3)
        self.assertEqual(result["profit_factor"], 2.5)
        self.assertEqual(result["expectancy_r"], .5)
        self.assertEqual(result["max_closed_pnl_drawdown"], 100)
        self.assertEqual(self.journal.summary(False)["closed_trades"], 0)

    def test_local_midnight_and_cooldown(self):
        self.trade("1", self.now)
        state = self.journal.state(self.now + timedelta(minutes=10), RiskPolicy(), True)
        self.assertTrue(state["cooldown_active"])
        self.assertEqual(state["trades_today"], 1)
        # 17:00 UTC is midnight in Asia/Bangkok.
        later = self.journal.state(self.now + timedelta(hours=1), RiskPolicy(), True)
        self.assertEqual(later["trades_today"], 0)
        self.assertEqual(later["open_risk"], 100)
        self.assertEqual(later["currency_risk"]["USD"], 100)

    def test_duplicate_close_and_invalid_time_rejected(self):
        self.trade("1", self.now)
        with self.assertRaises(ValidationError):
            self.journal.close_trade("1", 10, self.now - timedelta(seconds=1))
        self.journal.close_trade("1", 10, self.now)
        with self.assertRaises(ValidationError):
            self.journal.close_trade("1", 20, self.now)

    def test_amend_rejects_stop_on_wrong_side_of_entry(self):
        self.journal.open_trade({"id": "1", "pair": "EUR/USD", "side": "BUY",
                                 "opened_at": iso(self.now), "units": 10000,
                                 "entry": 1.1, "stop": 1.09, "target": 1.12,
                                 "initial_risk": 100, "simulated": False})
        with self.assertRaises(ValidationError):
            self.journal.amend_open_trade("1", {"units": 10000, "entry": 1.1,
                                                 "stop": 1.11, "target": 1.12,
                                                 "initial_risk": 100})

    def test_account_rejects_free_margin_above_equity(self):
        from forex_agent.models import Account
        with self.assertRaises(ValidationError):
            Account.parse({"equity": 1000, "free_margin": 1000.01,
                           "day_start_equity": 1000, "currency": "USD",
                           "as_of": iso(self.now)})
        with self.assertRaises(ValidationError):
            Account(1000, 1000.01, 1000, "USD", self.now)

    def test_signal_quota_and_cooldown_persist_across_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            path = folder + "/journal.sqlite3"
            policy = RiskPolicy(max_trades_per_day=2)
            with Journal(path) as first:
                self.assertIsNone(first.claim_signal("one", self.now, True, policy, {}))
            with Journal(path) as second:
                self.assertIn("sama", second.claim_signal("one", self.now, True, policy, {}))
                self.assertIn("jeda", second.claim_signal("two", self.now, True, policy, {}))


if __name__ == "__main__":
    unittest.main()
