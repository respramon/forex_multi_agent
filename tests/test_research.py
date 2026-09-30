import copy
import math
import unittest
from datetime import datetime, timedelta, timezone

from forex_agent.models import ValidationError, iso
from forex_agent.research import feature_rows, predict, train


def bars(count=140):
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    values = [1.1 + 0.001 * math.sin(i / 4) + i * 0.000001 for i in range(count + 1)]
    return [dict(time=iso(start + timedelta(minutes=5 * i)), open=values[i],
                 high=max(values[i], values[i + 1]) + 0.0001,
                 low=min(values[i], values[i + 1]) - 0.0001,
                 close=values[i + 1], volume=1, complete=True)
            for i in range(count)]


class ResearchTests(unittest.TestCase):
    def test_future_data_cannot_affect_fitted_weights_or_scaler(self):
        original = bars()
        changed = copy.deepcopy(original)
        for item in changed[-10:]:
            item["open"] += 0.01
            item["close"] += 0.01
            item["high"] += 0.01
            item["low"] += 0.01
        first = train(original, pair="EUR/USD", timeframe="M5")
        second = train(changed, pair="EUR/USD", timeframe="M5")
        self.assertEqual(first["weights"], second["weights"])
        self.assertEqual(first["mean"], second["mean"])
        self.assertLess(first["split"]["train"]["label_end"],
                        first["split"]["validation"]["start"])
        self.assertLess(first["split"]["validation"]["label_end"],
                        first["split"]["test"]["start"])
        score = predict(first, original)
        self.assertTrue(0 <= score["model_score"] <= 1)
        self.assertEqual(score["time"], original[-1]["time"])
        malformed = copy.deepcopy(first)
        malformed["scale"][0] = 0
        with self.assertRaises(ValidationError):
            predict(malformed, original)

    def test_incomplete_or_unsorted_bars_fail_closed(self):
        data = bars()
        data[4]["complete"] = False
        with self.assertRaises(ValidationError):
            feature_rows(data)
        data = bars()
        data[30]["time"] = data[29]["time"]
        with self.assertRaises(ValidationError):
            train(data, pair="EUR/USD", timeframe="M5")

    def test_timeframe_metadata_must_match_candle_cadence(self):
        data = bars()
        with self.assertRaisesRegex(ValidationError, "timeframe"):
            train(data, pair="EUR/USD", timeframe="H1")
        model = train(data, pair="EUR/USD", timeframe="M5")
        hourly = data[::12]
        with self.assertRaisesRegex(ValidationError, "timeframe"):
            predict(model, hourly)


if __name__ == "__main__":
    unittest.main()
