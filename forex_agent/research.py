"""Small reproducible research baseline; model scores are not calibrated odds."""

from __future__ import annotations

import math
import hashlib
import json

from .models import Candle, SECONDS, ValidationError, iso, number, pair_name, validate_cadence

FEATURES = ("return_1", "return_3", "return_5", "range_3", "close_location")
HORIZON = 1


def _features(candles: list[Candle], index: int) -> list[float]:
    current = candles[index]
    window = candles[index - 2:index + 1]
    return [current.close / candles[index - n].close - 1 for n in (1, 3, 5)] + [
        (max(c.high for c in window) - min(c.low for c in window)) / current.close,
        (current.close - current.low) / (current.high - current.low)
        if current.high > current.low else 0.5,
    ]


def feature_rows(raw_bars: list[dict]) -> list[dict]:
    candles = [Candle.parse(row) for row in raw_bars]
    if len(candles) < 100 or any(b.time <= a.time for a, b in zip(candles, candles[1:])):
        raise ValidationError("Training memerlukan >=100 candle tutup yang urut unik.")
    return [{"time": iso(candles[i].time), "label_time": iso(candles[i + HORIZON].time),
             "features": _features(candles, i),
             "label": int(candles[i + HORIZON].close > candles[i].close)}
            for i in range(5, len(candles) - HORIZON)]


def _check_timeframe(raw_bars: list[dict], timeframe: str, pair: str | None = None) -> None:
    """Reject metadata that disagrees with the actual close-to-close cadence."""
    candles = [Candle.parse(row) for row in raw_bars]
    validate_cadence(candles, timeframe, pair=pair)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1 + exp)


def _metrics(rows, predictions, threshold):
    actual = [r["label"] for r in rows]
    guesses = [int(score >= threshold) for score in predictions]
    positive = sum(actual)
    negative = len(actual) - positive
    tp = sum(y == 1 and p == 1 for y, p in zip(actual, guesses))
    tn = sum(y == 0 and p == 0 for y, p in zip(actual, guesses))
    return {"count": len(actual), "positive_rate": positive / len(actual),
            "accuracy": sum(y == p for y, p in zip(actual, guesses)) / len(actual),
            "balanced_accuracy": (tp / positive + tn / negative) / 2 if positive and negative else None,
            "brier": sum((p - y) ** 2 for y, p in zip(actual, predictions)) / len(actual)}


def train(raw_bars: list[dict], *, pair: str, timeframe: str) -> dict:
    """Fit on oldest 60%, select a threshold on validation, report held-out test."""
    pair = pair_name(pair)
    if timeframe not in SECONDS:
        raise ValidationError("Timeframe model tidak dikenal.")
    _check_timeframe(raw_bars, timeframe, pair)
    rows = feature_rows(raw_bars)
    n = len(rows)
    train_end, val_end = int(n * 0.6), int(n * 0.8)
    training = rows[:train_end]
    validation = rows[train_end + HORIZON:val_end]
    testing = rows[val_end + HORIZON:]
    if min(len(training), len(validation), len(testing)) < 10:
        raise ValidationError("Setelah purge, tiap subset membutuhkan >=10 sampel.")
    if not (training[-1]["label_time"] < validation[0]["time"] and
            validation[-1]["label_time"] < testing[0]["time"]):
        raise ValidationError("Pemisahan waktu tidak menghapus label yang tumpang tindih.")
    dimension = len(FEATURES)
    means = [sum(r["features"][j] for r in training) / len(training) for j in range(dimension)]
    scales = [max((sum((r["features"][j] - means[j]) ** 2 for r in training) /
                   len(training)) ** 0.5, 1e-12) for j in range(dimension)]

    def scaled(rows):
        return [[(r["features"][j] - means[j]) / scales[j] for j in range(dimension)]
                for r in rows]

    x_train = scaled(training)
    weights = [0.0] * dimension
    bias = 0.0
    for _ in range(400):
        gradients = [0.0] * dimension
        bias_gradient = 0.0
        for x, row in zip(x_train, training):
            error = _sigmoid(bias + sum(w * v for w, v in zip(weights, x))) - row["label"]
            bias_gradient += error
            for j, value in enumerate(x):
                gradients[j] += error * value
        size = len(training)
        weights = [w - 0.1 * (gradients[j] / size + 0.01 * w)
                   for j, w in enumerate(weights)]
        bias -= 0.1 * bias_gradient / size

    def scores(sample):
        return [_sigmoid(bias + sum(w * value for w, value in zip(weights, x)))
                for x in scaled(sample)]

    val_scores = scores(validation)
    thresholds = (0.4, 0.5, 0.6)
    threshold = max(thresholds, key=lambda value:
                    (_metrics(validation, val_scores, value)["balanced_accuracy"] or 0, -abs(value - 0.5)))
    model = {"version": 1, "pair": pair, "timeframe": timeframe,
             "dataset_sha256": hashlib.sha256(json.dumps(raw_bars, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
             "features": list(FEATURES), "horizon_bars": HORIZON,
             "mean": means, "scale": scales, "weights": weights,
             "bias": bias, "threshold": threshold,
             "validation": _metrics(validation, val_scores, threshold),
             "test": _metrics(testing, scores(testing), threshold),
             "split": {"train": {"start": training[0]["time"], "feature_end": training[-1]["time"],
                                 "label_end": training[-1]["label_time"], "count": len(training)},
                       "validation": {"start": validation[0]["time"], "feature_end": validation[-1]["time"],
                                      "label_end": validation[-1]["label_time"], "count": len(validation)},
                       "test": {"start": testing[0]["time"], "feature_end": testing[-1]["time"],
                                "label_end": testing[-1]["label_time"], "count": len(testing)}},
             "score_meaning": "Skor model riset, bukan probabilitas kemenangan terkalibrasi.",
             "validation_note": "Test dievaluasi sekali; biaya perdagangan dan kestabilan lintas rezim belum diukur."}
    return model


def predict(model: dict, raw_bars: list[dict]) -> dict:
    if (not isinstance(model, dict) or model.get("version") != 1 or
            model.get("features") != list(FEATURES)):
        raise ValidationError("Versi atau fitur model tidak cocok.")
    pair = pair_name(model.get("pair"))
    timeframe = model.get("timeframe")
    if timeframe not in SECONDS:
        raise ValidationError("Timeframe model tidak dikenal.")
    size = len(FEATURES)
    if any(not isinstance(model.get(key), list) or len(model[key]) != size
           for key in ("weights", "mean", "scale")):
        raise ValidationError("Dimensi model tidak cocok.")
    weights = [number(v, "weight") for v in model["weights"]]
    means = [number(v, "mean") for v in model["mean"]]
    scales = [number(v, "scale", positive=True) for v in model["scale"]]
    bias = number(model["bias"], "bias")
    threshold = number(model["threshold"], "threshold", minimum=0)
    if threshold > 1:
        raise ValidationError("Ambang model di luar [0,1].")
    candles = [Candle.parse(row) for row in raw_bars]
    if len(candles) < 6 or any(b.time <= a.time for a, b in zip(candles, candles[1:])):
        raise ValidationError("Prediksi memerlukan >=6 candle urut.")
    _check_timeframe(raw_bars, timeframe, pair)
    values = _features(candles, len(candles) - 1)
    score = _sigmoid(bias + sum(w * (v - mean) / scale for w, v, mean, scale in
                                zip(weights, values, means, scales)))
    return {"time": iso(candles[-1].time), "model_score": score,
            "above_validation_threshold": score >= threshold,
            "meaning": model["score_meaning"]}
