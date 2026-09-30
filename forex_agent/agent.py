"""Forex multi-agent coordinator. Mandatory vetoes override every proposal."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from .agents import (AGENT_TYPES, AgentAssessment, CurrencySentimentAgent,
                     DataValidationAgent, FundamentalAgent, MarketConditionsAgent,
                     PortfolioAgent, RiskAgent, StrategyAgent, TechnicalAgent, agent_manifest)
from .agents.contracts import VERDICTS
from .journal import Journal
from .models import RiskPolicy, SECONDS, ValidationError, iso


def empty_report(pair, timeframe, mode) -> dict:
    return {"pair": pair, "timeframe": timeframe, "mode": mode, "status": "NO_TRADE",
            "market_condition": "UNKNOWN", "trend": "UNKNOWN", "setup": "NONE",
            "entry_area": None, "stop_loss": None, "take_profit": None, "risk_reward": None,
            "reasons": [], "confidence": {"score": None, "label": "Belum dinilai",
                "meaning": "Skor kesesuaian aturan, bukan probabilitas menang."},
            "risks": ["Trading berleverage dapat merugi; stop loss tidak menjamin batas rugi saat gap."],
            "risk": None, "agent_reports": [],
            "coordination": {"architecture": "forex_multi_agent", "coordinator": "ForexCoordinator",
                             "decision_policy": "mandatory_veto", "agent_count": len(AGENT_TYPES),
                             "vetoed_by": [], "not_run": [], "final_status": "NO_TRADE",
                             "publication": {"status": "NOT_REQUESTED"}}}


class ForexCoordinator:
    def __init__(self, journal: Journal, policy: RiskPolicy | None = None):
        self.journal = journal
        self.policy = policy or RiskPolicy()
        self.data_agent = DataValidationAgent()
        self.technical_agent = TechnicalAgent()
        self.fundamental_agent = FundamentalAgent()
        self.market_agent = MarketConditionsAgent()
        self.portfolio_agent = PortfolioAgent()
        self.strategy_agent = StrategyAgent()
        self.sentiment_agent = CurrencySentimentAgent()
        self.risk_agent = RiskAgent()

    @staticmethod
    def manifest() -> dict:
        return agent_manifest()

    def _run(self, report, agent, *args, **kwargs) -> AgentAssessment:
        """A failed or malformed specialist message can never authorize a trade."""
        try:
            result = agent.assess(*args, **kwargs)
            if not isinstance(result, AgentAssessment) or result.agent_id != agent.agent_id:
                raise ValidationError("Kontrak laporan agen tidak valid.")
            if result.verdict not in VERDICTS:
                raise ValidationError("Verdict agen tidak valid.")
            agent.validate_assessment(result)
            if "phase" in kwargs and result.phase != kwargs["phase"]:
                raise ValidationError("Fase laporan agen tidak sesuai pemeriksaan yang diminta.")
            assessed = {item["agent"] for item in report["agent_reports"]}
            if not set(result.depends_on).issubset(assessed):
                raise ValidationError("Dependensi laporan agen belum tersedia.")
            summary = result.to_dict()
            json.dumps(summary, allow_nan=False)
        except (ValidationError, KeyError, TypeError, ValueError, IndexError, OverflowError, AttributeError) as exc:
            result = agent.assessment("ERROR", reasons=[f"Input/data tidak valid: {exc}"],
                                      phase=kwargs.get("phase", "analysis"))
            summary = result.to_dict()
        except Exception as exc:
            result = agent.assessment("ERROR", reasons=[f"Agen {agent.agent_id} gagal; analisis dihentikan."],
                                      evidence={"error_type": type(exc).__name__},
                                      phase=kwargs.get("phase", "analysis"))
            summary = result.to_dict()
        report["agent_reports"].append(summary)
        for key, messages in (("reasons", result.reasons), ("risks", result.warnings)):
            for message in messages:
                if message not in report[key]:
                    report[key].append(message)
        return result

    @staticmethod
    def _clear_levels(report):
        for key in ("entry_area", "stop_loss", "take_profit", "risk_reward", "risk", "expires_at"):
            report[key] = None
        report["setup"] = "NONE"
        report.pop("side", None)
        report.pop("signal_id", None)

    def _finish(self, report):
        trace = report["agent_reports"]
        coordination = report["coordination"]
        coordination["final_status"] = report["status"]
        coordination["vetoed_by"] = list(dict.fromkeys(item["agent"] for item in trace
                                                       if item["verdict"] in {"VETO", "ERROR"}))
        if coordination["publication"]["status"] in {"VETO", "ERROR"}:
            coordination["vetoed_by"].append("signal_journal")
        if "coordinator_error" in coordination:
            coordination["vetoed_by"].append("coordinator")
        assessed = {item["agent"] for item in trace}
        coordination["not_run"] = [a.agent_id for a in AGENT_TYPES if a.agent_id not in assessed]
        if report["status"] in {"NO_TRADE", "REJECTED"}:
            self._clear_levels(report)
        return report

    def _reject(self, report):
        report["status"] = "REJECTED" if report["mode"] == "risk" else "NO_TRADE"
        return self._finish(report)

    def analyze(self, snapshot: dict, timeframe: str = "M15", mode: str = "analyst",
                proposed_trade: dict | None = None, *, clock=None) -> dict:
        """The same coordinator serves CLI, API, and time-injected historical replay."""
        pair = snapshot.get("pair", "UNKNOWN") if isinstance(snapshot, dict) else "UNKNOWN"
        report = empty_report(pair, timeframe, mode)
        try:
            return self._analyze(snapshot, timeframe, mode, proposed_trade, clock, report)
        except Exception as exc:
            report["coordination"]["coordinator_error"] = {"error_type": type(exc).__name__}
            report["reasons"].append("Koordinator menerima hasil yang tidak dapat digunakan; keputusan diblokir.")
            return self._reject(report)

    def _analyze(self, snapshot, timeframe, mode, proposed_trade, clock, report):
        data = self._run(report, self.data_agent, snapshot, timeframe, mode,
                         self.policy, proposed_trade, clock)
        if data.verdict != "APPROVE":
            return self._reject(report)
        context = data.payload
        report.update(pair=context.pair, as_of=iso(context.now), simulated=context.simulated,
                      data_source=str(context.snapshot["source"]))
        if context.simulated:
            report["risks"].append("SIMULASI SINTETIS/HISTORIS — bukan harga atau sinyal pasar saat ini.")
        technical = self._run(report, self.technical_agent, context)
        if technical.verdict != "OBSERVE":
            return self._reject(report)
        observations = technical.payload
        frame = observations[timeframe]
        report.update(technical=observations, trend=frame["trend"],
                      market_condition="TRENDING" if frame["trend"] != "RANGE" else "RANGING")
        fundamental = self._run(report, self.fundamental_agent, context)
        if fundamental.verdict not in {"APPROVE", "VETO"}:
            return self._reject(report)
        report["fundamentals"] = fundamental.payload
        if mode == "analyst":
            report["status"] = "ANALYSIS_ONLY"
            report["reasons"].append("Analyst Mode menyajikan observasi tanpa level transaksi.")
            return self._finish(report)

        # Both independent gates report their objections before any proposal is made.
        market = self._run(report, self.market_agent, context, observations)
        portfolio = self._run(report, self.portfolio_agent, context, self.journal)
        if market.verdict in {"APPROVE", "VETO"}:
            report["spread"] = market.payload["spread"]
        if portfolio.verdict in {"APPROVE", "VETO"}:
            report["portfolio_state"] = portfolio.payload
        if any(result.verdict != "APPROVE" for result in (fundamental, market, portfolio)):
            return self._reject(report)
        strategy = self._run(report, self.strategy_agent, context, observations, market.payload)
        if strategy.verdict == "ERROR":
            return self._reject(report)
        if mode == "signal":
            checks = strategy.payload["checks"]
            report["checks"] = checks
            report["confidence"] = {"score": checks.get("quality_score", 0),
                                    "label": "Skor kesesuaian aturan",
                                    "meaning": "Bukan probabilitas menang; indikator dapat berkorelasi."}
        if strategy.verdict != "PROPOSE":
            return self._reject(report)
        proposal = strategy.payload["proposal"]
        if mode == "signal":
            sentiment = self._run(report, self.sentiment_agent, context, fundamental.payload, proposal)
            if sentiment.verdict not in {"APPROVE", "ABSTAIN"}:
                return self._reject(report)
        risk = self._run(report, self.risk_agent, context, observations, market.payload, proposal)
        if risk.verdict not in {"APPROVE", "VETO"}:
            return self._reject(report)
        projected = self._run(report, self.portfolio_agent, context, self.journal,
                              state=portfolio.payload, new_risk=risk.payload["estimated_loss"], phase="sized")
        if risk.verdict != "APPROVE" or projected.verdict != "APPROVE":
            if mode == "risk":
                report["risk_evaluation"] = risk.payload
            return self._reject(report)
        sizing = risk.payload
        report.update(status="APPROVED_RISK" if mode == "risk" else proposal["side"],
                      setup=proposal["setup"], side=proposal["side"], entry_area=proposal["entry_area"],
                      stop_loss=proposal["stop"], take_profit=proposal["target"], risk_reward=sizing["net_rr"],
                      risk=sizing, expires_at=iso(min(context.now + timedelta(seconds=SECONDS[timeframe]),
                          context.frames[timeframe][-1].time + timedelta(seconds=SECONDS[timeframe]))))
        report["reasons"].append(f"{proposal['setup']}: RR bersih {sizing['net_rr']:.2f}; sizing pada sisi area entry terburuk.")
        if mode == "risk":
            report["reasons"].append("APPROVED_RISK hanya kelayakan risiko; tidak mengonfirmasi strategi atau arah trading.")
            return self._finish(report)
        return self._publish(report, context, proposal["side"])

    def _publish(self, report, context, side):
        fingerprint = hashlib.sha256(
            f"{context.simulated}|{context.pair}|{context.timeframe}|{iso(context.frames[context.timeframe][-1].time)}|{side}".encode()).hexdigest()
        report["signal_id"] = fingerprint
        report["risks"].append("Setup kedaluwarsa pada candle berikutnya; hitung ulang risiko sebelum entry manual.")
        report["coordination"]["publication"] = {"status": "RECORDED"}
        self._finish(report)
        try:
            reason = self.journal.claim_signal(fingerprint, context.now, context.simulated, self.policy, report)
        except Exception:
            report["coordination"]["publication"] = {"status": "ERROR"}
            report["reasons"].append("Pencatatan sinyal gagal; keputusan diblokir.")
            return self._reject(report)
        if reason:
            report["coordination"]["publication"] = {"status": "VETO", "reason": reason}
            report["reasons"].append(reason)
            return self._reject(report)
        return report


class ForexAgent(ForexCoordinator):
    """Backward-compatible entrypoint; all analysis now uses the specialist team."""


def format_report(report: dict) -> str:
    value = lambda x: "N/A" if x is None else x
    lines = [f"PAIR: {report['pair']}", f"TIMEFRAME: {report['timeframe']}",
             f"MARKET CONDITION: {report['market_condition']}", f"TREND: {report['trend']}",
             f"SETUP: {report['setup']} | {report['status']}", f"ENTRY AREA: {value(report['entry_area'])}",
             f"STOP LOSS: {value(report['stop_loss'])}", f"TAKE PROFIT: {value(report['take_profit'])}",
             f"RISK/REWARD: {'1:' + format(report['risk_reward'], '.2f') if report['risk_reward'] is not None else 'N/A'}",
             "ALASAN ANALISIS: " + " | ".join(report["reasons"]),
             f"TINGKAT KEPERCAYAAN: {value(report['confidence']['score'])} — {report['confidence']['meaning']}",
             "RISIKO YANG PERLU DIPERHATIKAN: " + " | ".join(report["risks"])]
    if report.get("risk"):
        r = report["risk"]
        lines.append(f"LOT SIZE: {r['lots']:.6f} ({r['units']:g} units); estimasi rugi {r['estimated_loss']:.2f} {r['account_currency']}")
    if report.get("agent_reports"):
        lines.append("LAPORAN AGEN:")
        for item in report["agent_reports"]:
            reasons = "; ".join(item["reasons"]) or "Pemeriksaan selesai."
            lines.append(f"  {item['agent']} [{item['phase']}]: {item['verdict']} — {reasons}")
        vetoes = report["coordination"]["vetoed_by"]
        lines.append("KOORDINATOR: " + report["status"] + ("; veto: " + ", ".join(vetoes) if vetoes else ""))
    lines.append(f"DATA: {report.get('data_source', 'unknown')} | {report.get('as_of', 'N/A')}")
    return "\n".join(lines)
