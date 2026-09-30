"""The portfolio specialist owns account limits and broker reconciliation."""

from .contracts import SpecialistAgent
from ..models import number
from ..reconciliation import reconcile_positions
from ..risk import portfolio_gate


class PortfolioAgent(SpecialistAgent):
    agent_id = "portfolio"
    role = "Periksa drawdown harian, eksposur mata uang, jurnal, dan rekonsiliasi posisi broker."
    depends_on = ("data_validation",)
    allowed_phases = frozenset({"preflight", "sized"})
    payload_keys = ("open_positions", "open_risk", "currency_risk", "cooldown_active")

    def dependencies_for_phase(self, phase):
        return self.depends_on if phase == "preflight" else ("data_validation", "risk")

    def assess(self, context, journal, *, state=None, new_risk=0, phase="preflight"):
        state = journal.state(context.now, context.policy, context.simulated) if state is None else state
        blocks = portfolio_gate(context.account, state, context.policy, context.pair, new_risk)
        if phase == "preflight":
            open_count = number(context.snapshot["account"]["open_trade_count"], "open_trade_count", minimum=0)
            if int(open_count) != open_count or int(open_count) != state["open_positions"]:
                blocks.append("Jumlah transaksi terbuka akun berbeda dari jurnal; rekonsiliasi jurnal sebelum analisis risiko.")
            if not context.simulated:
                blocks.extend(reconcile_positions(context.snapshot.get("broker_open_trades"),
                                                   journal.open_positions(False), int(open_count)))
        dependencies = self.dependencies_for_phase(phase)
        return self.assessment("VETO" if blocks else "APPROVE", reasons=blocks,
                               payload=state, phase=phase, depends_on=dependencies,
                               evidence={"open_positions": state["open_positions"],
                                         "existing_risk": state["open_risk"], "new_risk": new_risk,
                                         "currency_risk": state["currency_risk"],
                                         "cooldown_active": state["cooldown_active"]})
