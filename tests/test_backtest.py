import unittest
from datetime import datetime, timedelta, timezone

from forex_agent.backtest import Backtest
from forex_agent.models import RiskPolicy, ValidationError, iso


START = datetime(2026, 1, 5, 0, 5, tzinfo=timezone.utc)


def dataset(count=40, pairs=("EUR/USD",)):
    bars = {}
    instruments = {}
    for pair in pairs:
        bars[pair] = [dict(time=iso(START + timedelta(minutes=5 * i)),
                           open=1.1, high=1.1001, low=1.0999, close=1.1,
                           volume=1, complete=True) for i in range(count)]
        instruments[pair] = dict(pair=pair, pip_size=0.0001, tick_size=0.00001,
                                 contract_size=100000, units_step=1000,
                                 min_units=1000, max_units=1000000, margin_rate=0.05)
    return {"simulated": True, "timeframe": "M5", "initial_equity": 10000,
            "account_currency": "USD", "bars": bars, "instruments": instruments,
            "assumptions": {"spread": {p: 0.00002 for p in pairs},
                            "slippage": {p: 0 for p in pairs},
                            "max_drawdown_fraction": 0.1}}


class TrackingStrategy:
    def __init__(self):
        self.seen = []

    def on_close(self, pair, history):
        self.seen.append((pair, len(history), history[-1].time))
        return "BUY" if len(history) == 15 else "SELL" if len(history) == 16 else None


