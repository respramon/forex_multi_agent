"""Validated boundary types. All candle timestamps denote CLOSE time, UTC."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD")
SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "Daily": 86400}
CONTEXT = {"M5": ("M15", "H1"), "M15": ("H1", "H4"),
           "H1": ("H4", "Daily"), "H4": ("Daily",), "Daily": ("H4",)}

try:
    _NEW_YORK = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    # Without the IANA database, fail closed for broker session gaps. The
    # normal exact cadence and weekend rules remain available everywhere.
    _NEW_YORK = None


class ValidationError(ValueError):
    pass


def utc(value: str | datetime) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Timestamp harus ISO 8601 dengan zona waktu.") from exc
    if dt.tzinfo is None:
        raise ValidationError("Timestamp tanpa zona waktu ditolak.")
    return dt.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def number(value: Any, name: str, *, minimum: float | None = None,
           positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{name} harus angka, bukan boolean.")
    try:
        n = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError(f"{name} harus angka.") from exc
    if not math.isfinite(n) or (positive and n <= 0) or (minimum is not None and n < minimum):
        raise ValidationError(f"{name} berada di luar batas valid.")
    return n


def pair_name(value: str) -> str:
    value = str(value).upper().replace("_", "/")
    if value not in PAIRS:
        raise ValidationError(f"Proyek ini khusus forex; pair harus salah satu: {', '.join(PAIRS)}")
    return value


def validate_trade_levels(side: str, entry: Any, stop: Any, target: Any) -> tuple[float, float, float]:
    """Validate the directional relationship between entry, SL, and TP.

    This is intentionally shared by every boundary that accepts broker levels.
    Keeping the invariant in one place prevents a journal amend from accepting
    a level that reconciliation would later reject (or vice versa).
    """
    if side not in ("BUY", "SELL"):
        raise ValidationError("Arah transaksi harus BUY/SELL.")
    values = tuple(number(value, name, positive=True)
                  for name, value in (("entry", entry), ("stop", stop), ("target", target)))
    entry_value, stop_value, target_value = values
    valid = (stop_value < entry_value < target_value if side == "BUY"
             else target_value < entry_value < stop_value)
    if not valid:
        raise ValidationError("Urutan entry, SL, TP tidak valid untuk arah transaksi.")
    return values


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

    @classmethod
    def parse(cls, raw: dict) -> "Candle":
        if raw.get("complete", True) is not True:
            raise ValidationError("Candle belum tutup tidak boleh dianalisis.")
        o, h, l, c = [number(raw[k], k, positive=True) for k in ("open", "high", "low", "close")]
        if l > min(o, c) or h < max(o, c) or h < l:
            raise ValidationError("OHLC tidak konsisten.")
        return cls(utc(raw["time"]), o, h, l, c, number(raw.get("volume", 0), "volume", minimum=0))


def weekend_gap(previous: datetime, current: datetime, timeframe: str) -> bool:
    """Return whether a cadence gap is exactly attributable to the FX weekend.

    Candle timestamps are close times in UTC. Depending on the provider, the
    last Friday close can therefore fall on Saturday UTC, and the first Sunday
    session close can fall on Sunday or Monday UTC. We only permit a gap that
    starts on Friday/Saturday, ends on Sunday/Monday/Tuesday, and is no more
    than one normal interval plus the three calendar weekend days.
    """
    if timeframe not in SECONDS:
        raise ValidationError("Timeframe tidak dikenal.")
    previous, current = utc(previous), utc(current)
    interval = timedelta(seconds=SECONDS[timeframe])
    gap = current - previous
    if gap <= interval or gap > interval + timedelta(days=3):
        return False
    if previous.weekday() not in (4, 5) or current.weekday() not in (0, 1, 6):
        return False
    return 0 < (current.date() - previous.date()).days <= 3


def session_gap(previous: datetime, current: datetime, timeframe: str, pair: str | None = None) -> bool:
    """Allow a known daily maintenance break near 17:00 New York.

    The FX feed can pause for a few minutes at the New York rollover. With
    M5/M15 close timestamps this appears as a missing aligned candle. The
    local-time windows keep the exception narrow and reject arbitrary gaps.
    """
    if pair is not None:
        pair_name(pair)
    if _NEW_YORK is None or timeframe not in ("M5", "M15"):
        return False
    previous, current = utc(previous), utc(current)
    interval = timedelta(seconds=SECONDS[timeframe])
    gap = current - previous
    reopen_delay = timedelta(minutes=5)
    if gap <= interval:
        return False
    previous_local = previous.astimezone(_NEW_YORK)
    current_local = current.astimezone(_NEW_YORK)
    if previous_local.date() != current_local.date():
        return False
    rollover = previous_local.replace(hour=17, minute=0, second=0, microsecond=0)
    reopen = rollover + reopen_delay
    if timeframe == "M5":
        next_close = reopen + interval
    else:
        # M15/H1 candles are aligned to the hour in the OANDA feed, so the
        # first post-reopen candle starts at the aligned boundary.
        aligned_start = reopen.replace(minute=(reopen.minute // int(interval.total_seconds() // 60)) *
                                        int(interval.total_seconds() // 60), second=0, microsecond=0)
        next_close = aligned_start + interval
    return previous_local == rollover and current_local == next_close


def validate_cadence(candles: Iterable[Candle | dict], timeframe: str, *, pair: str | None = None) -> None:
    """Require complete close-to-close cadence for an entire candle series."""
    if timeframe not in SECONDS:
        raise ValidationError("Timeframe tidak dikenal.")
    interval = timedelta(seconds=SECONDS[timeframe])
    values = [candle if isinstance(candle, Candle) else Candle.parse(candle)
              for candle in candles]
    for previous, current in zip(values, values[1:]):
        gap = current.time - previous.time
        if gap <= timedelta(0):
            raise ValidationError(f"Timestamp {timeframe} tidak urut atau duplikat.")
        if (gap != interval and
                not weekend_gap(previous.time, current.time, timeframe) and
                not session_gap(previous.time, current.time, timeframe, pair)):
            raise ValidationError(f"Interval candle tidak sesuai timeframe {timeframe} atau ada data hilang.")


# Descriptive alias for callers that prefer the full name.
validate_candle_cadence = validate_cadence


def validate_common_cutoff(cutoff: str | datetime, timestamps: Iterable[str | datetime], *,
                           label: str = "Data") -> datetime:
    """Ensure every timestamp belongs to one snapshot cutoff.

    Older components are safe (and occur naturally when higher timeframes close
    less often), while any component after the snapshot cutoff is look-ahead
    data and is rejected.
    """
    boundary = utc(cutoff)
    for value in timestamps:
        stamp = utc(value)
        if stamp > boundary:
            raise ValidationError(f"{label} bertanggal setelah cutoff snapshot.")
    return boundary


@dataclass(frozen=True)
class Instrument:
    pair: str
    pip_size: float
    tick_size: float
    contract_size: float
    units_step: float
    min_units: float
    max_units: float
    margin_rate: float
    commission_per_unit_roundtrip: float = 0
    min_commission_roundtrip: float = 0
    spec_source: str = "user-supplied"

    def __post_init__(self):
        object.__setattr__(self, "pair", pair_name(self.pair))

    @classmethod
    def parse(cls, raw: dict) -> "Instrument":
        names = ("pip_size", "tick_size", "contract_size", "units_step", "min_units", "max_units", "margin_rate")
        values = {k: number(raw[k], k, positive=True) for k in names}
        if values["min_units"] > values["max_units"] or values["margin_rate"] > 1:
            raise ValidationError("Spesifikasi instrumen tidak konsisten.")
        for key in ("commission_per_unit_roundtrip", "min_commission_roundtrip"):
            values[key] = number(raw.get(key, 0), key, minimum=0)
        return cls(pair_name(raw["pair"]), **values, spec_source=str(raw.get("spec_source", "user-supplied")))


@dataclass(frozen=True)
class Account:
    equity: float
    free_margin: float
    day_start_equity: float
    currency: str
    as_of: datetime

    def __post_init__(self):
        equity = number(self.equity, "equity", positive=True)
        free_margin = number(self.free_margin, "free_margin", minimum=0)
        day_start = number(self.day_start_equity, "day_start_equity", positive=True)
        currency = str(self.currency).upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("Mata uang akun harus kode tiga huruf.")
        if free_margin > equity + 1e-8:
            raise ValidationError("Free margin tidak boleh melebihi equity akun.")
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "free_margin", free_margin)
        object.__setattr__(self, "day_start_equity", day_start)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "as_of", utc(self.as_of))

    @classmethod
    def parse(cls, raw: dict) -> "Account":
        return cls(raw["equity"], raw["free_margin"], raw["day_start_equity"],
                   raw["currency"], raw["as_of"])


@dataclass(frozen=True)
class RiskPolicy:
    risk_fraction: float = 0.01
    min_rr: float = 2.0
    atr_stop_multiplier: float = 1.5
    max_daily_loss_fraction: float = 0.03
    max_portfolio_risk_fraction: float = 0.04
    max_currency_risk_fraction: float = 0.03
    max_trades_per_day: int = 3
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 60
    max_spread_atr_fraction: float = 0.15
    max_quote_age_seconds: int = 120
    calendar_max_age_minutes: int = 15
    news_before_minutes: int = 30
    news_after_minutes: int = 30
    slippage_atr_fraction: float = 0.05
    max_margin_fraction: float = 0.5
    min_confirmations: int = 4

    def __post_init__(self):
        for f in fields(self):
            n = number(getattr(self, f.name), f.name, positive=True)
            if f.type == "int" and n != int(n):
                raise ValidationError(f"{f.name} harus bilangan bulat.")
            object.__setattr__(self, f.name, int(n) if f.type == "int" else n)
        if not 0 < self.risk_fraction <= 0.02:
            raise ValidationError("Risiko per transaksi harus > 0 dan <= 2%.")
        if self.min_rr < 2 or not 3 <= self.min_confirmations <= 5:
            raise ValidationError("RR minimal 2 dan konfirmasi minimal 3–5.")
        if any(getattr(self, k) > 1 for k in ("max_daily_loss_fraction", "max_portfolio_risk_fraction",
                "max_currency_risk_fraction", "max_spread_atr_fraction", "max_margin_fraction", "slippage_atr_fraction")):
            raise ValidationError("Fraksi harus <= 1.")

    @classmethod
    def parse(cls, raw: dict | None = None) -> "RiskPolicy":
        raw = raw or {}
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValidationError(f"Konfigurasi tidak dikenal: {sorted(unknown)}")
        return cls(**raw)
