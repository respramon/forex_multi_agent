"""Risk calculations in account currency; quantity is broker units, not lots."""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from .models import Account, Instrument, RiskPolicy, ValidationError, number


def floor_step(value: float, step: float) -> float:
    return float((Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)
                 * Decimal(str(step)))


def size_position(*, entry: float, stop: float, target: float, side: str,
                  instrument: Instrument, account: Account, conversion: dict,
                  spread: float, slippage: float, policy: RiskPolicy,
                  requested_units: float | None = None) -> dict:
    entry, stop, target = [number(v, k, positive=True) for k, v in
                           (("entry", entry), ("stop", stop), ("target", target))]
    if side not in ("BUY", "SELL"):
        raise ValidationError("Arah harus BUY atau SELL.")
    if not (stop < entry < target if side == "BUY" else target < entry < stop):
        raise ValidationError("Urutan entry, SL, TP tidak valid untuk arah transaksi.")
    spread = number(spread, "spread", minimum=0)
    slippage = number(slippage, "slippage", minimum=0)
    if conversion["account_currency"] != account.currency:
        raise ValidationError("Konversi tidak sesuai mata uang akun.")
    loss, gain, position = [number(conversion[k], k, positive=True)
                            for k in ("loss_factor", "gain_factor", "position_factor")]
    s = instrument
    budget = account.equity * policy.risk_fraction
    distance, reward = abs(entry - stop), abs(target - entry)
    market_cost = (spread + slippage) * loss
    loss_per_unit = distance * loss + market_cost
    margin_per_unit = entry * position * s.margin_rate
    maximum = min(budget / (loss_per_unit + s.commission_per_unit_roundtrip),
                  max(0, budget - s.min_commission_roundtrip) / loss_per_unit,
                  account.free_margin * policy.max_margin_fraction / margin_per_unit,
                  s.max_units)
    # Snap only machine-noise at a grid boundary, then floor. Recheck cash and
    # margin below with a 1e-8 account-currency tolerance (far below one cent).
    grid_max = round(maximum / s.units_step, 10) * s.units_step
    suggested = floor_step(grid_max, s.units_step)
    units = suggested if requested_units is None else number(requested_units, "units", positive=True)
    errors = []
    if units < s.min_units:
        errors.append("Ukuran posisi di bawah minimum broker; jangan dibulatkan naik.")
    if units > s.max_units:
        errors.append("Ukuran posisi melebihi maksimum broker.")
    if abs(units - floor_step(units, s.units_step)) > s.units_step * 1e-7:
        errors.append("Units tidak mengikuti langkah ukuran broker.")
    commission = max(units * s.commission_per_unit_roundtrip, s.min_commission_roundtrip) if units else 0
    risk_cash = units * loss_per_unit + commission
    net_reward = units * (reward * gain - market_cost) - commission
    rr = net_reward / risk_cash if risk_cash > 0 else 0
    margin = units * margin_per_unit
    if risk_cash > budget + 1e-8:
        errors.append("Risiko melampaui anggaran per transaksi.")
    if margin > account.free_margin * policy.max_margin_fraction + 1e-8:
        errors.append("Kebutuhan margin melebihi batas yang dialokasikan.")
    if rr + 1e-8 < policy.min_rr:
        errors.append("Risk/reward bersih setelah biaya kurang dari minimum.")
    return {"approved": not errors, "reasons": errors, "units": units,
            "lots": units / s.contract_size, "suggested_units": suggested,
            "contract_size": s.contract_size, "risk_budget": budget,
            "estimated_loss": risk_cash, "estimated_net_reward": net_reward,
            "risk_fraction_actual": risk_cash / account.equity,
            "net_rr": rr, "gross_rr": reward / distance, "estimated_margin": margin,
            "estimated_roundtrip_cost": units * market_cost + commission,
            "stop_distance_pips": distance / s.pip_size, "account_currency": account.currency,
            "cost_basis": "Level midpoint; full spread + slippage allowance + roundtrip commission.",
            "limit_note": "Gap, slippage aktual, swap, dan perubahan konversi dapat melampaui estimasi."}


def portfolio_gate(account: Account, state: dict, policy: RiskPolicy, pair: str,
                   new_risk: float = 0) -> list[str]:
    reasons = []
    # Account equity catches floating losses; journal catches realized net losses.
    loss = max(account.day_start_equity - account.equity, -state.get("daily_pnl", 0), 0)
    if loss >= account.day_start_equity * policy.max_daily_loss_fraction:
        reasons.append("Batas kerugian harian tercapai.")
    if state.get("trades_today", 0) >= policy.max_trades_per_day:
        reasons.append("Batas jumlah transaksi harian tercapai.")
    if state.get("consecutive_losses", 0) >= policy.max_consecutive_losses:
        reasons.append("Batas kekalahan beruntun tercapai; perlu tinjauan jurnal.")
    if state.get("cooldown_active", False):
        reasons.append("Masa jeda transaksi belum selesai.")
    if state.get("open_risk", 0) + new_risk > account.equity * policy.max_portfolio_risk_fraction + 1e-8:
        reasons.append("Total risiko posisi terbuka melampaui batas portofolio.")
    currencies = set(pair.split("/"))
    for currency in currencies:
        if state.get("currency_risk", {}).get(currency, 0) + new_risk > account.equity * policy.max_currency_risk_fraction + 1e-8:
            reasons.append(f"Eksposur risiko {currency} melampaui batas; diversifikasi pair bukan diversifikasi USD.")
    return reasons
