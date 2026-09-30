"""Calendar vetoes and contextual currency sentiment; no invented macro forecasts."""

from datetime import timedelta
from .models import RiskPolicy, ValidationError, iso, number, utc


def evaluate(raw: dict, pair: str, now, policy: RiskPolicy) -> dict:
    blocks, warnings = [], []
    currencies = set(pair.split("/"))
    if raw.get("status") != "ok":
        return {"blocks": ["Kalender ekonomi belum tersedia/terverifikasi."], "warnings": [],
                "events": [], "pair_sentiment": None, "source": raw.get("source", "unknown")}
    fetched = utc(raw["as_of"])
    if fetched > now or now - fetched > timedelta(minutes=policy.calendar_max_age_minutes):
        blocks.append("Kalender ekonomi kedaluwarsa atau bertanggal masa depan.")
    start, end = utc(raw["coverage_from"]), utc(raw["coverage_to"])
    if start > now - timedelta(minutes=policy.news_after_minutes) or end < now + timedelta(minutes=policy.news_before_minutes):
        blocks.append("Cakupan kalender tidak mencakup seluruh jendela pembatasan berita.")
    if not currencies.issubset(set(raw["currencies"])):
        blocks.append("Cakupan mata uang kalender tidak lengkap.")
    relevant = []
    for event in raw.get("events", []):
        when = utc(event["time"])
        if event["impact"] not in ("low", "medium", "high"):
            raise ValidationError("Dampak berita harus low/medium/high.")
        if not event.get("source"):
            raise ValidationError("Event ekonomi harus mencantumkan sumber.")
        if event["currency"] not in currencies:
            continue
        if abs((when - now).total_seconds()) <= 24 * 3600:
            relevant.append({k: event.get(k) for k in
                             ("time", "currency", "impact", "title", "source", "actual", "forecast", "previous")})
        if event["impact"] == "high" and when - timedelta(minutes=policy.news_before_minutes) <= now <= when + timedelta(minutes=policy.news_after_minutes):
            blocks.append(f"Berita high-impact {event['currency']}: {event['title']} ({iso(when)}).")
    scores = {}
    for item in raw.get("sentiment", []):
        score = number(item["score"], "sentiment score")
        count = number(item["sample_count"], "sample_count", minimum=0)
        published = utc(item["as_of"])
        if not -1 <= score <= 1 or int(count) != count:
            raise ValidationError("Sentimen harus -1..1 dengan sample_count bulat.")
        if published > now or now - published > timedelta(hours=24) or count < 3:
            warnings.append(f"Sentimen {item['currency']} tidak cukup segar/representatif.")
        elif item.get("source"):
            scores[item["currency"]] = score
    base, quote = pair.split("/")
    pair_score = (scores[base] - scores[quote]) / 2 if base in scores and quote in scores else None
    if pair_score is None:
        warnings.append("Sentimen pasangan tidak lengkap; tidak diasumsikan netral atau dijadikan konfirmasi.")
    return {"blocks": blocks, "warnings": warnings, "events": relevant,
            "currency_sentiment": scores, "pair_sentiment": pair_score,
            "source": raw.get("source", "user-supplied"),
            "interpretation": "Sentimen hanya konteks; actual vs forecast tidak otomatis menentukan arah harga."}
