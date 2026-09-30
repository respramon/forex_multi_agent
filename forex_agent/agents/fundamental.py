"""Calendar and directional currency sentiment are separate specialist votes."""

from .contracts import SpecialistAgent
from .. import fundamentals
from ..models import ValidationError, validate_common_cutoff


class FundamentalAgent(SpecialistAgent):
    agent_id = "fundamental"
    role = "Validasi kalender kedua mata uang dan veto periode berita berdampak tinggi."
    depends_on = ("data_validation",)
    payload_keys = ("blocks", "warnings", "events", "pair_sentiment", "source")

    def validate_assessment(self, result):
        super().validate_assessment(result)
        if (result.verdict == "APPROVE") != (not bool(result.payload["blocks"])):
            raise ValidationError("Verdict fundamental bertentangan dengan veto kalender.")

    def assess(self, context):
        raw = context.snapshot.get("fundamentals", {})
        if not isinstance(raw, dict):
            raise ValidationError("Fundamental harus object JSON.")
        timestamps = []
        if raw.get("as_of") is not None:
            timestamps.append(raw["as_of"])
        timestamps.extend(item["as_of"] for item in raw.get("sentiment", [])
                          if isinstance(item, dict) and item.get("as_of") is not None)
        validate_common_cutoff(context.cutoff, timestamps, label="Fundamental")
        macro = fundamentals.evaluate(raw, context.pair, context.now, context.policy)
        return self.assessment("VETO" if macro["blocks"] else "APPROVE",
                               reasons=macro["blocks"], warnings=macro["warnings"], payload=macro,
                               evidence={"source": macro["source"],
                                         "relevant_events": macro["events"],
                                         "calendar_verified": not bool(macro["blocks"])})


class CurrencySentimentAgent(SpecialistAgent):
    agent_id = "currency_sentiment"
    role = "Bandingkan sentimen mata uang dasar dan kuotasi dengan arah kandidat transaksi."
    depends_on = ("fundamental", "strategy")
    allowed_verdicts = frozenset({"APPROVE", "ABSTAIN", "VETO"})
    payload_type = type(None)

    def assess(self, context, macro, proposal):
        score = macro["pair_sentiment"]
        evidence = {"pair_sentiment": score, "candidate_side": proposal["side"]}
        if score is None:
            return self.assessment("ABSTAIN", evidence=evidence,
                                   reasons=["Sentimen tidak lengkap; agen sentimen tidak memberi konfirmasi arah."])
        contrary = score < -0.4 if proposal["side"] == "BUY" else score > 0.4
        return self.assessment("VETO" if contrary else "APPROVE", evidence=evidence,
                               reasons=["Sentimen pasangan berlawanan kuat dengan kandidat teknikal."] if contrary else [])
