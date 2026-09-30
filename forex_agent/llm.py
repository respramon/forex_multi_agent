"""Optional narrative only. Never delegates risk, prices, or orders to a model."""

from importlib.resources import files
import json
import os
from .http_client import request_json
from .models import ValidationError


def explain(report: dict, *, api_key=None, model=None, transport=request_json) -> str:
    key, chosen = api_key or os.getenv("OPENAI_API_KEY"), model or os.getenv("OPENAI_MODEL")
    if not key or not chosen:
        raise ValidationError("OPENAI_API_KEY dan OPENAI_MODEL diperlukan untuk --explain.")
    # Whitelist avoids exposing account equity, credentials, positions, or journal.
    public = {k: report.get(k) for k in ("pair", "timeframe", "status", "market_condition", "trend",
              "setup", "reasons", "confidence", "risks", "as_of", "simulated")}
    public["agent_verdicts"] = [{k: item[k] for k in ("agent", "verdict", "phase")}
                               for item in report.get("agent_reports", [])]
    coordination = report.get("coordination", {})
    public["coordination"] = {k: coordination.get(k) for k in ("agent_count", "vetoed_by", "final_status")}
    prompt = files("forex_agent").joinpath("prompts/system.md").read_text(encoding="utf-8")
    result = transport("https://api.openai.com/v1/responses",
                       headers={"Authorization": f"Bearer {key}"},
                       payload={"model": chosen, "instructions": prompt,
                                "input": "Jelaskan hasil mesin berikut dalam maksimal 150 kata. Jangan tambahkan angka harga, lot, atau sinyal.\nDATA_JSON:\n" + json.dumps(public, ensure_ascii=False),
                                "store": False, "max_output_tokens": 800})
    if result.get("status") != "completed":
        raise ValidationError("Narasi AI tidak selesai; gunakan hasil mesin yang sudah tersedia.")
    parts = [c["text"] for item in result.get("output", []) if item.get("type") == "message"
             for c in item.get("content", []) if c.get("type") == "output_text"]
    if not parts:
        raise ValidationError("AI tidak memberikan narasi; hasil mesin tetap berlaku.")
    return "\n".join(parts)
