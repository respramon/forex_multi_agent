"""SQLite journal and atomic signal throttling. One DB per trading account."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone as fixed_timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .models import (RiskPolicy, ValidationError, iso, number, pair_name,
                     utc, validate_trade_levels)


class Journal:
    def __init__(self, path: str = ":memory:", timezone: str = "Asia/Bangkok"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            # Windows may lack the IANA database. Bangkok has a fixed UTC+7
            # offset for all supported modern trading timestamps.
            if timezone == "Asia/Bangkok":
                self.tz = fixed_timezone(timedelta(hours=7), "Asia/Bangkok")
            elif timezone == "UTC":
                self.tz = fixed_timezone.utc
            else:
                raise ValidationError("Timezone tidak tersedia; instal data IANA atau gunakan Asia/Bangkok/UTC.") from None
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY, pair TEXT NOT NULL, side TEXT NOT NULL,
            opened_at TEXT NOT NULL, closed_at TEXT, units REAL NOT NULL,
            entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL,
            initial_risk REAL NOT NULL, net_pnl REAL, setup TEXT NOT NULL,
            notes TEXT NOT NULL, simulated INTEGER NOT NULL,
            broker_trade_id TEXT
        );
        CREATE TABLE IF NOT EXISTS signals (
            fingerprint TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            simulated INTEGER NOT NULL, report TEXT NOT NULL
        );
        """)
        if "broker_trade_id" not in {row["name"] for row in self.db.execute("PRAGMA table_info(trades)")}:
            self.db.execute("ALTER TABLE trades ADD COLUMN broker_trade_id TEXT")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS trades_broker_id_unique "
                        "ON trades(broker_trade_id) WHERE broker_trade_id IS NOT NULL AND simulated=0")

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def open_trade(self, raw: dict) -> str:
        pair, side = pair_name(raw["pair"]), raw["side"]
        entry, stop, target = validate_trade_levels(side, raw["entry"], raw["stop"], raw["target"])
        simulated = raw.get("simulated", False)
        if not isinstance(simulated, bool):
            raise ValidationError("simulated harus boolean.")
        trade_id = str(raw.get("id") or uuid.uuid4())
        broker_id = raw.get("broker_trade_id")
        if broker_id is not None and (simulated or not isinstance(broker_id, str) or not broker_id.strip()):
            raise ValidationError("broker_trade_id hanya untuk transaksi nyata dan harus string nonkosong.")
        try:
            with self.db:
                self.db.execute("INSERT INTO trades "
                                "(id,pair,side,opened_at,closed_at,units,entry,stop,target,initial_risk,"
                                "net_pnl,setup,notes,simulated,broker_trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    trade_id, pair, side, iso(utc(raw["opened_at"])), None,
                    number(raw["units"], "units", positive=True), entry, stop, target,
                    number(raw["initial_risk"], "initial_risk", positive=True), None,
                    str(raw.get("setup", "manual")), str(raw.get("notes", "")), int(simulated), broker_id))
        except sqlite3.IntegrityError as exc:
            raise ValidationError("ID transaksi atau broker_trade_id sudah ada.") from exc
        return trade_id

    def link_broker_trade(self, trade_id: str, broker_trade_id: str) -> None:
        """Attach a broker ID to a legacy real journal record after manual verification."""
        if not isinstance(broker_trade_id, str) or not broker_trade_id.strip():
            raise ValidationError("broker_trade_id harus string nonkosong.")
        try:
            with self.db:
                row = self.db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
                if row is None or row["simulated"] or row["closed_at"] is not None:
                    raise ValidationError("Hanya transaksi nyata yang terbuka dapat ditautkan.")
                if row["broker_trade_id"] not in (None, broker_trade_id):
                    raise ValidationError("Transaksi sudah ditautkan ke ID broker berbeda.")
                self.db.execute("UPDATE trades SET broker_trade_id=? WHERE id=?", (broker_trade_id, trade_id))
        except sqlite3.IntegrityError as exc:
            raise ValidationError("ID broker sudah dipakai transaksi lain.") from exc

    def open_positions(self, simulated: bool) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM trades WHERE simulated=? AND closed_at IS NULL", (int(simulated),))]

    def amend_open_trade(self, trade_id: str, raw: dict) -> None:
        """Record changed broker levels/units without releasing the original risk reserve."""
        values = {key: number(raw[key], key, positive=True)
                  for key in ("units", "entry", "stop", "target", "initial_risk")}
        with self.db:
            row = self.db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if row is None or row["simulated"] or row["closed_at"] is not None:
                raise ValidationError("Hanya transaksi nyata yang terbuka dapat diperbarui.")
            validate_trade_levels(row["side"], values["entry"], values["stop"], values["target"])
            minimum = row["initial_risk"] * max(1, values["units"] / row["units"])
            if values["initial_risk"] + 1e-8 < minimum:
                raise ValidationError("initial_risk tidak boleh turun atau lebih kecil setelah units bertambah.")
            self.db.execute("UPDATE trades SET units=?, entry=?, stop=?, target=?, initial_risk=? WHERE id=?",
                            (values["units"], values["entry"], values["stop"], values["target"],
                             values["initial_risk"], trade_id))

    def close_trade(self, trade_id: str, net_pnl: float, closed_at: datetime) -> None:
        net_pnl = number(net_pnl, "net_pnl")
        with self.db:
            row = self.db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if row is None or row["closed_at"] is not None:
                raise ValidationError("Transaksi tidak ditemukan atau sudah ditutup.")
            if utc(closed_at) < utc(row["opened_at"]):
                raise ValidationError("Waktu tutup lebih awal dari waktu buka.")
            self.db.execute("UPDATE trades SET net_pnl=?, closed_at=? WHERE id=?",
                            (net_pnl, iso(closed_at), trade_id))

    def state(self, now: datetime, policy: RiskPolicy, simulated: bool) -> dict:
        rows = self.db.execute("SELECT * FROM trades WHERE simulated=? ORDER BY opened_at", (int(simulated),)).fetchall()
        today = utc(now).astimezone(self.tz).date()
        known = [r for r in rows if utc(r["opened_at"]) <= now]
        open_rows = [r for r in known if r["closed_at"] is None or utc(r["closed_at"]) > now]
        closed = sorted([r for r in known if r["closed_at"] and utc(r["closed_at"]) <= now], key=lambda r:r["closed_at"])
        daily = [r for r in closed if utc(r["closed_at"]).astimezone(self.tz).date() == today]
        streak = 0
        for r in reversed(daily):
            if r["net_pnl"] >= 0:
                break
            streak += 1
        currency_risk: dict[str, float] = {}
        for r in open_rows:
            for c in r["pair"].split("/"):
                currency_risk[c] = currency_risk.get(c, 0) + r["initial_risk"]
        recent_actions = [utc(r["opened_at"]) for r in known] + [utc(r["closed_at"]) for r in closed]
        last = max(recent_actions, default=None)
        return {"trades_today": sum(utc(r["opened_at"]).astimezone(self.tz).date() == today for r in known),
                "daily_pnl": sum(r["net_pnl"] for r in daily), "consecutive_losses": streak,
                "open_risk": sum(r["initial_risk"] for r in open_rows), "currency_risk": currency_risk,
                "cooldown_active": last is not None and now - last < timedelta(minutes=policy.cooldown_minutes),
                "open_positions": len(open_rows), "timezone": str(self.tz)}

    def claim_signal(self, fingerprint: str, now: datetime, simulated: bool,
                     policy: RiskPolicy, report: dict) -> str | None:
        """Serializes read/check/write so concurrent requests cannot bypass quotas."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            rows = self.db.execute("SELECT * FROM signals WHERE simulated=?", (int(simulated),)).fetchall()
            today = now.astimezone(self.tz).date()
            known = [r for r in rows if utc(r["created_at"]) <= now]
            reason = None
            if any(r["fingerprint"] == fingerprint for r in rows):
                reason = "Setup pada candle yang sama sudah diterbitkan."
            elif sum(utc(r["created_at"]).astimezone(self.tz).date() == today for r in known) >= policy.max_trades_per_day:
                reason = "Batas penerbitan sinyal harian tercapai."
            elif any(now - utc(r["created_at"]) < timedelta(minutes=policy.cooldown_minutes) for r in known):
                reason = "Masa jeda antar-sinyal belum selesai."
            if reason is None:
                self.db.execute("INSERT INTO signals VALUES (?,?,?,?)", (
                    fingerprint, iso(now), int(simulated), json.dumps(report, allow_nan=False)))
            self.db.commit()
            return reason
        except Exception:
            self.db.rollback()
            raise

    def summary(self, simulated: bool = False) -> dict:
        rows = self.db.execute("SELECT * FROM trades WHERE simulated=? ORDER BY closed_at", (int(simulated),)).fetchall()
        closed = [r for r in rows if r["closed_at"] is not None]
        wins = [r for r in closed if r["net_pnl"] > 0]
        losses = [r for r in closed if r["net_pnl"] < 0]
        profit, loss = sum(r["net_pnl"] for r in wins), -sum(r["net_pnl"] for r in losses)
        curve = peak = drawdown = 0.0
        for r in closed:
            curve += r["net_pnl"]
            peak = max(peak, curve)
            drawdown = max(drawdown, peak - curve)
        by_setup = {}
        for r in closed:
            item = by_setup.setdefault(r["setup"], {"trades": 0, "net_pnl": 0.0, "sum_r": 0.0})
            item["trades"] += 1
            item["net_pnl"] += r["net_pnl"]
            item["sum_r"] += r["net_pnl"] / r["initial_risk"]
        return {"mode": "journal", "simulated": simulated, "closed_trades": len(closed),
                "open_trades": len(rows) - len(closed), "net_pnl": profit - loss,
                "win_rate": len(wins) / len(closed) if closed else None,
                "profit_factor": profit / loss if loss else None,
                "profit_factor_note": "null jika belum ada kerugian tertutup; bukan bukti profit pasti.",
                "expectancy_r": sum(r["net_pnl"] / r["initial_risk"] for r in closed) / len(closed) if closed else None,
                "max_closed_pnl_drawdown": drawdown, "by_setup": by_setup,
                "review": "Bandingkan expectancy R per setup, biaya, disiplin SL, dan sampel. Drawdown ini hanya P/L tertutup."}
