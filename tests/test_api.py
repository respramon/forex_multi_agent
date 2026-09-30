import http.client
import json
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from forex_agent.api import handler_factory
from forex_agent.cli import write_json
from forex_agent.demo import make_snapshot
from forex_agent.models import RiskPolicy


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.token = "test-token-" + "a" * 40
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(
            cls.folder.name + "/journal.sqlite3", cls.token, RiskPolicy()))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.folder.cleanup()

    def request(self, method, path, body=None, auth=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json", **(headers or {})}
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        result = (response.status, json.loads(response.read()))
        connection.close()
        return result

    def test_health_and_authentication(self):
        status, body = self.request("GET", "/health", auth=False)
        self.assertEqual(status, 200)
        self.assertFalse(body["execution_enabled"])
        self.assertEqual(self.request("GET", "/v1/journal", auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/v1/journal")[0], 200)

    def test_forex_agent_manifest_requires_authentication(self):
        self.assertEqual(self.request("GET", "/v1/agents", auth=False)[0], 401)
        status, manifest = self.request("GET", "/v1/agents")
        self.assertEqual(status, 200)
        self.assertEqual(manifest["agent_count"], 8)
        self.assertTrue(manifest["forex_only"])
        self.assertNotIn("XAU/USD", manifest["pairs"])

    def test_analyze_api_returns_multi_agent_observations(self):
        payload = {"snapshot": make_snapshot(), "mode": "analyst"}
        status, report = self.request("POST", "/v1/analyze", json.dumps(payload))
        self.assertEqual(status, 200)
        self.assertEqual(report["status"], "ANALYSIS_ONLY")
        self.assertEqual(report["coordination"]["architecture"], "forex_multi_agent")
        self.assertEqual({item["agent"] for item in report["agent_reports"]},
                         {"data_validation", "technical", "fundamental"})

    def test_malformed_request_and_nan_rejected(self):
        self.assertEqual(self.request("POST", "/v1/analyze", "{")[0], 400)
        self.assertEqual(self.request("POST", "/v1/analyze", '{"value": NaN}')[0], 400)

    def test_no_file_paths_or_execution_route(self):
        self.assertEqual(self.request("POST", "/v1/order", "{}")[0], 404)
        self.assertEqual(self.request("POST", "/v1/analyze", '{"snapshot":"/etc/passwd"}')[0], 400)

    def test_existing_real_journal_trade_can_link_a_broker_ticket(self):
        trade = {"id": "api-link", "pair": "EUR/USD", "side": "BUY",
                 "opened_at": "2026-01-15T10:00:00Z", "units": 10000,
                 "entry": 1.1, "stop": 1.09, "target": 1.12,
                 "initial_risk": 110, "simulated": False}
        self.assertEqual(self.request("POST", "/v1/journal/open", json.dumps(trade))[0], 200)
        link = {"trade_id": "api-link", "broker_trade_id": "ticket-7"}
        self.assertEqual(self.request("POST", "/v1/journal/link", json.dumps(link))[0], 200)
        self.assertEqual(self.request("POST", "/v1/journal/link", json.dumps(
            {**link, "broker_trade_id": "ticket-8"}))[0], 400)

    def test_journal_open_is_idempotent_for_client_id_and_header_key(self):
        baseline = self.request("GET", "/v1/journal?simulated=true")[1]["open_trades"]
        trade = {"client_id": "api-idempotent-1", "pair": "EUR/USD", "side": "BUY",
                 "opened_at": "2026-01-15T10:00:00Z", "units": 10000,
                 "entry": 1.1, "stop": 1.09, "target": 1.12,
                 "initial_risk": 110, "simulated": True}
        first = self.request("POST", "/v1/journal/open", json.dumps(trade))
        second = self.request("POST", "/v1/journal/open", json.dumps(trade))
        self.assertEqual(first[0], 200)
        self.assertEqual(second, first)
        self.assertEqual(self.request("GET", "/v1/journal?simulated=true")[1]["open_trades"], baseline + 1)

        header_trade = {"pair": "GBP/USD", "side": "BUY", "opened_at": "2026-01-15T10:00:00Z",
                        "units": 10000, "entry": 1.3, "stop": 1.29, "target": 1.32,
                        "initial_risk": 110, "simulated": True}
        headers = {"Idempotency-Key": "api-header-idempotent-1"}
        first = self.request("POST", "/v1/journal/open", json.dumps(header_trade), headers=headers)
        second = self.request("POST", "/v1/journal/open", json.dumps(header_trade), headers=headers)
        self.assertEqual(first[0], 200)
        self.assertEqual(second, first)
        self.assertEqual(self.request("GET", "/v1/journal?simulated=true")[1]["open_trades"], baseline + 2)

        changed = {**header_trade, "units": 11000}
        self.assertEqual(self.request("POST", "/v1/journal/open", json.dumps(changed), headers=headers)[0], 409)
        malformed_retry = {**header_trade, "simulated": "false"}
        self.assertEqual(self.request("POST", "/v1/journal/open", json.dumps(malformed_retry), headers=headers)[0], 409)

    def test_journal_open_idempotency_handles_concurrent_retries(self):
        trade = {"pair": "AUD/USD", "side": "BUY", "opened_at": "2026-01-15T10:00:00Z",
                 "units": 10000, "entry": 0.7, "stop": 0.69, "target": 0.72,
                 "initial_risk": 110, "simulated": True}
        barrier = threading.Barrier(4)
        results = []
        lock = threading.Lock()

        def submit():
            barrier.wait()
            result = self.request("POST", "/v1/journal/open", json.dumps(trade),
                                  headers={"Idempotency-Key": "api-concurrent-idempotent-1"})
            with lock:
                results.append(result)

        workers = [threading.Thread(target=submit) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(len({body["trade_id"] for _, body in results}), 1)

    def test_query_boolean_and_readiness_are_strict(self):
        self.assertEqual(self.request("GET", "/v1/journal?simulated=1")[0], 400)
        self.assertEqual(self.request("GET", "/v1/journal?simulated=true&simulated=false")[0], 400)
        status, body = self.request("GET", "/ready", auth=False)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ready")

    def test_write_json_is_atomic_and_owner_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "report.json"
            write_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
