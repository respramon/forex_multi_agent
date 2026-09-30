"""Behavioral checks for cooperation, veto authority, failures, and publication."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from io import StringIO
import json
import unittest
from unittest.mock import patch

from forex_agent.agent import ForexAgent, ForexCoordinator
from forex_agent.agents import AgentAssessment, agent_manifest
from forex_agent.cli import main
from forex_agent.demo import make_snapshot
from forex_agent.journal import Journal
from forex_agent.llm import explain
from forex_agent.models import PAIRS, iso, utc


class MultiAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = make_snapshot()

    def setUp(self):
        self.snapshot = deepcopy(self.fixture)
        self.journal = Journal()
        self.coordinator = ForexCoordinator(self.journal)

    def tearDown(self):
        self.journal.close()

    def signal(self):
        return self.coordinator.analyze(self.snapshot, "M15", "signal")

    def signal_count(self):
        return self.journal.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

    def assert_withheld(self, report, status="NO_TRADE"):
        self.assertEqual(report["status"], status, report["reasons"])
        self.assertEqual(report["coordination"]["final_status"], status)
        for key in ("entry_area", "stop_loss", "take_profit", "risk_reward", "risk", "expires_at"):
            self.assertIsNone(report[key])
        self.assertNotIn("side", report)
        self.assertNotIn("signal_id", report)

    def test_success_has_independent_votes_and_persists_the_complete_trace(self):
        report = self.signal()
        self.assertEqual(report["status"], "BUY", report["reasons"])
        ids = {item["agent"] for item in report["agent_reports"]}
        self.assertEqual(ids, {a["agent"] for a in agent_manifest()["agents"]})
        votes = {item["agent"]: item["verdict"] for item in report["agent_reports"]}
        self.assertEqual(votes["strategy"], "PROPOSE")
        self.assertEqual(votes["risk"], "APPROVE")
        self.assertEqual(votes["currency_sentiment"], "ABSTAIN")
        self.assertEqual(report["coordination"]["not_run"], [])
        self.assertEqual(report["coordination"]["vetoed_by"], [])
        saved = json.loads(self.journal.db.execute("SELECT report FROM signals").fetchone()[0])
        self.assertEqual(saved, json.loads(json.dumps(report)))

    def test_multiple_independent_vetoes_prevent_proposal_and_publication(self):
        self.snapshot["fundamentals"]["status"] = "unknown"
        self.snapshot["quote"]["ask"] += .01
        self.snapshot["account"].update(equity=9600, free_margin=9600)
        report = self.signal()
        self.assert_withheld(report)
        self.assertEqual(set(report["coordination"]["vetoed_by"]),
                         {"fundamental", "market_conditions", "portfolio"})
        self.assertIn("strategy", report["coordination"]["not_run"])
        self.assertEqual(self.signal_count(), 0)

    def test_contrary_currency_sentiment_vetoes_an_otherwise_valid_proposal(self):
        self.snapshot["fundamentals"]["sentiment"] = [
            {"currency": currency, "score": score, "sample_count": 10,
             "as_of": self.snapshot["as_of"], "source": "synthetic test"}
            for currency, score in (("EUR", -.9), ("USD", .9))]
        report = self.signal()
        self.assert_withheld(report)
        votes = {item["agent"]: item["verdict"] for item in report["agent_reports"]}
        self.assertEqual(votes["strategy"], "PROPOSE")
        self.assertEqual(votes["currency_sentiment"], "VETO")
        self.assertIn("risk", report["coordination"]["not_run"])
        self.assertEqual(self.signal_count(), 0)

    def test_projected_currency_exposure_can_veto_after_risk_sizing_passes(self):
        self.journal.open_trade({"id": "existing-usd-exposure", "pair": "GBP/USD", "side": "BUY",
            "opened_at": iso(utc(self.snapshot["as_of"]) - timedelta(days=2)),
            "units": 10000, "entry": 1.2, "stop": 1.18, "target": 1.25,
            "initial_risk": 250, "simulated": True})
        self.snapshot["account"]["open_trade_count"] = 1
        report = self.signal()
        self.assert_withheld(report)
        portfolio = [item for item in report["agent_reports"] if item["agent"] == "portfolio"]
        self.assertEqual([(item["phase"], item["verdict"]) for item in portfolio],
                         [("preflight", "APPROVE"), ("sized", "VETO")])
        self.assertEqual(next(item["verdict"] for item in report["agent_reports"] if item["agent"] == "risk"), "APPROVE")
        self.assertTrue(any("USD" in reason for reason in report["reasons"]))
        self.assertEqual(self.signal_count(), 0)

    def test_every_specialist_failure_fails_closed(self):
        for name in ("data_agent", "technical_agent", "fundamental_agent", "market_agent",
                     "portfolio_agent", "strategy_agent", "sentiment_agent", "risk_agent"):
            with self.subTest(agent=name):
                agent = getattr(self.coordinator, name)
                with patch.object(agent, "assess", side_effect=RuntimeError("unavailable")):
                    report = self.signal()
                self.assert_withheld(report)
                self.assertIn(agent.agent_id, report["coordination"]["vetoed_by"])
                self.assertEqual(self.signal_count(), 0)

    def test_malformed_and_wrong_role_messages_are_rejected(self):
        for message in ({"approved": True}, AgentAssessment("strategy", "APPROVE"),
                        AgentAssessment("risk", "ABSTAIN")):
            with self.subTest(message=message):
                with patch.object(self.coordinator.risk_agent, "assess", return_value=message):
                    report = self.signal()
                self.assert_withheld(report)
                self.assertIn("risk", report["coordination"]["vetoed_by"])
                self.assertEqual(self.signal_count(), 0)

    def test_risk_verdict_cannot_override_a_rejected_calculation(self):
        original = self.coordinator.risk_agent.assess

        def contradictory(*args):
            assessment = original(*args)
            payload = {**assessment.payload, "approved": False}
            return replace(assessment, verdict="APPROVE", payload=payload)

        with patch.object(self.coordinator.risk_agent, "assess", side_effect=contradictory):
            report = self.signal()
        self.assert_withheld(report)
        self.assertIn("risk", report["coordination"]["vetoed_by"])
        self.assertEqual(self.signal_count(), 0)

    def test_non_finite_agent_evidence_cannot_be_published(self):
        original = self.coordinator.risk_agent.assess

        def non_finite(*args):
            return replace(original(*args), evidence={"estimated_loss": float("nan")})

        with patch.object(self.coordinator.risk_agent, "assess", side_effect=non_finite):
            report = self.signal()
        self.assert_withheld(report)
        self.assertEqual(self.signal_count(), 0)

    def test_message_cannot_erase_its_required_dependencies(self):
        original = self.coordinator.risk_agent.assess

        def missing_dependencies(*args):
            return replace(original(*args), depends_on=())

        with patch.object(self.coordinator.risk_agent, "assess", side_effect=missing_dependencies):
            report = self.signal()
        self.assert_withheld(report)
        self.assertIn("risk", report["coordination"]["vetoed_by"])
        self.assertEqual(self.signal_count(), 0)

    def test_missing_internal_payload_is_withheld_by_the_coordinator(self):
        with patch.object(self.coordinator.technical_agent, "assess",
                          return_value=AgentAssessment("technical", "OBSERVE", payload={},
                                                       depends_on=("data_validation",))):
            report = self.signal()
        self.assert_withheld(report)
        self.assertIn("coordinator", report["coordination"]["vetoed_by"])
        self.assertEqual(self.signal_count(), 0)

    def test_snapshot_cannot_disable_mandatory_agents(self):
        self.snapshot["fundamentals"] = {"status": "unknown"}
        self.snapshot["agents"] = {"fundamental": {"enabled": False}, "risk": {"enabled": False}}
        self.snapshot["coordination"] = {"decision_policy": "majority_vote", "force_buy": True}
        report = self.signal()
        self.assert_withheld(report)
        self.assertIn("fundamental", report["coordination"]["vetoed_by"])
        self.assertEqual(self.signal_count(), 0)

    def test_analyst_only_observes_without_account_and_preserves_calendar_veto(self):
        self.snapshot.pop("account")
        self.snapshot.pop("quote")
        self.snapshot["fundamentals"] = {"status": "unknown"}
        report = self.coordinator.analyze(self.snapshot, mode="analyst")
        self.assertEqual(report["status"], "ANALYSIS_ONLY")
        self.assertEqual({item["agent"] for item in report["agent_reports"]},
                         {"data_validation", "technical", "fundamental"})
        self.assertIn("fundamental", report["coordination"]["vetoed_by"])
        self.assertIsNone(report["entry_area"])
        self.assertEqual(self.signal_count(), 0)

    def test_risk_mode_reviews_user_proposal_without_claiming_a_signal(self):
        with Journal() as isolated:
            signal = ForexCoordinator(isolated).analyze(self.snapshot, mode="signal")
        proposal = {"side": "BUY", "entry": signal["entry_area"][1],
                    "stop": signal["stop_loss"], "target": signal["take_profit"]}
        report = self.coordinator.analyze(self.snapshot, mode="risk", proposed_trade=proposal)
        self.assertEqual(report["status"], "APPROVED_RISK", report["reasons"])
        self.assertIn("currency_sentiment", report["coordination"]["not_run"])
        self.assertEqual(self.signal_count(), 0)
        proposal["units"] = 1000000
        report = self.coordinator.analyze(self.snapshot, mode="risk", proposed_trade=proposal)
        self.assert_withheld(report, "REJECTED")
        self.assertIn("risk", report["coordination"]["vetoed_by"])
        self.assertFalse(report["risk_evaluation"]["approved"])

    def test_duplicate_signal_is_a_journal_veto_after_specialist_approvals(self):
        self.assertEqual(self.signal()["status"], "BUY")
        report = self.signal()
        self.assert_withheld(report)
        self.assertEqual(report["coordination"]["vetoed_by"], ["signal_journal"])
        self.assertEqual(self.signal_count(), 1)

    def test_failed_publication_clears_all_transaction_fields(self):
        with patch.object(self.journal, "claim_signal", side_effect=RuntimeError("database failure")):
            report = self.signal()
        self.assert_withheld(report)
        self.assertEqual(report["coordination"]["publication"]["status"], "ERROR")
        self.assertEqual(self.signal_count(), 0)

    def test_forex_only_scope_rejects_metals_crypto_and_equities(self):
        for symbol in ("XAU/USD", "BTC/USD", "SPY"):
            with self.subTest(symbol=symbol):
                self.snapshot["pair"] = symbol
                report = self.signal()
                self.assert_withheld(report)
                self.assertEqual(report["coordination"]["vetoed_by"], ["data_validation"])
        self.assertEqual(self.signal_count(), 0)

    def test_all_four_fx_pairs_use_broker_units_and_currency_conversions(self):
        for pair in PAIRS:
            with self.subTest(pair=pair), Journal() as journal:
                snapshot = self.fixture if pair == "EUR/USD" else make_snapshot(pair)
                report = ForexCoordinator(journal).analyze(snapshot, mode="signal")
                self.assertEqual(report["status"], "BUY", report["reasons"])
                self.assertLessEqual(report["risk"]["estimated_loss"], 100 + 1e-8)
                self.assertGreaterEqual(report["risk_reward"], 2)

    def test_requests_do_not_mutate_input_or_reuse_previous_vetoes(self):
        self.snapshot["fundamentals"]["status"] = "unknown"
        original = deepcopy(self.snapshot)
        first = self.signal()
        self.assertEqual(self.snapshot, original)
        self.snapshot = deepcopy(self.fixture)
        second = self.signal()
        self.assert_withheld(first)
        self.assertEqual(second["status"], "BUY")
        self.assertEqual(second["coordination"]["vetoed_by"], [])

    def test_optional_ai_receives_verdicts_without_private_agent_evidence(self):
        report = self.signal()
        before = deepcopy(report)
        captured = {}

        def transport(url, **kwargs):
            captured.update(kwargs["payload"])
            return {"status": "completed", "output": [{"type": "message", "content":
                    [{"type": "output_text", "text": "Penjelasan hasil mesin."}]}]}

        explain(report, api_key="fake", model="fake", transport=transport)
        public = json.loads(captured["input"].split("DATA_JSON:\n", 1)[1])
        self.assertEqual(report, before)
        self.assertEqual(len({a["agent"] for a in public["agent_verdicts"]}), 8)
        for field in ("account", "equity", "positions", "currency_risk", "evidence", "risk_budget"):
            self.assertNotIn(f'"{field}"', captured["input"])

    def test_cli_manifest_exposes_the_forex_team_without_api_keys(self):
        stream = StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["agents", "--json"]), 0)
        manifest = json.loads(stream.getvalue())
        self.assertEqual(manifest["agent_count"], 8)
        self.assertTrue(manifest["forex_only"])
        self.assertEqual(manifest["pairs"], list(PAIRS))
        self.assertFalse(manifest["execution_enabled"])
        self.assertIsInstance(ForexAgent(self.journal), ForexCoordinator)


if __name__ == "__main__":
    unittest.main()
