"""Fail-closed comparison of real journal positions with broker trade tickets."""

from __future__ import annotations

import math

from .models import ValidationError, number, pair_name, validate_trade_levels


def reconcile_positions(broker_trades, journal_trades: list[dict], open_count: int) -> list[str]:
    if not isinstance(broker_trades, list):
        return ["Daftar tiket broker tidak tersedia; ambil snapshot akun baru."]
    if len(broker_trades) != open_count or len(journal_trades) != open_count:
        return ["Jumlah tiket broker, akun, dan jurnal berbeda."]
    tickets = {}
    for raw in broker_trades:
        if not isinstance(raw, dict):
            raise ValidationError("Tiket broker harus object.")
        ticket = raw.get("id")
        if not isinstance(ticket, str) or not ticket or ticket in tickets:
            raise ValidationError("ID tiket broker hilang atau duplikat.")
        side = raw.get("side")
        if side not in ("BUY", "SELL"):
            raise ValidationError("Arah tiket broker tidak valid.")
        pair = pair_name(raw["pair"])
        if any(raw.get(field) is None for field in ("stop", "target", "loss_factor")):
            return [f"Tiket {ticket}: SL, TP, atau konversi belum tersedia; risiko tidak dapat diverifikasi."]
        for field in ("units", "entry", "stop", "target", "loss_factor"):
            number(raw[field], field, positive=True)
        validate_trade_levels(side, raw["entry"], raw["stop"], raw["target"])
        normalized = dict(raw)
        normalized["pair"], normalized["side"] = pair, side
        tickets[ticket] = normalized
    journal_ids = [row["broker_trade_id"] for row in journal_trades]
    if any(not value for value in journal_ids) or set(journal_ids) != set(tickets):
        return ["ID tiket broker tidak cocok dengan jurnal; tautkan dan periksa tiap transaksi."]
    reasons = []
    for row in journal_trades:
        # Journal rows are normally produced by Journal.open_trade/amend, but
        # validate again at this boundary so imported legacy rows fail closed.
        validate_trade_levels(row["side"], row["entry"], row["stop"], row["target"])
        trade = tickets[row["broker_trade_id"]]
        ticket = trade["id"]
        if trade["pair"] != row["pair"] or trade["side"] != row["side"]:
            reasons.append(f"Tiket {ticket}: pair atau arah berbeda dari jurnal.")
            continue
        if not math.isclose(float(trade["units"]), row["units"], rel_tol=1e-8, abs_tol=1e-8):
            reasons.append(f"Tiket {ticket}: units berubah; perbarui jurnal setelah fill parsial.")
        for broker_key, journal_key in (("entry", "entry"), ("stop", "stop"), ("target", "target")):
            if not math.isclose(float(trade[broker_key]), row[journal_key], rel_tol=1e-8, abs_tol=1e-8):
                reasons.append(f"Tiket {ticket}: {journal_key} broker dan jurnal berbeda.")
        adverse = (float(trade["entry"]) - float(trade["stop"]) if trade["side"] == "BUY"
                   else float(trade["stop"]) - float(trade["entry"]))
        minimum_risk = max(0, adverse) * float(trade["units"]) * float(trade["loss_factor"])
        if row["initial_risk"] + 1e-6 < minimum_risk:
            reasons.append(f"Tiket {ticket}: risiko kas jurnal lebih kecil dari jarak stop broker.")
    return reasons
