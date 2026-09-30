"""Dependency-free local HTTP API.

The server is intentionally local/internal. Put it behind a maintained TLS
proxy before exposing it to a network. Journal-open requests can carry an
``Idempotency-Key`` (or a JSON ``client_id``) so a retried HTTP request cannot
create a second record.
"""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
import threading
import time
from urllib.parse import parse_qs, urlsplit
from .agent import ForexCoordinator
from .agents import agent_manifest
from .journal import Journal
from .models import RiskPolicy, ValidationError, utc

LOGGER = logging.getLogger("forex_agent.api")
MAX_BODY = 4 * 1024 * 1024
MAX_RATE_KEYS = 2048


def handler_factory(db_path: str, token: str, policy: RiskPolicy):
    traffic = defaultdict(deque)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ForexMultiAgent/0.2"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, fmt, *args):
            # Keep the standard request line free of payloads and credentials.
            LOGGER.info("http_request method=%s path=%s", self.command, urlsplit(self.path).path)

        def send(self, code, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def error(self, code, message, *, error_code=None):
            value = {"error": message}
            if error_code:
                value["code"] = error_code
            self.send(code, value)

        @staticmethod
        def _idempotency_id(key: str) -> str:
            return "api-idempotency-" + hashlib.sha256(key.encode("utf-8")).hexdigest()

        @staticmethod
        def _open_fingerprint(raw: dict) -> str:
            fields = ("pair", "side", "opened_at", "units", "entry", "stop", "target",
                      "initial_risk", "setup", "notes", "simulated", "broker_trade_id")
            values = {field: raw.get(field) for field in fields}
            values["setup"] = raw.get("setup", "manual")
            values["notes"] = raw.get("notes", "")
            # Preserve the raw type here. A malformed retry such as the string
            # "false" must not compare equal to a previously recorded boolean.
            values["simulated"] = raw.get("simulated", False)
            if values["opened_at"] is not None:
                values["opened_at"] = utc(values["opened_at"]).isoformat().replace("+00:00", "Z")
            for field in ("units", "entry", "stop", "target", "initial_risk"):
                if values[field] is not None:
                    values[field] = float(values[field])
            return json.dumps(values,
                              sort_keys=True, separators=(",", ":"), allow_nan=False)

        @classmethod
        def _existing_open(cls, journal, trade_id: str, raw: dict):
            row = journal.db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if row is None:
                return None
            existing = dict(row)
            existing_raw = {
                "pair": existing["pair"], "side": existing["side"],
                "opened_at": existing["opened_at"], "units": existing["units"],
                "entry": existing["entry"], "stop": existing["stop"],
                "target": existing["target"], "initial_risk": existing["initial_risk"],
                "setup": existing["setup"], "notes": existing["notes"],
                "simulated": bool(existing["simulated"]),
                "broker_trade_id": existing["broker_trade_id"],
            }
            if cls._open_fingerprint(existing_raw) != cls._open_fingerprint(raw):
                raise ValidationError("Idempotency-Key sudah dipakai untuk transaksi berbeda.")
            return {"trade_id": trade_id, "status": "recorded"}

        @classmethod
        def _open_idempotent(cls, journal, payload: dict, key: str):
            payload = dict(payload)
            payload["id"] = cls._idempotency_id(key)
            existing = cls._existing_open(journal, payload["id"], payload)
            if existing:
                return existing
            try:
                return {"trade_id": journal.open_trade(payload), "status": "recorded"}
            except ValidationError:
                # A second request can pass the initial SELECT while the first
                # request is committing. Re-read after the insert race and
                # return the recorded result when the payload matches.
                existing = cls._existing_open(journal, payload["id"], payload)
                if existing:
                    return existing
                raise

        def permitted(self):
            provided = self.headers.get("Authorization", "")
            if not hmac.compare_digest(provided.encode(), ("Bearer " + token).encode()):
                self.error(401, "Bearer token diperlukan.", error_code="unauthorized")
                return False
            with lock:
                key, now = self.client_address[0], time.monotonic()
                # Bounded storage: remove inactive IP entries before adding this request.
                for ip in list(traffic):
                    while traffic[ip] and traffic[ip][0] <= now - 60:
                        traffic[ip].popleft()
                    if not traffic[ip]:
                        del traffic[ip]
                if key not in traffic and len(traffic) >= MAX_RATE_KEYS:
                    oldest = min(traffic, key=lambda ip: traffic[ip][0] if traffic[ip] else now)
                    del traffic[oldest]
                if len(traffic[key]) >= 60:
                    self.error(429, "Batas 60 request/menit tercapai.", error_code="rate_limited")
                    return False
                traffic[key].append(now)
            return True

        @staticmethod
        def _query_bool(query: str, name: str, default: bool = False) -> bool:
            values = parse_qs(query, keep_blank_values=True).get(name)
            if values is None:
                return default
            if len(values) != 1 or values[0] not in ("true", "false"):
                raise ValidationError(f"Parameter {name} harus true atau false.")
            return values[0] == "true"

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self.send(200, {"status": "ok", "execution_enabled": False})
                return
            if parsed.path == "/ready":
                try:
                    with Journal(db_path):
                        pass
                    self.send(200, {"status": "ready", "execution_enabled": False})
                except Exception:
                    self.error(503, "Database belum siap.", error_code="not_ready")
                return
            if not self.permitted():
                return
            if parsed.path == "/v1/agents":
                self.send(200, agent_manifest())
            elif parsed.path == "/v1/journal":
                try:
                    simulated = self._query_bool(parsed.query, "simulated", False)
                    with Journal(db_path) as journal:
                        self.send(200, journal.summary(simulated))
                except ValidationError as exc:
                    self.error(400, str(exc), error_code="invalid_query")
            else:
                self.error(404, "Endpoint tidak ditemukan.", error_code="not_found")

        def do_POST(self):
            if not self.permitted():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    self.error(413, "Body harus 1 byte–4 MiB.", error_code="body_too_large")
                    return
                if self.headers.get_content_type() != "application/json":
                    self.error(415, "Gunakan application/json.", error_code="unsupported_media_type")
                    return
                raw = self.rfile.read(length)
                payload = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValidationError("Angka JSON tidak valid.")))
                if not isinstance(payload, dict):
                    raise ValidationError("Body harus object JSON.")
                path = urlsplit(self.path).path
                with Journal(db_path) as journal:
                    agent = ForexCoordinator(journal, policy)
                    if path in ("/v1/analyze", "/v1/risk") and not isinstance(payload.get("snapshot"), dict):
                        raise ValidationError("Snapshot harus object JSON.")
                    if path == "/v1/analyze":
                        mode = payload.get("mode", "analyst")
                        if mode not in ("analyst", "signal"):
                            raise ValidationError("Gunakan /v1/risk untuk mode risk.")
                        result = agent.analyze(payload["snapshot"], payload.get("timeframe", "M15"), mode)
                    elif path == "/v1/risk":
                        result = agent.analyze(payload["snapshot"], payload.get("timeframe", "M15"), "risk", payload["proposed_trade"])
                    elif path == "/v1/journal/open":
                        header_key = self.headers.get("Idempotency-Key", "").strip()
                        body_key = str(payload.get("client_id", "")).strip()
                        if header_key and body_key and header_key != body_key:
                            raise ValidationError("Idempotency-Key dan client_id berbeda.")
                        idempotency_key = header_key or body_key
                        if idempotency_key:
                            if len(idempotency_key) > 128:
                                raise ValidationError("Idempotency-Key terlalu panjang.")
                            result = self._open_idempotent(journal, payload, idempotency_key)
                        else:
                            result = {"trade_id": journal.open_trade(payload), "status": "recorded"}
                    elif path == "/v1/journal/close":
                        journal.close_trade(payload["trade_id"], payload["net_pnl"], utc(payload["closed_at"]))
                        result = {"status": "closed"}
                    elif path == "/v1/journal/link":
                        journal.link_broker_trade(payload["trade_id"], payload["broker_trade_id"])
                        result = {"status": "linked"}
                    elif path == "/v1/journal/amend":
                        journal.amend_open_trade(payload["trade_id"], payload)
                        result = {"status": "amended"}
                    else:
                        self.error(404, "Endpoint tidak ditemukan.", error_code="not_found")
                        return
                self.send(200, result)
            except ValidationError as exc:
                status = 409 if str(exc).startswith("Idempotency-Key") else 400
                self.error(status, str(exc), error_code="conflict" if status == 409 else "invalid_request")
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                self.error(400, str(exc), error_code="invalid_request")
            except Exception:
                LOGGER.exception("api_operation_failed path=%s", urlsplit(self.path).path)
                self.error(500, "Operasi gagal; tidak ada sinyal yang dapat digunakan.",
                           error_code="internal_error")

    return Handler


def serve(db_path="data/journal.sqlite3", host="127.0.0.1", port=8000, policy=None):
    token = os.getenv("FOREX_API_TOKEN", "")
    if len(token) < 32:
        raise ValidationError("Set FOREX_API_TOKEN minimal 32 karakter sebelum menjalankan API.")
    server = ThreadingHTTPServer((host, port), handler_factory(db_path, token, policy or RiskPolicy()))
    print(f"Forex Agent API: http://{host}:{port} — hentikan dengan Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
