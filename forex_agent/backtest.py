"""Causal, deterministic candle replay for paper research only.

Bars use close timestamps. The engine observes a close before it can submit an
order, fills at the *next* open, and assumes the stop wins an intrabar tie.
OHLC values are midpoint prices; stop/target triggers use an inferred bid for
BUY positions and ask for SELL positions, with half the configured spread on
each side. Slippage remains an execution allowance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta, timezone
import hashlib
import json
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (Account, Candle, Instrument, RiskPolicy, SECONDS,
                     ValidationError, iso, number, pair_name, utc, validate_cadence)
from .orderbook import OrderBook
from .risk import size_position
from .replay import AgentReplay


class Strategy(Protocol):
    def on_close(self, pair: str, history: tuple[Candle, ...]) -> str | None:
        """Return BUY, SELL, or None using only candles in history."""


class SmaCross:
    def __init__(self, fast: int = 5, slow: int = 20):
        if not isinstance(fast, int) or not isinstance(slow, int) or not 1 < fast < slow:
            raise ValidationError("Periode SMA harus bilangan bulat dengan 1 < fast < slow.")
        self.fast, self.slow = fast, slow

    def on_close(self, pair: str, history: tuple[Candle, ...]) -> str | None:
        if len(history) <= self.slow:
            return None
        closes = [c.close for c in history[-self.slow - 1:]]
        prev = sum(closes[-self.fast - 1:-1]) / self.fast - sum(closes[:-1]) / self.slow
        current = sum(closes[-self.fast:]) / self.fast - sum(closes[-self.slow:]) / self.slow
        return "BUY" if prev <= 0 < current else "SELL" if prev >= 0 > current else None


@dataclass
class Pending:
    client_id: str
    pair: str
    side: str
    stop: float
    target: float
    units: float
    reserved_risk: float
    margin: float
    signal_time: object
    entry_area: tuple[float, float] | None = None


@dataclass
class Position:
    client_id: str
    pair: str
    side: str
    units: float
    entry: float
    stop: float
    target: float
    opened_at: object
    margin: float
    initial_risk: float
    financing: float = 0


class Backtest:
    def __init__(self, dataset: dict, strategy: Strategy | None = None,
                 policy: RiskPolicy | None = None, *, agent_replay: bool = False):
        if dataset.get("simulated") is not True:
            raise ValidationError("Backtest memerlukan simulated=true; data bukan quote berjalan.")
        if agent_replay and strategy is not None:
            raise ValidationError("Pilih agent_replay atau strategi kustom, bukan keduanya.")
        self.policy = policy or RiskPolicy()
        self.strategy = strategy or SmaCross()
        self.agent_replay = agent_replay
        self.source = str(dataset.get("source", "HISTORICAL USER-SUPPLIED"))
        self.dataset_sha256 = hashlib.sha256(json.dumps(dataset, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        self.timeframe = dataset["timeframe"]
        if self.timeframe not in SECONDS:
            raise ValidationError("Timeframe backtest tidak dikenal.")
        self.duration = timedelta(seconds=SECONDS[self.timeframe])
        self.initial_equity = number(dataset["initial_equity"], "initial_equity", positive=True)
        self.currency = str(dataset.get("account_currency", "USD")).upper()
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError("Mata uang akun tidak valid.")
        zone = dataset.get("timezone", "Asia/Bangkok")
        try:
            self.tz = ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            if zone == "Asia/Bangkok":
                self.tz = timezone(timedelta(hours=7))
            elif zone == "UTC":
                self.tz = timezone.utc
            else:
                raise ValidationError("Timezone backtest tidak tersedia.") from None
        settings = dataset.get("assumptions", {})
        self.max_drawdown = number(settings.get("max_drawdown_fraction", 0.1),
                                   "max_drawdown_fraction", positive=True)
        if self.max_drawdown > 1:
            raise ValidationError("max_drawdown_fraction harus <= 1.")
        raw_bars = dataset["bars"]
        if not isinstance(raw_bars, dict) or not raw_bars:
            raise ValidationError("Backtest memerlukan bars per pair.")
        if any(pair_name(p) != p for p in raw_bars):
            raise ValidationError("Nama pair backtest harus berbentuk EUR/USD.")
        self.pairs = sorted(pair_name(p) for p in raw_bars)
        if len(self.pairs) != len(raw_bars):
            raise ValidationError("Nama pair duplikat setelah normalisasi.")
        self.bars = {}
        self.raw = {}
        self.instruments = {}
        self.spreads = {}
        self.slippages = {}
        self.financing = {}
        for pair in self.pairs:
            rows = raw_bars[pair]
            if not isinstance(rows, list) or len(rows) < 30:
                raise ValidationError(f"{pair} memerlukan setidaknya 30 candle.")
            candles = [Candle.parse(row) for row in rows]
            try:
                validate_cadence(candles, self.timeframe, pair=pair)
            except ValidationError as exc:
                raise ValidationError(f"Candle {pair} hilang, duplikat, atau intervalnya tidak valid.") from exc
            spec = Instrument.parse(dataset["instruments"][pair])
            if spec.pair != pair:
                raise ValidationError("Spesifikasi instrumen salah pair.")
            self.bars[pair], self.raw[pair], self.instruments[pair] = candles, rows, spec
            self.spreads[pair] = self._series(settings["spread"][pair], len(rows), "spread", minimum=0)
            self.slippages[pair] = self._series(settings.get("slippage", {}).get(pair, 0),
                                                len(rows), "slippage", minimum=0)
            financing = settings.get("financing_per_unit", {}).get(pair, {})
            self.financing[pair] = {side: self._series(financing.get(side, 0), len(rows),
                                                     "financing_per_unit")
                                    for side in ("BUY", "SELL")}
            if pair.split("/")[1] != self.currency:
                for candle, row in zip(candles, rows):
                    if row.get("conversion_time") != iso(candle.time):
                        raise ValidationError("Konversi per candle dengan timestamp cocok wajib untuk mata uang quote berbeda.")
                    number(row["quote_to_account"], "quote_to_account", positive=True)
        self.times = [c.time for c in self.bars[self.pairs[0]]]
        if any([c.time for c in self.bars[pair]] != self.times for pair in self.pairs[1:]):
            raise ValidationError("Ada candle simbol portofolio yang hilang; backtest dihentikan tanpa forward-fill.")
        self.cash = self.initial_equity
        self.peak_equity = self.initial_equity
        self.max_seen_drawdown = 0.0
        self.halted = False
        self.orders = OrderBook()
        self.pending: dict[str, Pending] = {}
        self.positions: dict[str, Position] = {}
        self.trades: list[dict] = []
        self.events: list[dict] = []
        self.equity_curve: list[dict] = []
        self.last_action = None
        self._ran = False
        self.replay = AgentReplay(self, dataset) if agent_replay else None

    @staticmethod
    def _series(raw, length, name, *, minimum=None):
        values = raw if isinstance(raw, list) else [raw] * length
        if len(values) != length:
            raise ValidationError(f"{name} harus satu nilai atau satu nilai per candle.")
        return [number(value, name, minimum=minimum) for value in values]

    @staticmethod
    def _compact(values):
        return values[0] if all(value == values[0] for value in values) else values

    def _conversion(self, pair, index, *, at_open=False):
        # At the new bar's open, only the previous completed conversion is known.
        known_index = index - 1 if at_open else index
        return (1.0 if pair.split("/")[1] == self.currency else
                number(self.raw[pair][known_index]["quote_to_account"],
                       "quote_to_account", positive=True))

    def _emit(self, when, phase: int, pair: str, kind: str, **details):
        event = {"time": iso(when), "phase": phase, "pair": pair, "kind": kind, **details}
        key = (when, phase)
        if self.events and key < self._last_event_key:
            raise ValidationError("Event replay tidak kronologis.")
        self._last_event_key = key
        self.events.append(event)

    def _unrealized(self, pair, index, *, at_open=False):
        pos = self.positions[pair]
        mid = self.bars[pair][index].open if at_open else self.bars[pair][index].close
        half_cost = (self.spreads[pair][index] + self.slippages[pair][index]) / 2
        exit_price = mid - half_cost if pos.side == "BUY" else mid + half_cost
        change = (exit_price - pos.entry) * (1 if pos.side == "BUY" else -1) * pos.units
        commission = max(pos.units * self.instruments[pair].commission_per_unit_roundtrip,
                         self.instruments[pair].min_commission_roundtrip)
        return change * self._conversion(pair, index, at_open=at_open) - commission

    def _bid_ask(self, pair, index, midpoint):
        """Infer side-aware quotes from midpoint OHLC and the configured spread."""
        half_spread = self.spreads[pair][index] / 2
        return midpoint - half_spread, midpoint + half_spread

    def _equity(self, index, *, at_open=False):
        return self.cash + sum(self._unrealized(pair, index, at_open=at_open)
                               for pair in self.positions)

    def _account(self, index, *, at_open=False):
        equity = self._equity(index, at_open=at_open)
        margin = sum(p.margin for p in self.positions.values()) + sum(p.margin for p in self.pending.values())
        day = self.times[index].astimezone(self.tz).date()
        start = next((r["equity"] for r in reversed(self.equity_curve)
                      if utc(r["time"]).astimezone(self.tz).date() < day), self.initial_equity)
        return Account(equity=max(equity, 1e-9), free_margin=max(0, equity - margin),
                       day_start_equity=start, currency=self.currency, as_of=self.times[index])

    def _journal_state(self, index):
        today = self.times[index].astimezone(self.tz).date()
        closed = [t for t in self.trades if utc(t["closed_at"]).astimezone(self.tz).date() == today]
        streak = 0
        for trade in reversed(closed):
            if trade["net_pnl"] >= 0:
                break
            streak += 1
        return {"daily_pnl": sum(t["net_pnl"] for t in closed),
                "trades_today": sum(utc(t["opened_at"]).astimezone(self.tz).date() == today for t in self.trades)
                + sum(p.opened_at.astimezone(self.tz).date() == today for p in self.positions.values())
                + sum(p.signal_time.astimezone(self.tz).date() == today for p in self.pending.values()),
                "consecutive_losses": streak,
                "cooldown_active": self.last_action is not None and
                self.times[index] - self.last_action < timedelta(minutes=self.policy.cooldown_minutes)}

    def _exit(self, pair, index, when, midpoint, reason, phase, *, at_open=False):
        pos = self.positions.pop(pair)
        sign = 1 if pos.side == "BUY" else -1
        exit_price = midpoint - sign * (self.spreads[pair][index] + self.slippages[pair][index]) / 2
        change = (exit_price - pos.entry) * sign * pos.units
        factor = self._conversion(pair, index, at_open=at_open)
        fee = max(pos.units * self.instruments[pair].commission_per_unit_roundtrip,
                  self.instruments[pair].min_commission_roundtrip)
        pnl = change * factor - fee
        self.cash += pnl
        self.orders.close(pos.client_id, when)
        net_pnl = pnl + pos.financing
        if self.replay:
            self.replay.closed(pos, when, net_pnl)
        trade = {"order_id": pos.client_id, "pair": pair, "side": pos.side,
                 "units": pos.units, "entry": pos.entry, "exit": exit_price,
                 "opened_at": iso(pos.opened_at), "closed_at": iso(when),
                 "reason": reason, "net_pnl": net_pnl, "financing": pos.financing,
                 "initial_risk": pos.initial_risk}
        self.trades.append(trade)
        self.last_action = when
        self._emit(when, phase, pair, "exit", reason=reason, net_pnl=net_pnl)

    def _check_exit(self, pair, index, at_open=False):
        if pair not in self.positions:
            return
        pos, candle = self.positions[pair], self.bars[pair][index]
        when = candle.time - self.duration if at_open else candle.time
        if at_open:
            bid, ask = self._bid_ask(pair, index, candle.open)
            stop = bid <= pos.stop if pos.side == "BUY" else ask >= pos.stop
            target = bid >= pos.target if pos.side == "BUY" else ask <= pos.target
            if stop or target:
                self._exit(pair, index, when, candle.open if stop else pos.target,
                           "stop_gap" if stop else "target_gap", 2, at_open=True)
            return
        bid_low, ask_low = self._bid_ask(pair, index, candle.low)
        bid_high, ask_high = self._bid_ask(pair, index, candle.high)
        stop = bid_low <= pos.stop if pos.side == "BUY" else ask_high >= pos.stop
        target = bid_high >= pos.target if pos.side == "BUY" else ask_low <= pos.target
        if stop or target:
            self._exit(pair, index, when, pos.stop if stop else pos.target,
                       "stop" if stop else "target", 0)

    def _fill_pending(self, pair, index, when):
        order = self.pending.pop(pair, None)
        if order is None:
            return
        candle, instrument = self.bars[pair][index], self.instruments[pair]
        if order.entry_area is not None and not order.entry_area[0] <= candle.open <= order.entry_area[1]:
            self.orders.cancel(order.client_id, when)
            self._emit(when, 2, pair, "fill_rejected", reason="Open di luar area entry sinyal.")
            return
        conversion = self._conversion(pair, index, at_open=True)
        account = self._account(index, at_open=True)
        try:
            check = size_position(entry=candle.open, stop=order.stop, target=order.target,
                                  side=order.side, instrument=instrument, account=account,
                                  conversion={"account_currency": self.currency,
                                              "loss_factor": conversion, "gain_factor": conversion,
                                              "position_factor": conversion},
                                  spread=self.spreads[pair][index], slippage=self.slippages[pair][index],
                                  policy=self.policy, requested_units=order.units)
        except ValidationError:
            check = {"approved": False}
        if not check["approved"] or check["estimated_loss"] > order.reserved_risk + 1e-8:
            self.orders.cancel(order.client_id, when)
            self._emit(when, 2, pair, "fill_rejected", reason="Gap, biaya, risiko atau RR berubah.")
            return
        sign = 1 if order.side == "BUY" else -1
        price = candle.open + sign * (self.spreads[pair][index] + self.slippages[pair][index]) / 2
        self.orders.fill(order.client_id, execution_id=order.client_id + ":fill",
                         units=order.units, price=price, filled_at=when)
        self.positions[pair] = Position(order.client_id, pair, order.side, order.units,
                                        price, order.stop, order.target, when,
                                        check["estimated_margin"], check["estimated_loss"])
        if self.replay:
            self.replay.opened(self.positions[pair])
        self.last_action = when
        self._emit(when, 2, pair, "fill", price=price, units=order.units)

    def _signal(self, pair, index, side):
        if side not in ("BUY", "SELL"):
            raise ValidationError("Strategi harus mengembalikan BUY, SELL, atau None.")
        when = self.times[index]
        if self.halted or pair in self.positions or pair in self.pending:
            self._emit(when, 1, pair, "signal_ignored", reason="risk_halt_or_position")
            return
        history = self.bars[pair][:index + 1]
        if len(history) < 15:
            return
        true_ranges = [max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
                       for prev, c in zip(history[-15:-1], history[-14:])]
        atr = sum(true_ranges) / 14
        if atr <= 0:
            return
        sign = 1 if side == "BUY" else -1
        mid = history[-1].close
        distance = atr * self.policy.atr_stop_multiplier
        stop = mid - sign * distance
        factor = self._conversion(pair, index)
        instrument = self.instruments[pair]
        cost = (self.spreads[pair][index] + self.slippages[pair][index]) * factor + instrument.commission_per_unit_roundtrip
        reward = ((self.policy.min_rr + 0.25) * (distance * factor + cost) + cost) / factor
        target = mid + sign * reward
        account = self._account(index)
        try:
            risk = size_position(entry=mid, stop=stop, target=target, side=side,
                                 instrument=instrument, account=account,
                                 conversion={"account_currency": self.currency,
                                             "loss_factor": factor, "gain_factor": factor,
                                             "position_factor": factor},
                                 spread=self.spreads[pair][index], slippage=self.slippages[pair][index],
                                 policy=self.policy)
            if not risk["approved"]:
                raise ValidationError(" ".join(risk["reasons"]))
            client_id = f"paper:{pair}:{iso(when)}"
            self.orders.submit(client_id=client_id, pair=pair, side=side,
                               units=risk["units"], estimated_risk=risk["estimated_loss"],
                               created_at=when, account=account, policy=self.policy,
                               journal_state=self._journal_state(index))
        except ValidationError as exc:
            self._emit(when, 1, pair, "signal_rejected", reason=str(exc))
            return
        self.pending[pair] = Pending(client_id, pair, side, stop, target, risk["units"],
                                     risk["estimated_loss"], risk["estimated_margin"], when)
        self._emit(when, 1, pair, "order_submitted", units=risk["units"])

    def _agent_signal(self, pair, index, report):
        if report["status"] not in ("BUY", "SELL"):
            return
        when, risk = self.times[index], report["risk"]
        client_id = f"paper:{pair}:{iso(when)}"
        try:
            self.orders.submit(client_id=client_id, pair=pair, side=report["side"],
                               units=risk["units"], estimated_risk=risk["estimated_loss"],
                               created_at=when, account=self._account(index), policy=self.policy,
                               journal_state=self._journal_state(index))
        except ValidationError as exc:
            self._emit(when, 1, pair, "signal_rejected", reason=str(exc))
            return
        self.pending[pair] = Pending(client_id, pair, report["side"], report["stop_loss"],
                                     report["take_profit"], risk["units"], risk["estimated_loss"],
                                     risk["estimated_margin"], when, tuple(report["entry_area"]))
        self._emit(when, 1, pair, "order_submitted", units=risk["units"],
                   signal_id=report["signal_id"], setup=report["setup"])

    def run(self) -> dict:
        try:
            return self._run()
        finally:
            if self.replay:
                self.replay.close()

    def _run(self) -> dict:
        if self._ran:
            raise ValidationError("Backtest hanya dapat dijalankan satu kali.")
        self._ran = True
        self._last_event_key = (self.times[0] - self.duration, -1)
        for i, close_time in enumerate(self.times):
            open_time = close_time - self.duration
            for pair in self.pairs:
                self._check_exit(pair, i, at_open=True)
            # Resolve every open gap before validating any pending fill at the
            # same timestamp. This keeps account equity/margin independent of
            # pair iteration order when one symbol exits and another fills.
            for pair in self.pairs:
                self._fill_pending(pair, i, open_time)
            for pair in self.pairs:
                self._check_exit(pair, i)
                if pair in self.positions:
                    charge = self.positions[pair].units * self.financing[pair][self.positions[pair].side][i]
                    if charge:
                        self.cash += charge
                        self.positions[pair].financing += charge
                        self._emit(close_time, 0, pair, "financing", amount=charge)
            equity = self._equity(i)
            self.peak_equity = max(self.peak_equity, equity)
            drawdown = 1 - equity / self.peak_equity
            self.max_seen_drawdown = max(self.max_seen_drawdown, drawdown)
            if drawdown >= self.max_drawdown and not self.halted:
                self.halted = True
                self._emit(close_time, 0, "", "drawdown_halt", drawdown=drawdown)
                for pair, order in sorted(self.pending.items()):
                    self.orders.cancel(order.client_id, close_time)
                    self._emit(close_time, 0, pair, "cancelled_by_drawdown")
                self.pending.clear()
            self.equity_curve.append({"time": iso(close_time), "equity": equity})
            for pair in self.pairs:
                if self.replay:
                    if not self.halted and pair not in self.positions and pair not in self.pending:
                        report = self.replay.report(pair, i)
                        if report is not None:
                            self._agent_signal(pair, i, report)
                else:
                    signal = self.strategy.on_close(pair, tuple(self.bars[pair][:i + 1]))
                    if signal is not None:
                        self._signal(pair, i, signal)
        for pair, order in sorted(self.pending.items()):
            self.orders.cancel(order.client_id, self.times[-1])
            self._emit(self.times[-1], 3, pair, "unfilled_at_end")
        self.pending.clear()
        closed = self.trades
        wins = [trade["net_pnl"] for trade in closed if trade["net_pnl"] > 0]
        losses = [-trade["net_pnl"] for trade in closed if trade["net_pnl"] < 0]
        realized_pnl = sum(trade["net_pnl"] for trade in closed)
        unrealized_pnl = sum(self._unrealized(pair, len(self.times) - 1)
                             + self.positions[pair].financing
                             for pair in self.positions)
        metrics = {"closed_trades": len(closed),
                   "win_rate": len(wins) / len(closed) if closed else None,
                   "profit_factor": sum(wins) / sum(losses) if losses else None,
                   "expectancy_r": (sum(t["net_pnl"] / t["initial_risk"] for t in closed) / len(closed)
                                    if closed else None),
                   "realized_pnl": realized_pnl,
                   "unrealized_pnl": unrealized_pnl,
                   "total_return_fraction": self.equity_curve[-1]["equity"] / self.initial_equity - 1}
        return {"simulated": True, "timeframe": self.timeframe,
                "strategy": "forex_agent_signal" if self.replay else type(self.strategy).__name__,
                "dataset_sha256": self.dataset_sha256, "data_source": self.source,
                "risk_policy": asdict(self.policy),
                "assumptions": {"fill": "next_open", "intrabar_tie": "stop_first",
                                "spread": {p: self._compact(v) for p, v in self.spreads.items()},
                                "slippage": {p: self._compact(v) for p, v in self.slippages.items()},
                                "financing_per_unit": {p: {side: self._compact(values) for side, values in sides.items()}
                                                       for p, sides in self.financing.items()},
                                "conversion": "per bar for non-account quote, otherwise 1",
                                "ohlc": "midpoint",
                                "exit_trigger": "BUY uses inferred bid; SELL uses inferred ask",
                                "execution_price": "side quote with half spread and slippage allowance",
                                "mark_to_market": True},
                "initial_equity": self.initial_equity, "final_equity": self.equity_curve[-1]["equity"],
                "max_drawdown_fraction": self.max_seen_drawdown, "risk_halted": self.halted,
                "metrics": metrics, "trades": self.trades, "open_positions": sorted(self.positions),
                "decision_summary": ({"status": dict(self.replay.status_counts),
                                      "blocks": dict(self.replay.block_counts)} if self.replay else None),
                "equity_curve": self.equity_curve, "events": self.events}
