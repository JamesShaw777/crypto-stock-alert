#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


def load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "market_alert.py"
    spec = importlib.util.spec_from_file_location("market_alert", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load market_alert module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEventChartCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def _rule(self, rid: str, symbol: str, event_type: str = "rsi_cross_50_up"):
        params = self.mod.normalize_event_params_for_compare(
            event_type,
            {
                "severity": "auto",
                "attach_chart": False,
                "lookback_bars": 20,
            },
        )
        return {
            "id": rid,
            "event_type": event_type,
            "asset_type": "crypto",
            "symbol": "BTC",
            "quote_symbol": symbol,
            "period": "5d",
            "interval": "15m",
            "confirm_bars": 1,
            "cooldown_minutes": 0,
            "dedup_mode": "cross_once",
            "params": params,
            "enabled": True,
        }

    def test_fetch_once_per_unique_key(self):
        rules = [
            self._rule("r1", "BTC-USD"),
            self._rule("r2", "BTC-USD"),  # same key as r1
            self._rule("r3", "ETH-USD"),  # different key
        ]
        calls = []

        def fake_fetch(asset_type, chart_symbol, period, interval):
            calls.append((asset_type, chart_symbol, period, interval))
            return {
                "asset_type": asset_type,
                "input_symbol": chart_symbol,
                "symbol": chart_symbol,
                "period": period,
                "interval": interval,
                "source": "fake",
                "provider": "fake",
                "as_of": "2026-03-02T00:00:00Z",
                "checked_at": "2026-03-02T00:00:00Z",
                "candles": [],
            }

        with mock.patch.object(self.mod, "fetch_chart_data", side_effect=fake_fetch):
            rule_ctx_by_id, chart_cache, chart_cache_error, metrics = self.mod.build_event_chart_cache(rules)

        self.assertEqual(len(rule_ctx_by_id), 3)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(chart_cache), 2)
        self.assertEqual(chart_cache_error, {})
        self.assertEqual(metrics["enabled_rules"], 3)
        self.assertEqual(metrics["chart_cache_fetches"], 2)
        self.assertEqual(metrics["chart_cache_reused_rules"], 1)
        self.assertEqual(metrics["chart_cache_failures"], 0)
        self.assertEqual(metrics["chart_cache_unique_keys"], 2)

    def test_with_workers_exposes_prefetch_metrics(self):
        rules = [
            self._rule("r1", "BTC-USD"),
            self._rule("r2", "ETH-USD"),
        ]

        def fake_fetch(asset_type, chart_symbol, period, interval):
            return {
                "asset_type": asset_type,
                "input_symbol": chart_symbol,
                "symbol": chart_symbol,
                "period": period,
                "interval": interval,
                "source": "fake",
                "provider": "fake",
                "as_of": "2026-03-02T00:00:00Z",
                "checked_at": "2026-03-02T00:00:00Z",
                "candles": [],
            }

        with mock.patch.object(self.mod, "fetch_chart_data", side_effect=fake_fetch):
            _, _, _, metrics = self.mod.build_event_chart_cache_with_workers(rules, prefetch_workers=8)

        self.assertEqual(metrics["chart_cache_prefetch_workers"], 8)
        self.assertEqual(metrics["chart_cache_unique_keys"], 2)
        self.assertEqual(metrics["chart_cache_fetches"], 2)
        self.assertIn("chart_cache_prefetch_duration_ms", metrics)


if __name__ == "__main__":
    unittest.main()