class BacktestTests(unittest.TestCase):
    def test_strategy_updates_while_position_open_and_events_are_ordered(self):
        strategy = TrackingStrategy()
        result = Backtest(dataset(), strategy=strategy).run()
        self.assertEqual(len(strategy.seen), 40)
        self.assertEqual(result["open_positions"], ["EUR/USD"])
        kinds = [e["kind"] for e in result["events"]]
        self.assertEqual(kinds[:3], ["order_submitted", "fill", "signal_ignored"])
        self.assertEqual(result["events"][0]["time"], result["events"][1]["time"])
        self.assertEqual([e["phase"] for e in result["events"][:2]], [1, 2])
        self.assertTrue(all((a["time"], a["phase"]) <=
                            (b["time"], b["phase"])
                            for a, b in zip(result["events"], result["events"][1:])))

    def test_stop_wins_intrabar_tie_and_drawdown_halts_future_orders(self):
        data = dataset()
        data["bars"]["EUR/USD"][15].update(high=1.2, low=1.0)
        data["assumptions"]["max_drawdown_fraction"] = 0.0001
        result = Backtest(data, strategy=TrackingStrategy()).run()
        self.assertEqual(result["trades"][0]["reason"], "stop")
        self.assertLess(result["trades"][0]["net_pnl"], 0)
        self.assertTrue(result["risk_halted"])
        self.assertEqual(result["open_positions"], [])

    def test_missing_symbol_candle_rejected_before_any_replay(self):
        data = dataset(pairs=("EUR/USD", "GBP/USD"))
        del data["bars"]["GBP/USD"][10]
        with self.assertRaisesRegex(ValidationError, "hilang"):
            Backtest(data)
        single = dataset()
        del single["bars"]["EUR/USD"][10]
        with self.assertRaisesRegex(ValidationError, "hilang"):
            Backtest(single)

    def test_future_signal_does_not_fill_on_final_bar(self):
        class FinalOnly:
            def on_close(self, pair, history):
                return "BUY" if len(history) == 40 else None
        result = Backtest(dataset(), strategy=FinalOnly()).run()
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["open_positions"], [])
        self.assertEqual(result["events"][-1]["kind"], "unfilled_at_end")
        engine = Backtest(dataset(), strategy=FinalOnly())
        engine.run()
        with self.assertRaises(ValidationError):
            engine.run()

    def test_next_open_sizing_cannot_see_other_symbols_future_close(self):
        class TwoSignals:
            def on_close(self, pair, history):
                if pair == "EUR/USD" and len(history) == 15:
                    return "BUY"
                if pair == "GBP/USD" and len(history) == 16:
                    return "BUY"
                return None

        ordinary = dataset(pairs=("EUR/USD", "GBP/USD"))
        shock = dataset(pairs=("EUR/USD", "GBP/USD"))
        # At bar 17's open GBP is filled while EUR remains open. EUR's future
        # close within that bar cannot influence GBP's open-time risk check.
        shock["bars"]["EUR/USD"][16].update(low=1.0799, close=1.08)
        policy = RiskPolicy(cooldown_minutes=1)
        first = Backtest(ordinary, strategy=TwoSignals(), policy=policy).run()
        second = Backtest(shock, strategy=TwoSignals(), policy=policy).run()
        fills = lambda result: [(e["pair"], e["units"]) for e in result["events"]
                                if e["kind"] == "fill"]
        self.assertEqual(fills(first), fills(second))
        self.assertEqual(len(fills(first)), 2)

    def test_variable_spread_and_financing_change_mark_to_market(self):
        base = dataset()
        variable = dataset()
        variable["assumptions"]["spread"]["EUR/USD"] = [0.00002] * 16 + [0.00004] * 24
        variable["assumptions"]["financing_per_unit"] = {"EUR/USD": {"BUY": -0.0000001}}
        ordinary = Backtest(base, strategy=TrackingStrategy()).run()
        expensive = Backtest(variable, strategy=TrackingStrategy()).run()
        self.assertLess(expensive["final_equity"], ordinary["final_equity"])
        self.assertIn("financing", [item["kind"] for item in expensive["events"]])
        variable["assumptions"]["spread"]["EUR/USD"] = [0.00002] * 39
        with self.assertRaisesRegex(ValidationError, "spread"):
            Backtest(variable)

    def test_all_open_gap_exits_precede_pending_fills_regardless_of_pair_order(self):
        class GapExitAndPending:
            def on_close(self, pair, history):
                if pair == "GBP/USD" and len(history) == 15:
                    return "BUY"
                if pair == "EUR/USD" and len(history) == 16:
                    return "BUY"
                return None

        def run(pairs):
            data = dataset(pairs=pairs)
            data["bars"]["GBP/USD"][16].update(
                open=1.098, high=1.1001, low=1.097, close=1.098)
            return Backtest(data, strategy=GapExitAndPending(),
                            policy=RiskPolicy(cooldown_minutes=1)).run()

        forward = run(("EUR/USD", "GBP/USD"))
        reverse = run(("GBP/USD", "EUR/USD"))
        for result in (forward, reverse):
            same_time = [event for event in result["events"]
                         if event["time"] == "2026-01-05T01:20:00Z" and event["phase"] == 2]
            self.assertEqual([(event["pair"], event["kind"]) for event in same_time],
                             [("GBP/USD", "exit"), ("EUR/USD", "fill")])
            self.assertEqual(result["open_positions"], ["EUR/USD"])
        self.assertEqual(forward["trades"], reverse["trades"])
        self.assertEqual(forward["equity_curve"], reverse["equity_curve"])

    def test_stop_trigger_uses_side_aware_quote_from_midpoint_ohlc(self):
        for side, updates in (
            ("BUY", {"low": 1.09971, "high": 1.1001}),
            ("SELL", {"low": 1.0999, "high": 1.10029}),
        ):
            class SingleSignal:
                def on_close(self, pair, history):
                    return side if len(history) == 15 else None

            data = dataset()
            data["bars"]["EUR/USD"][15].update(**updates)
            result = Backtest(data, strategy=SingleSignal()).run()
            self.assertEqual(result["trades"][0]["reason"], "stop")

    def test_metrics_report_realized_and_unrealized_pnl(self):
        result = Backtest(dataset(), strategy=TrackingStrategy()).run()
        self.assertAlmostEqual(result["metrics"]["realized_pnl"], 0)
        self.assertAlmostEqual(result["metrics"]["unrealized_pnl"],
                               result["final_equity"] - result["initial_equity"])


if __name__ == "__main__":
    unittest.main()
