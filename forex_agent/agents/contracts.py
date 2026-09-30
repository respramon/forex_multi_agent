"""Messages exchanged by the forex specialists and their coordinator."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..models import Account, Candle, Instrument, RiskPolicy, ValidationError

VERDICTS = frozenset({"APPROVE", "OBSERVE", "PROPOSE", "ABSTAIN", "VETO", "ERROR"})


@dataclass(frozen=True)
class AnalysisContext:
    snapshot: dict
    pair: str
    timeframe: str
    mode: str
    now: datetime
    cutoff: datetime
    simulated: bool
    policy: RiskPolicy
    frames: dict[str, list[Candle]]
    instrument: Instrument | None = None
    account: Account | None = None
    conversion: dict | None = None
    bid: float | None = None
    ask: float | None = None
    proposed_trade: dict | None = None


@dataclass(frozen=True)
class AgentAssessment:
    agent_id: str
    verdict: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence: dict = field(default_factory=dict)
    payload: Any = None
    phase: str = "analysis"
    depends_on: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.verdict in {"VETO", "ERROR"}

    def to_dict(self) -> dict:
        # Internal payloads can contain candles, accounts, and domain objects.
        # Only the explicit evidence is included in the public decision trace.
        return {"agent": self.agent_id, "verdict": self.verdict,
                "phase": self.phase, "depends_on": list(self.depends_on),
                "reasons": list(self.reasons), "warnings": list(self.warnings),
                "evidence": deepcopy(self.evidence)}


class SpecialistAgent:
    agent_id = ""
    role = ""
    depends_on: tuple[str, ...] = ()
    allowed_verdicts = frozenset({"APPROVE", "VETO"})
    allowed_phases = frozenset({"analysis"})
    payload_type = dict
    payload_keys: tuple[str, ...] = ()

    @classmethod
    def describe(cls) -> dict:
        return {"agent": cls.agent_id, "role": cls.role,
                "depends_on": list(cls.depends_on), "method": "deterministic"}

    def assessment(self, verdict, *, reasons=(), warnings=(), evidence=None,
                   payload=None, phase="analysis", depends_on=None) -> AgentAssessment:
        return AgentAssessment(self.agent_id, verdict, tuple(reasons), tuple(warnings),
                               evidence or {}, payload, phase,
                               self.depends_on if depends_on is None else tuple(depends_on))

    def validate_assessment(self, result: AgentAssessment):
        if result.verdict not in self.allowed_verdicts or result.phase not in self.allowed_phases:
            raise ValidationError("Verdict/fase tidak sesuai tanggung jawab agen.")
        if not all(isinstance(message, str) and message for message in (*result.reasons, *result.warnings)):
            raise ValidationError("Alasan/peringatan agen harus berupa teks.")
        if result.verdict == "VETO" and not result.reasons:
            raise ValidationError("Veto agen harus mempunyai alasan.")
        if not isinstance(result.payload, self.payload_type):
            raise ValidationError("Payload laporan agen tidak valid.")
        if self.payload_keys and not all(key in result.payload for key in self.payload_keys):
            raise ValidationError("Payload laporan agen tidak lengkap.")
        if not isinstance(result.evidence, dict):
            raise ValidationError("Bukti agen harus object JSON.")
        if result.depends_on != self.dependencies_for_phase(result.phase):
            raise ValidationError("Dependensi tidak sesuai tanggung jawab agen.")

    def dependencies_for_phase(self, phase):
        return self.depends_on
