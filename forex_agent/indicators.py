"""Causal indicators with explicit warm-up and confirmed pivots."""

from __future__ import annotations

from statistics import fmean, pstdev
from .models import Candle, ValidationError


def ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValidationError("Periode EMA harus positif.")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    v = fmean(values[:period])
    out[period - 1] = v
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        v += alpha * (values[i] - v)
        out[i] = v
    return out


def wilder(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    v = fmean(values[:period])
    out[period - 1] = v
    for i in range(period, len(values)):
        v = (v * (period - 1) + values[i]) / period
        out[i] = v
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    differences = [b - a for a, b in zip(values, values[1:])]
    gains = wilder([max(0, d) for d in differences], period)
    losses = wilder([max(0, -d) for d in differences], period)
    out: list[float | None] = [None]
    for g, l in zip(gains, losses):
        if g is None or l is None:
            out.append(None)
        elif g == l == 0:
            out.append(50.0)
        elif l == 0:
            out.append(100.0)
        else:
            out.append(100 - 100 / (1 + g / l))
    return out[:len(values)]


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    ranges = [max(c.high - c.low,
                  abs(c.high - candles[i - 1].close) if i else 0,
                  abs(c.low - candles[i - 1].close) if i else 0)
              for i, c in enumerate(candles)]
    return wilder(ranges, period)


def pivots(candles: list[Candle], radius: int = 2) -> tuple[list, list]:
    highs, lows = [], []
    for i in range(radius, len(candles) - radius):
        neighbors = candles[i - radius:i] + candles[i + 1:i + radius + 1]
        if all(candles[i].high > x.high for x in neighbors):
            highs.append((i, candles[i].high))
        if all(candles[i].low < x.low for x in neighbors):
            lows.append((i, candles[i].low))
    return highs, lows


def candlestick_patterns(c: list[Candle]) -> list[str]:
    a, b = c[-2:]
    body, span = abs(b.close - b.open), b.high - b.low
    lower, upper = min(b.open, b.close) - b.low, b.high - max(b.open, b.close)
    patterns = []
    if span == 0:
        return ["doji"]
    if body <= span * 0.1:
        patterns.append("doji")
    if a.close < a.open and b.close > b.open and b.open <= a.close and b.close >= a.open:
        patterns.append("bullish_engulfing")
    if a.close > a.open and b.close < b.open and b.open >= a.close and b.close <= a.open:
        patterns.append("bearish_engulfing")
    if lower >= 2 * body and upper <= span * 0.2 and body >= span * 0.1:
        patterns.append("bullish_pin_bar")
    if upper >= 2 * body and lower <= span * 0.2 and body >= span * 0.1:
        patterns.append("bearish_pin_bar")
    if b.high < a.high and b.low > a.low:
        patterns.append("inside_bar")
    return patterns


def analyze_frame(candles: list[Candle]) -> dict:
    if len(candles) < 250:
        raise ValidationError("Minimal 250 candle tutup per timeframe untuk warm-up EMA200.")
    closes = [c.close for c in candles]
    e20, e50, e200 = [ema(closes, n) for n in (20, 50, 200)]
    e12, e26 = ema(closes, 12), ema(closes, 26)
    line = [a - b for a, b in zip(e12[25:], e26[25:])]
    signal = ema(line, 9)
    a14 = atr(candles)
    last, prev = candles[-1], candles[-2]
    volatility = a14[-1]
    mean, sd = fmean(closes[-20:]), pstdev(closes[-20:])
    trend = "RANGE"
    if last.close > e20[-1] > e50[-1] > e200[-1] and e50[-1] > e50[-6]:
        trend = "BULLISH"
    elif last.close < e20[-1] < e50[-1] < e200[-1] and e50[-1] < e50[-6]:
        trend = "BEARISH"
    hi, lo = pivots(candles[-120:])
    structure = "MIXED"
    if len(hi) >= 2 and len(lo) >= 2:
        if hi[-1][1] > hi[-2][1] and lo[-1][1] > lo[-2][1]:
            structure = "HH_HL"
        elif hi[-1][1] < hi[-2][1] and lo[-1][1] < lo[-2][1]:
            structure = "LH_LL"
    supports = sorted({p for _, p in lo if p < last.close}, reverse=True)
    resistances = sorted({p for _, p in hi if p > last.close})
    prior = candles[-21:-1]
    channel_high, channel_low = max(c.high for c in prior), min(c.low for c in prior)
    # Fibonacci only when chronologically ordered, confirmed swing anchors exist.
    fib, anchors = {}, None
    if trend == "BULLISH" and hi:
        choices = [(i, p) for i, p in lo if i < hi[-1][0] and p < hi[-1][1]]
        if choices:
            low, high = choices[-1][1], hi[-1][1]
            anchors = {"low": low, "high": high, "direction": "up"}
            fib = {str(r): high - (high - low) * r for r in (0.382, 0.5, 0.618)}
    if trend == "BEARISH" and lo:
        choices = [(i, p) for i, p in hi if i < lo[-1][0] and p > lo[-1][1]]
        if choices:
            high, low = choices[-1][1], lo[-1][1]
            anchors = {"low": low, "high": high, "direction": "down"}
            fib = {str(r): low + (high - low) * r for r in (0.382, 0.5, 0.618)}
    # Educational SMC proxies, never proof of institutional orders.
    smc = []
    past_hi = [p for i, p in hi if i < 117]
    past_lo = [p for i, p in lo if i < 117]
    if past_hi and prev.close <= past_hi[-1] < last.close:
        smc.append("bullish_bos_proxy")
    if past_lo and prev.close >= past_lo[-1] > last.close:
        smc.append("bearish_bos_proxy")
    if past_lo and last.low < past_lo[-1] < last.close:
        smc.append("sell_side_sweep_proxy")
    if past_hi and last.high > past_hi[-1] > last.close:
        smc.append("buy_side_sweep_proxy")
    if candles[-3].high < last.low:
        smc.append("bullish_fvg_proxy")
    if candles[-3].low > last.high:
        smc.append("bearish_fvg_proxy")
    return {"close": last.close, "ema20": e20[-1], "ema50": e50[-1], "ema200": e200[-1],
            "sma20": mean, "rsi14": rsi(closes)[-1], "macd": line[-1],
            "macd_signal": signal[-1], "macd_histogram": line[-1] - signal[-1],
            "bb_lower": mean - 2 * sd, "bb_middle": mean, "bb_upper": mean + 2 * sd,
            "atr14": volatility, "atr_reference": fmean(x for x in a14[-64:-14] if x is not None),
            "trend": trend, "structure": structure, "support": supports[:5],
            "resistance": resistances[:5], "channel_high": channel_high, "channel_low": channel_low,
            "fibonacci": fib, "fib_anchors": anchors, "patterns": candlestick_patterns(candles), "smc": smc}
