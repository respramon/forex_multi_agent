"""The strategy agent proposes a setup; it cannot authorize its own risk."""

import math

from .contracts import SpecialistAgent
from ..models import CONTEXT, ValidationError, validate_trade_levels
from ..strategies import candidate


def round_price(price, tick, upward):
    value = price / tick
    return round((math.ceil(value - 1e-10) if upward else math.floor(value + 1e-10)) * tick, 10)


class StrategyAgent(SpecialistAgent):
    agent_id = "strategy"
    role = "Usulkan setup trend following, breakout, atau pullback dengan entry, SL, dan TP."
    depends_on = ("data_validation", "technical", "market_conditions")
    allowed_verdicts = frozenset({"PROPOSE", "ABSTAIN"})
    payload_keys = ("proposal",)

    def validate_assessment(self, result):
        super().validate_assessment(result)
        if result.verdict == "PROPOSE":
            proposal = result.payload["proposal"]
            validate_trade_levels(proposal["side"], proposal["entry"], proposal["stop"], proposal["target"])
            if proposal["entry_area"][0] > proposal["entry"] or proposal["entry"] > proposal["entry_area"][1]:
                raise ValidationError("Entry kandidat berada di luar area entry.")

    def assess(self, context, technical, market):
        frame = technical[context.timeframe]
        volatility, spec, policy = frame["atr14"], context.instrument, context.policy
        if context.mode == "risk":
            raw = context.proposed_trade
            if not isinstance(raw, dict):
                raise ValidationError("Risk Manager memerlukan proposed_trade berupa object JSON.")
            side = raw["side"]
            entry, stop, target = validate_trade_levels(side, raw["entry"], raw["stop"], raw["target"])
            if abs(entry - (context.bid + context.ask) / 2) > volatility:
                raise ValidationError("Entry usulan lebih dari 1 ATR dari quote; refresh ketika mendekati entry.")
            if abs(entry - stop) < volatility * policy.atr_stop_multiplier:
                raise ValidationError("Stop usulan terlalu sempit relatif terhadap ATR.")
            proposal = {"side": side, "entry": entry, "stop": stop, "target": target,
                        "entry_area": [entry, entry], "setup": "USER_PROPOSAL",
                        "requested_units": raw.get("units")}
            return self.assessment("PROPOSE", payload={"proposal": proposal},
                                   evidence={"setup": "USER_PROPOSAL", "side": side,
                                             "direction_confirmed": False})

        checks = candidate(frame, [technical[t] for t in CONTEXT[context.timeframe]],
                           context.frames[context.timeframe], policy)
        payload = {"checks": checks, "proposal": None}
        evidence = {"setup": checks["setup"], "side": checks["side"],
                    "confirmations": checks["confirmations"], "quality_score": checks.get("quality_score", 0)}
        if not checks["side"]:
            return self.assessment("ABSTAIN", reasons=[checks["reason"]],
                                   evidence=evidence, payload=payload)
        side, setup = checks["side"], checks["setup"]
        entry_area = [round_price(frame["close"] - 0.1 * volatility, spec.tick_size, False),
                      round_price(frame["close"] + 0.1 * volatility, spec.tick_size, True)]
        entry = entry_area[1] if side == "BUY" else entry_area[0]
        recent = context.frames[context.timeframe][-5:]
        stop = (min(entry - policy.atr_stop_multiplier * volatility, min(c.low for c in recent) - 0.2 * volatility)
                if side == "BUY" else
                max(entry + policy.atr_stop_multiplier * volatility, max(c.high for c in recent) + 0.2 * volatility))
        stop = round_price(stop, spec.tick_size, side == "SELL")
        conversion = context.conversion
        cost = ((market["spread"] + volatility * policy.slippage_atr_fraction) * conversion["loss_factor"]
                + spec.commission_per_unit_roundtrip)
        distance = (policy.min_rr * (abs(entry - stop) * conversion["loss_factor"] + cost) + cost) / conversion["gain_factor"]
        target = round_price(entry + (distance if side == "BUY" else -distance), spec.tick_size, side == "BUY")
        obstacles = [level for observation in technical.values()
                     for level in observation["resistance" if side == "BUY" else "support"]]
        if any((entry < p <= target + 0.1 * volatility) if side == "BUY" else
               (target - 0.1 * volatility <= p < entry) for p in obstacles):
            return self.assessment("ABSTAIN", payload=payload, evidence=evidence,
                                   reasons=["Support/resistance terkonfirmasi menghalangi target minimum 1:2."])
        payload["proposal"] = {"side": side, "setup": setup, "entry_area": entry_area,
                               "entry": entry, "stop": stop, "target": target, "requested_units": None}
        return self.assessment("PROPOSE", payload=payload, evidence=evidence,
                               reasons=[f"Konfirmasi {len(checks['confirmations'])}/5: " +
                                        ", ".join(checks["confirmations"]) +
                                        f"; RSI14 {frame['rsi14']:.1f}, MACD histogram {frame['macd_histogram']:.6g}."])
