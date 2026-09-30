"""Paper order ledger. A filled order keeps its risk reservation until closed.

This ledger does not route orders to a broker. A caller must pass the loss
estimate from ``size_position`` and reconcile executions before live use.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Account, RiskPolicy, ValidationError, iso, number, pair_name, utc
from .risk import portfolio_gate


class OrderBook:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS paper_orders (
                client_id TEXT PRIMARY KEY, pair TEXT NOT NULL, side TEXT NOT NULL,
                units REAL NOT NULL, filled_units REAL NOT NULL DEFAULT 0,
                avg_price REAL, estimated_risk REAL NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_fills (
                execution_id TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                units REAL NOT NULL, price REAL NOT NULL, filled_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES paper_orders(client_id)
            );
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def get(self, client_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM paper_orders WHERE client_id=?", (client_id,)).fetchone()
        return dict(row) if row else None

    def _reserved(self) -> tuple[float, dict[str, float]]:
        total, currencies = 0.0, {}
        for row in self.db.execute("SELECT * FROM paper_orders WHERE status != 'CLOSED'"):
            active = row["filled_units"] if row["status"] == "CANCELLED" else row["units"]
            risk = row["estimated_risk"] * active / row["units"]
            total += risk
            for currency in set(row["pair"].split("/")):
                currencies[currency] = currencies.get(currency, 0.0) + risk
        return total, currencies

    def reserved(self) -> dict:
        total, currencies = self._reserved()
        return {"total": total, "currency_risk": currencies}

    def submit(self, *, client_id: str, pair: str, side: str, units: float,
               estimated_risk: float, created_at, account: Account,
               policy: RiskPolicy, journal_state: dict | None = None) -> dict:
        """Atomically claim the client ID and portfolio/currency risk budget."""
        pair = pair_name(pair)
        if side not in ("BUY", "SELL") or not client_id or not isinstance(client_id, str):
            raise ValidationError("Order memerlukan client_id dan arah BUY/SELL.")
        units = number(units, "units", positive=True)
        estimated_risk = number(estimated_risk, "estimated_risk", positive=True)
        stamp = iso(utc(created_at))
        if estimated_risk > account.equity * policy.risk_fraction + 1e-8:
            raise ValidationError("Risiko order melebihi batas per transaksi.")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.get(client_id)
            if existing:
                if (existing["pair"], existing["side"], existing["units"],
                    existing["estimated_risk"], existing["created_at"]) != (
                        pair, side, units, estimated_risk, stamp):
                    raise ValidationError("client_id sudah dipakai untuk order berbeda.")
                self.db.commit()
                return existing
            total, currencies = self._reserved()
            state = dict(journal_state or {})
            state["open_risk"] = state.get("open_risk", 0) + total
            external = dict(state.get("currency_risk", {}))
            for currency, risk in currencies.items():
                external[currency] = external.get(currency, 0) + risk
            state["currency_risk"] = external
            reasons = portfolio_gate(account, state, policy, pair, estimated_risk)
            if reasons:
                raise ValidationError(" ".join(reasons))
            self.db.execute("INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (client_id, pair, side, units, 0, None, estimated_risk,
                             "PENDING", stamp, stamp))
            self.db.commit()
            return self.get(client_id)
        except Exception:
            self.db.rollback()
            raise

    def fill(self, client_id: str, *, execution_id: str, units: float, price: float,
             filled_at) -> dict:
        units, price = number(units, "units", positive=True), number(price, "price", positive=True)
        stamp = iso(utc(filled_at))
        if not execution_id or not isinstance(execution_id, str):
            raise ValidationError("execution_id harus string nonkosong.")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.get(client_id)
            if row is None:
                raise ValidationError("Order tidak ditemukan.")
            prior = self.db.execute("SELECT * FROM paper_fills WHERE execution_id=?", (execution_id,)).fetchone()
            if prior:
                if (prior["client_id"], prior["units"], prior["price"], prior["filled_at"]) != (
                        client_id, units, price, stamp):
                    raise ValidationError("execution_id sudah dipakai untuk fill berbeda.")
                self.db.commit()
                return row
            if row["status"] not in ("PENDING", "PARTIAL"):
                raise ValidationError("Order tidak menerima fill lagi.")
            if utc(stamp) < utc(row["updated_at"]) or row["filled_units"] + units > row["units"] + 1e-8:
                raise ValidationError("Waktu atau jumlah fill tidak valid.")
            filled = min(row["units"], row["filled_units"] + units)
            average = ((row["avg_price"] or 0) * row["filled_units"] + price * units) / filled
            status = "FILLED" if filled >= row["units"] - 1e-8 else "PARTIAL"
            self.db.execute("INSERT INTO paper_fills VALUES (?,?,?,?,?)",
                            (execution_id, client_id, units, price, stamp))
            self.db.execute("UPDATE paper_orders SET filled_units=?, avg_price=?, status=?, updated_at=? WHERE client_id=?",
                            (filled, average, status, stamp, client_id))
            self.db.commit()
            return self.get(client_id)
        except Exception:
            self.db.rollback()
            raise

    def cancel(self, client_id: str, at) -> dict:
        return self._transition(client_id, at, ("PENDING", "PARTIAL"), "CANCELLED")

    def close(self, client_id: str, at) -> dict:
        return self._transition(client_id, at, ("FILLED", "CANCELLED"), "CLOSED", needs_fill=True)

    def _transition(self, client_id, at, allowed, target, needs_fill=False):
        stamp = iso(utc(at))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.get(client_id)
            if row is None or row["status"] not in allowed or (needs_fill and row["filled_units"] <= 0):
                raise ValidationError("Transisi status order tidak valid.")
            if utc(stamp) < utc(row["updated_at"]):
                raise ValidationError("Waktu event order mundur.")
            self.db.execute("UPDATE paper_orders SET status=?, updated_at=? WHERE client_id=?",
                            (target, stamp, client_id))
            self.db.commit()
            return self.get(client_id)
        except Exception:
            self.db.rollback()
            raise
