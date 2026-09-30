"""The data agent owns validation and the common, closed-candle snapshot."""

from copy import deepcopy

from .contracts import AnalysisContext, SpecialistAgent
from ..models import (Account, Candle, CONTEXT, Instrument, SECONDS, ValidationError,
                      iso, now_utc, number, pair_name, utc, validate_cadence,
                      validate_common_cutoff)


def fresh(raw_time, now, max_seconds, name):
    stamp = utc(raw_time)
    if stamp > now or (now - stamp).total_seconds() > max_seconds:
        raise ValidationError(f"{name} kedaluwarsa atau berasal dari masa depan.")
    return stamp


class DataValidationAgent(SpecialistAgent):
    agent_id = "data_validation"
    role = "Validasi pasangan forex, candle tutup, timestamp, quote, dan spesifikasi akun."
    allowed_verdicts = frozenset({"APPROVE"})
    payload_type = AnalysisContext

    def assess(self, snapshot, timeframe, mode, policy, proposed_trade=None, clock=None):
        if not isinstance(snapshot, dict):
            raise ValidationError("Snapshot harus object JSON.")
        if mode not in ("analyst", "signal", "risk"):
            raise ValidationError("Mode harus analyst/signal/risk; journal memakai perintah tersendiri.")
        if timeframe not in SECONDS:
            raise ValidationError("Timeframe harus M5, M15, H1, H4, atau Daily.")
        snapshot = deepcopy(snapshot)
        pair = pair_name(snapshot["pair"])
        simulated = snapshot.get("simulated", False)
        if not isinstance(simulated, bool):
            raise ValidationError("simulated harus boolean.")
        now = utc(clock) if clock else utc(snapshot["as_of"]) if simulated else now_utc()
        cutoff = fresh(snapshot["as_of"], now, policy.max_quote_age_seconds, "Snapshot")
        # Require an explicit source even when the data is synthetic.
        source = str(snapshot["source"])
        frames = {}
        for tf in (timeframe, *CONTEXT[timeframe]):
            raw = snapshot["frames"].get(tf)
            if not isinstance(raw, list) or not 250 <= len(raw) <= 5000:
                raise ValidationError(f"Timeframe {tf} memerlukan 250–5000 candle tutup.")
            candles = [Candle.parse(c) for c in raw]
            validate_cadence(candles, tf, pair=pair)
            validate_common_cutoff(cutoff, (c.time for c in candles), label=f"Candle {tf}")
            fresh(candles[-1].time, now, SECONDS[tf] * 1.25 + 60, f"Candle {tf}")
            frames[tf] = candles

        instrument = account = conversion = bid = ask = None
        if mode != "analyst":
            instrument = Instrument.parse(snapshot["instrument"])
            if instrument.pair != pair:
                raise ValidationError("Spesifikasi instrumen tidak cocok dengan pair.")
            account = Account.parse(snapshot["account"])
            fresh(account.as_of, now, policy.max_quote_age_seconds, "Akun")
            validate_common_cutoff(cutoff, (account.as_of,), label="Akun")
            conversion = dict(snapshot["conversion"])
            fresh(conversion["time"], now, policy.max_quote_age_seconds, "Konversi")
            validate_common_cutoff(cutoff, (conversion["time"],), label="Konversi")
            if conversion["account_currency"] != account.currency:
                raise ValidationError("Mata uang konversi tidak cocok dengan akun.")
            if conversion.get("quote_currency") != pair.split("/")[1]:
                raise ValidationError("Mata uang quote konversi tidak cocok dengan instrumen.")
            for key in ("loss_factor", "gain_factor", "position_factor"):
                conversion[key] = number(conversion[key], key, positive=True)
                if account.currency == conversion["quote_currency"] and abs(conversion[key] - 1) > 1e-9:
                    raise ValidationError("Konversi ke mata uang yang sama harus 1.")
            quote = snapshot["quote"]
            fresh(quote["time"], now, policy.max_quote_age_seconds, "Quote")
            validate_common_cutoff(cutoff, (quote["time"],), label="Quote")
            bid = number(quote["bid"], "bid", positive=True)
            ask = number(quote["ask"], "ask", positive=True)
            if ask < bid:
                raise ValidationError("Ask lebih rendah dari bid.")
        context = AnalysisContext(snapshot, pair, timeframe, mode, now, cutoff, simulated,
                                  policy, frames, instrument, account, conversion, bid, ask,
                                  deepcopy(proposed_trade))
        return self.assessment("APPROVE", payload=context,
                               evidence={"pair": pair, "as_of": iso(now), "source": source,
                                         "simulated": simulated,
                                         "closed_candles": {tf: len(c) for tf, c in frames.items()}})
