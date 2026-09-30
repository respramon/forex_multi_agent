"""The risk specialist independently sizes and validates a proposed trade."""

from .contracts import SpecialistAgent
from ..models import ValidationError
from ..risk import size_position


class RiskAgent(SpecialistAgent):
    agent_id = "risk"
    role = "Hitung units/lot, risiko kas, margin, dan risk/reward bersih setelah biaya."
    depends_on = ("data_validation", "technical", "market_conditions", "strategy")
    payload_keys = ("approved", "reasons", "estimated_loss", "net_rr", "units", "lots")

    def validate_assessment(self, result):
        super().validate_assessment(result)
        if not isinstance(result.payload["approved"], bool):
            raise ValidationError("Persetujuan risiko harus boolean.")
        if (result.verdict == "APPROVE") != result.payload["approved"]:
            raise ValidationError("Verdict risiko bertentangan dengan hasil perhitungan.")
        if result.payload["approved"] == bool(result.payload["reasons"]):
            raise ValidationError("Persetujuan risiko bertentangan dengan alasan penolakan.")

    def assess(self, context, technical, market, proposal):
        risk = size_position(entry=proposal["entry"], stop=proposal["stop"],
                             target=proposal["target"], side=proposal["side"],
                             instrument=context.instrument, account=context.account,
                             conversion=context.conversion, spread=market["spread"],
                             slippage=technical[context.timeframe]["atr14"] * context.policy.slippage_atr_fraction,
                             policy=context.policy, requested_units=proposal["requested_units"])
        return self.assessment("APPROVE" if risk["approved"] else "VETO",
                               reasons=risk["reasons"], payload=risk,
                               evidence={k: risk[k] for k in ("units", "lots", "risk_budget", "estimated_loss",
                                                              "estimated_margin", "net_rr", "account_currency")})
