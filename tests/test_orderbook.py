import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forex_agent.models import Account, RiskPolicy, ValidationError
from forex_agent.orderbook import OrderBook


T = datetime(2026, 1, 1, tzinfo=timezone.utc)


class OrderBookTests(unittest.TestCase):
    def setUp(self):
        self.account = Account(10_000, 10_000, 10_000, "USD", T)
        self.policy = RiskPolicy()

    def _submit(self, book, client_id, pair="EUR/USD", risk=100):
        return book.submit(client_id=client_id, pair=pair, side="BUY", units=1000,
                           estimated_risk=risk, created_at=T,
                           account=self.account, policy=self.policy)

    def test_partial_fill_is_idempotent_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "orders.sqlite3")
            with OrderBook(path) as book:
                self._submit(book, "alpha")
                self.assertEqual(self._submit(book, "alpha")["status"], "PENDING")
                self.assertEqual(book.fill("alpha", execution_id="ex1", units=400,
                                           price=1.1, filled_at=T)["status"], "PARTIAL")
                book.fill("alpha", execution_id="ex1", units=400, price=1.1, filled_at=T)
                with self.assertRaises(ValidationError):
                    book.fill("alpha", execution_id="ex1", units=400, price=1.2, filled_at=T)
                with self.assertRaises(ValidationError):
                    book.fill("alpha", execution_id="ex2", units=700, price=1.1, filled_at=T)
            with OrderBook(path) as book:
                self.assertEqual(book.get("alpha")["filled_units"], 400)
                self.assertEqual(book.reserved()["total"], 100)
                book.cancel("alpha", T + timedelta(seconds=1))
                self.assertEqual(book.reserved()["total"], 40)
                with self.assertRaises(ValidationError):
                    book.fill("alpha", execution_id="ex2", units=1, price=1.1,
                              filled_at=T + timedelta(seconds=2))
                book.close("alpha", T + timedelta(seconds=2))
                self.assertEqual(book.reserved()["total"], 0)

    def test_currency_reservations_are_atomic_and_time_cannot_go_back(self):
        with OrderBook() as book:
            self._submit(book, "a", "EUR/USD")
            self._submit(book, "b", "GBP/USD")
            self._submit(book, "c", "AUD/USD")
            with self.assertRaisesRegex(ValidationError, "USD"):
                self._submit(book, "d", "USD/JPY")
            with self.assertRaises(ValidationError):
                self._submit(book, "a", "EUR/USD", 90)
            book.fill("a", execution_id="f", units=1000, price=1.1,
                      filled_at=T + timedelta(seconds=1))
            with self.assertRaises(ValidationError):
                book.close("a", T)
            book.close("a", T + timedelta(seconds=2))
            self._submit(book, "d", "USD/JPY")


if __name__ == "__main__":
    unittest.main()
