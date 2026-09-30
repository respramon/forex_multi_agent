import io
import json
import unittest
from unittest.mock import patch
import urllib.error

from forex_agent.http_client import request_json


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return json.dumps(self.value).encode()


class RetryAfterTests(unittest.TestCase):
    def test_get_retry_honors_bounded_retry_after(self):
        calls = []

        class Opener:
            def open(self, _request, timeout):
                calls.append(timeout)
                if len(calls) == 1:
                    raise urllib.error.HTTPError(
                        "https://provider.example/test", 429, "slow down", {"Retry-After": "7"}, io.BytesIO())
                return _Response({"ok": True})

        with patch("forex_agent.http_client.urllib.request.build_opener", return_value=Opener()), \
             patch("forex_agent.http_client.time.sleep") as sleep:
            self.assertEqual(request_json("https://provider.example/test", timeout=3), {"ok": True})
        sleep.assert_called_once_with(7.0)
        self.assertEqual(calls, [3, 3])

    def test_invalid_retry_after_uses_bounded_backoff(self):
        calls = []

        class Opener:
            def open(self, _request, timeout):
                calls.append(timeout)
                if len(calls) == 1:
                    raise urllib.error.HTTPError(
                        "https://provider.example/test", 503, "busy", {"Retry-After": "NaN"}, io.BytesIO())
                return _Response({"ok": True})

        with patch("forex_agent.http_client.urllib.request.build_opener", return_value=Opener()), \
             patch("forex_agent.http_client.time.sleep") as sleep:
            self.assertEqual(request_json("https://provider.example/test", timeout=3), {"ok": True})
        sleep.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
