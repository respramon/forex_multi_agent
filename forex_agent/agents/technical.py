"""Independent multi-timeframe technical observations."""

from .contracts import SpecialistAgent
from ..indicators import analyze_frame
from ..models import CONTEXT


class TechnicalAgent(SpecialistAgent):
    agent_id = "technical"
    role = "Observasi trend, momentum, struktur, pola harga, dan volatilitas lintas timeframe."
    depends_on = ("data_validation",)
    allowed_verdicts = frozenset({"OBSERVE"})

    def assess(self, context):
        technical = {tf: analyze_frame(c) for tf, c in context.frames.items()}
        frame = technical[context.timeframe]
        reasons = [f"Trend {context.timeframe}: {frame['trend']}; struktur: {frame['structure']}.",
                   "Konteks: " + ", ".join(f"{tf} {technical[tf]['trend']}"
                                           for tf in CONTEXT[context.timeframe])]
        return self.assessment("OBSERVE", reasons=reasons, payload=technical,
                               evidence={"trends": {tf: f["trend"] for tf, f in technical.items()},
                                         "rsi14": frame["rsi14"], "atr14": frame["atr14"]})
