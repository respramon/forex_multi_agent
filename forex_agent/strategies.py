"""Transparent strategy selection. Correlated indicators are not independent odds."""

from .models import Candle, RiskPolicy


def candidate(frame: dict, context: list[dict], candles: list[Candle], policy: RiskPolicy) -> dict:
    trend = frame["trend"]
    if trend == "RANGE":
        return {"side": None, "setup": "NONE", "confirmations": [], "reason": "Trend tidak jelas; strategi range tidak diaktifkan."}
    direction = 1 if trend == "BULLISH" else -1
    side = "BUY" if direction == 1 else "SELL"
    last, previous = candles[-1], candles[-2]
    atr = frame["atr14"]
    if atr <= 0:
        return {"side": None, "setup": "NONE", "confirmations": [], "reason": "ATR nol."}
    aligned = all(x["trend"] == trend for x in context)
    rsi_ok = 50 <= frame["rsi14"] <= 72 if side == "BUY" else 28 <= frame["rsi14"] <= 50
    momentum = frame["macd_histogram"] * direction > 0
    body = (last.close - last.open) * direction > 0 and abs(last.close - last.open) >= (last.high - last.low) * 0.4
    patterns = frame["patterns"]
    price_action = body or any(p.startswith("bullish" if side == "BUY" else "bearish") for p in patterns)
    bb_ok = last.close >= frame["bb_middle"] if side == "BUY" else last.close <= frame["bb_middle"]
    checks = {"trend_multi_timeframe": aligned, "rsi_zone": rsi_ok, "macd_momentum": momentum,
              "price_action": price_action, "bollinger_direction": bb_ok}
    confirmations = [k for k, v in checks.items() if v]
    high, low = frame["channel_high"], frame["channel_low"]
    breakout = (previous.close <= high and last.close > high + 0.1 * atr if side == "BUY" else
                previous.close >= low and last.close < low - 0.1 * atr)
    pullback = (last.low <= frame["ema20"] + 0.15 * atr and last.close > frame["ema20"] if side == "BUY" else
                last.high >= frame["ema20"] - 0.15 * atr and last.close < frame["ema20"])
    continuation = (last.close > previous.high if side == "BUY" else last.close < previous.low)
    extension = abs(last.close - frame["ema20"]) / atr
    setup = "BREAKOUT" if breakout else "PULLBACK" if pullback and price_action else "TREND_FOLLOWING" if continuation else "NONE"
    # SMC is supporting context only; no causal claim about hidden order flow.
    reason = None
    if not aligned:
        reason = "Arah antar-timeframe tidak selaras."
    elif not rsi_ok:
        reason = "RSI belum mendukung atau harga terlalu jenuh."
    elif extension > 2.5:
        reason = "Harga terlalu jauh dari EMA20; hindari mengejar pergerakan."
    elif len(confirmations) < policy.min_confirmations:
        reason = f"Konfirmasi baru {len(confirmations)}/5; perlu {policy.min_confirmations}."
    elif setup == "NONE":
        reason = "Belum ada pemicu entry pada candle tutup."
    return {"side": None if reason else side, "setup": setup, "confirmations": confirmations,
            "checks": checks, "reason": reason, "smc_context": frame["smc"],
            "quality_score": round(len(confirmations) / 5 * 100)}
