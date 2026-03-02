#!/usr/bin/env python3
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "market_alert.py"
    spec = importlib.util.spec_from_file_location("market_alert", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load market_alert module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_synthetic_chart():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 100.0
    for i in range(420):
        wave = ((i % 40) - 20) * 0.12
        drift = 0.02 if i % 80 < 40 else -0.015
        close = max(1.0, price + drift + wave * 0.05)
        open_ = price
        high = max(open_, close) + 0.5 + abs(wave) * 0.02
        low = min(open_, close) - 0.5 - abs(wave) * 0.02
        volume = 1000.0 + (i % 35) * 20.0 + abs(wave) * 8.0
        candles.append(
            {
                "dt": start + timedelta(minutes=15 * i),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
            }
        )
        price = close
    as_of = candles[-1]["dt"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "asset_type": "crypto",
        "input_symbol": "BTC",
        "symbol": "BTC-USD",
        "period": "5d",
        "interval": "15m",
        "source": "synthetic",
        "provider": "synthetic",
        "as_of": as_of,
        "checked_at": as_of,
        "candles": candles,
    }


class TestEventEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()
        cls.chart_payload = build_synthetic_chart()

    def _rule_for_event(self, event_type: str):
        raw_params = {
            "severity": "auto",
            "attach_chart": False,
            "hist_expand_bars": 3,
            "lookback_bars": 20,
            "bb_width_threshold": 0.06,
            "volume_spike_multiplier": 1.8,
            "volume_dry_threshold": 0.6,
            "fib_anchor_bars": 120,
            "fib_touch_tolerance": 0.002,
            "pivot_left": 3,
            "pivot_right": 3,
            "min_pivot_gap": 5,
            "max_pivot_gap": 120,
            "min_price_delta_pct": 0.3,
            "min_indicator_delta": 0.1,
            "dedup_window_bars": 20,
        }
        if event_type.startswith("macd_"):
            raw_params.update(
                {
                    "macd_profile": "user_7_10_30",
                    "macd_fast": 7,
                    "macd_slow": 10,
                    "macd_signal": 30,
                }
            )
        params = self.mod.normalize_event_params_for_compare(event_type, raw_params)
        return {
            "id": f"rule-{event_type}",
            "event_type": event_type,
            "asset_type": "crypto",
            "symbol": "BTC",
            "quote_symbol": "BTC-USD",
            "period": "5d",
            "interval": "15m",
            "confirm_bars": 1,
            "cooldown_minutes": 0,
            "dedup_mode": "cross_once",
            "params": params,
            "channel": "",
            "target": "",
            "enabled": True,
        }

    def test_all_event_types_can_evaluate_and_format_message(self):
        for event_type in self.mod.EVENT_TYPE_CHOICES:
            with self.subTest(event_type=event_type):
                rule = self._rule_for_event(event_type)
                evaluation = self.mod.evaluate_event_rule_on_chart(rule, self.chart_payload)
                self.assertIn("condition", evaluation)
                self.assertIsInstance(evaluation["condition"], bool)
                message = self.mod.format_event_message(rule, evaluation)
                self.assertIn(event_type, message)

    def test_upsert_event_rule_is_idempotent(self):
        rules = []
        event_type = "rsi_cross_50_up"
        rule_base = self._rule_for_event(event_type)
        created_rule, created = self.mod.upsert_event_rule(
            rules=rules,
            event_type=event_type,
            asset_type=rule_base["asset_type"],
            symbol_for_rule=rule_base["symbol"],
            quote_symbol=rule_base["quote_symbol"],
            period=rule_base["period"],
            interval=rule_base["interval"],
            confirm_bars=rule_base["confirm_bars"],
            cooldown_minutes=rule_base["cooldown_minutes"],
            dedup_mode=rule_base["dedup_mode"],
            params=rule_base["params"],
            channel=rule_base["channel"],
            target=rule_base["target"],
            note="",
        )
        self.assertTrue(created)
        self.assertEqual(len(rules), 1)

        same_rule, created_again = self.mod.upsert_event_rule(
            rules=rules,
            event_type=event_type,
            asset_type=rule_base["asset_type"],
            symbol_for_rule=rule_base["symbol"],
            quote_symbol=rule_base["quote_symbol"],
            period=rule_base["period"],
            interval=rule_base["interval"],
            confirm_bars=rule_base["confirm_bars"],
            cooldown_minutes=rule_base["cooldown_minutes"],
            dedup_mode=rule_base["dedup_mode"],
            params=rule_base["params"],
            channel=rule_base["channel"],
            target=rule_base["target"],
            note="",
        )
        self.assertFalse(created_again)
        self.assertEqual(created_rule["id"], same_rule["id"])
        self.assertEqual(len(rules), 1)


if __name__ == "__main__":
    unittest.main()
