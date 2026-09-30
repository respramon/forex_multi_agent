import unittest
from datetime import timedelta
from forex_agent.indicators import atr, candlestick_patterns, ema, pivots, rsi
from forex_agent.models import Candle, ValidationError, utc


def candle(i, o, h, l, c):
    return Candle(utc("2026-01-01T00:00:00Z") + timedelta(minutes=i * 5), o, h, l, c)


class IndicatorTests(unittest.TestCase):
    def test_ema_sma_seed(self):
        self.assertEqual(ema([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])

    def test_rsi_flat_rising_and_falling(self):
        self.assertEqual(rsi([10.] * 30)[-1], 50)
        self.assertEqual(rsi(list(range(1, 31)))[-1], 100)
        self.assertEqual(rsi(list(range(31, 1, -1)))[-1], 0)

    def test_atr_includes_gap_from_previous_close(self):
        candles = [candle(0, 10, 11, 9, 10), candle(1, 14, 15, 14, 15)]
        self.assertEqual(atr(candles, 2), [None, 3.5])

    def test_engulfing(self):
        self.assertIn("bullish_engulfing", candlestick_patterns([
            candle(0, 10, 11, 8, 9), candle(1, 8.9, 11.5, 8.5, 11)]))

    def test_pivot_requires_two_future_closed_bars(self):
        c = [candle(i, v, v+1, v-1, v) for i, v in enumerate([3, 4, 8, 4, 3])]
        self.assertEqual(pivots(c[:3])[0], [])
        self.assertEqual(pivots(c)[0], [(2, 9)])

    def test_invalid_candles_and_naive_times(self):
        with self.assertRaises(ValidationError):
            Candle.parse({"time": "2026-01-01T00:00:00Z", "open": 2, "high": 1, "low": 1, "close": 2})
        with self.assertRaises(ValidationError):
            utc("2026-01-01T00:00:00")


if __name__ == "__main__":
    unittest.main()
