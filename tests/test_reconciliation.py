import sqlite3
import tempfile
import unittest
from pathlib import Path

from forex_agent.journal import Journal
from forex_agent.models import ValidationError
from forex_agent.reconciliation import reconcile_positions


class ReconciliationTests(unittest.TestCase):
    def test_matching_count_cannot_hide_changed_stop_or_units(self):
        with Journal() as journal:
            journal.open_trade({"id": "journal-1", "broker_trade_id": "broker-7",
                                "pair": "EUR/USD", "side": "BUY", "opened_at": "2026-01-15T10:00:00Z",
                                "units": 10000, "entry": 1.10, "stop": 1.09, "target": 1.12,
                                "initial_risk": 110, "simulated": False})
            position = {"id": "broker-7", "pair": "EUR/USD", "side": "BUY",
                        "units": 10000, "entry": 1.10, "stop": 1.09,
                        "target": 1.12, "loss_factor": 1}
            self.assertEqual(reconcile_positions([position], journal.open_positions(False), 1), [])
            self.assertTrue(any("stop" in reason for reason in reconcile_positions(
                [{**position, "stop": 1.08}], journal.open_positions(False), 1)))
            self.assertTrue(any("units" in reason for reason in reconcile_positions(
                [{**position, "units": 11000}], journal.open_positions(False), 1)))
            self.assertTrue(any("SL" in reason for reason in reconcile_positions(
                [{**position, "stop": None}], journal.open_positions(False), 1)))
            self.assertTrue(reconcile_positions(None, journal.open_positions(False), 1))
            journal.amend_open_trade("journal-1", {"units": 10000, "entry": 1.1,
                                                    "stop": 1.08, "target": 1.12,
                                                    "initial_risk": 220})
            self.assertEqual(reconcile_positions([{**position, "stop": 1.08}],
                                                 journal.open_positions(False), 1), [])
            with self.assertRaises(ValidationError):
                journal.amend_open_trade("journal-1", {"units": 10000, "entry": 1.1,
                                                        "stop": 1.09, "target": 1.12,
                                                        "initial_risk": 100})

    def test_legacy_journal_migrates_and_can_link_a_real_ticket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "old.sqlite3")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE trades (id TEXT PRIMARY KEY, pair TEXT NOT NULL, side TEXT NOT NULL, "
                           "opened_at TEXT NOT NULL, closed_at TEXT, units REAL NOT NULL, entry REAL NOT NULL, "
                           "stop REAL NOT NULL, target REAL NOT NULL, initial_risk REAL NOT NULL, "
                           "net_pnl REAL, setup TEXT NOT NULL, notes TEXT NOT NULL, simulated INTEGER NOT NULL)")
            with Journal(path) as journal:
                journal.open_trade({"id": "old", "pair": "EUR/USD", "side": "BUY",
                                    "opened_at": "2026-01-15T10:00:00Z", "units": 10000,
                                    "entry": 1.1, "stop": 1.09, "target": 1.12,
                                    "initial_risk": 110, "simulated": False})
                journal.link_broker_trade("old", "broker-7")
                self.assertEqual(journal.open_positions(False)[0]["broker_trade_id"], "broker-7")
                with self.assertRaises(ValidationError):
                    journal.link_broker_trade("old", "broker-8")

    def test_broker_levels_must_follow_trade_direction(self):
        position = {"id": "broker-7", "pair": "EUR/USD", "side": "BUY",
                    "units": 10000, "entry": 1.10, "stop": 1.09,
                    "target": 1.12, "loss_factor": 1}
        journal = [{"broker_trade_id": "broker-7", "pair": "EUR/USD", "side": "BUY",
                    "units": 10000, "entry": 1.10, "stop": 1.09,
                    "target": 1.12, "initial_risk": 110}]
        with self.assertRaises(ValidationError):
            reconcile_positions([{**position, "stop": 1.11}], journal, 1)


if __name__ == "__main__":
    unittest.main()
