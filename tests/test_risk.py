import unittest
from dataclasses import replace
from forex_agent.models import Account, Instrument, RiskPolicy, ValidationError, utc
from forex_agent.risk import floor_step, portfolio_gate, size_position


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.account = Account(10000, 10000, 10000, "USD", utc("2026-01-15T12:00:00Z"))
        self.spec = Instrument("EUR/USD", .0001, .00001, 100000, 1000, 1000, 1000000, .02)
        self.conv = {"account_currency": "USD", "loss_factor": 1, "gain_factor": 1, "position_factor": 1}

    def calc(self, **overrides):
        args = dict(entry=1.1, stop=1.095, target=1.112, side="BUY", instrument=self.spec,
                    account=self.account, conversion=self.conv, spread=0, slippage=0, policy=RiskPolicy())
        args.update(overrides)
        return size_position(**args)

    def test_eurusd_expected_cash_and_lots(self):
        r = self.calc()
        self.assertTrue(r["approved"])
        self.assertAlmostEqual(r["lots"], .2)
        self.assertAlmostEqual(r["estimated_loss"], 100)
        self.assertAlmostEqual(r["net_rr"], 2.4)

    def test_sell_geometry(self):
        self.assertTrue(self.calc(side="SELL", stop=1.105, target=1.088)["approved"])
        with self.assertRaises(ValidationError):
            self.calc(side="SELL")

    def test_jpy_conversion(self):
        spec = replace(self.spec, pair="USD/JPY", pip_size=.01, tick_size=.001)
        r = self.calc(entry=150, stop=149, target=152.5, instrument=spec,
                      conversion={"account_currency": "USD", "loss_factor": 1/150, "gain_factor": 1/150, "position_factor": 1/150})
        self.assertEqual(r["units"], 15000)
        self.assertAlmostEqual(r["estimated_loss"], 100)
        self.assertAlmostEqual(r["stop_distance_pips"], 100)

    def test_broker_contract_size_controls_fx_lot_equivalent(self):
        r = self.calc(instrument=replace(self.spec, contract_size=10000))
        self.assertEqual(r["units"], 20000)
        self.assertEqual(r["lots"], 2)
        self.assertAlmostEqual(r["estimated_loss"], 100)

    def test_non_forex_instrument_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "khusus forex"):
            replace(self.spec, pair="XAU/USD")

    def test_costs_can_invalidate_gross_two_rr(self):
        r = self.calc(target=1.11, spread=.0002, slippage=.0001)
        self.assertFalse(r["approved"])
        self.assertLess(r["net_rr"], 2)
        self.assertLessEqual(r["estimated_loss"], r["risk_budget"])

    def test_minimum_commission_is_in_budget(self):
        r = self.calc(instrument=replace(self.spec, min_commission_roundtrip=15))
        self.assertLessEqual(r["estimated_loss"], 100 + 1e-8)
        self.assertAlmostEqual(r["estimated_roundtrip_cost"], 15)

    def test_never_round_up_to_minimum(self):
        r = self.calc(account=replace(self.account, equity=10, free_margin=10, day_start_equity=10))
        self.assertFalse(r["approved"])
        self.assertEqual(r["units"], 0)

    def test_margin_limits_quantity(self):
        r = self.calc(account=replace(self.account, free_margin=100))
        self.assertLessEqual(r["estimated_margin"], 50)

    def test_oversized_manual_trade_rejected(self):
        self.assertFalse(self.calc(requested_units=100000)["approved"])
        self.assertFalse(self.calc(requested_units=1500)["approved"])

    def test_floats_floor_and_nan(self):
        self.assertEqual(floor_step(.029, .01), .02)
        with self.assertRaises(ValidationError):
            self.calc(entry=float("nan"))

    def test_non_usd_account_conversion(self):
        r = self.calc(account=replace(self.account, currency="EUR"),
                      conversion={"account_currency": "EUR", "loss_factor": .9, "gain_factor": .89, "position_factor": .9})
        self.assertLessEqual(r["estimated_loss"], 100)
        self.assertGreater(r["units"], 20000)

    def test_hard_policy_limits(self):
        for args in ({"risk_fraction": .0201}, {"risk_fraction": 0}, {"min_rr": 1.99},
                     {"min_confirmations": 2}, {"max_trades_per_day": 2.5}):
            with self.assertRaises(ValidationError):
                RiskPolicy(**args)

    def test_equity_drawdown_and_currency_concentration(self):
        self.assertTrue(portfolio_gate(replace(self.account, equity=9600, free_margin=9600), {}, RiskPolicy(), "EUR/USD"))
        state = {"open_risk": 250, "currency_risk": {"USD": 250}}
        result = portfolio_gate(self.account, state, RiskPolicy(), "GBP/USD", 100)
        self.assertTrue(any("USD" in r for r in result))


if __name__ == "__main__":
    unittest.main()
