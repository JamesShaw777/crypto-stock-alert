#!/usr/bin/env python3
"""OpenClaw market alert helper for crypto and stocks.

Features:
- Fetch quotes with multi-provider fallback
- Manage threshold alerts (above/below)
- Periodic checks with edge-triggered notifications (crossing threshold)
- Generate chart images (candlestick/line)
- Calculate technical indicators (SMA/EMA/MACD/RSI/BB/Fibonacci)
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import math
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DEFAULT_TIMEOUT_SECONDS = 12

DEFAULT_STATE_DIR = Path.home() / ".openclaw" / "skills-data" / "crypto-stock-alert"
STATE_DIR = Path(os.environ.get("OPENCLAW_MARKET_ALERT_STATE_DIR", str(DEFAULT_STATE_DIR))).expanduser()
ALERTS_FILE = STATE_DIR / "alerts.json"
STATUS_FILE = STATE_DIR / "status.json"
LOG_FILE = STATE_DIR / "check.log"
LOCK_FILE = STATE_DIR / "check.lock"
EVENT_RULES_FILE = STATE_DIR / "event_rules.json"
EVENT_STATUS_FILE = STATE_DIR / "event_status.json"
EVENT_LOCK_FILE = STATE_DIR / "event_check.lock"
CHART_DIR = STATE_DIR / "charts"

CRON_BLOCK_START = "# OPENCLAW_CRYPTO_STOCK_ALERT_START"
CRON_BLOCK_END = "# OPENCLAW_CRYPTO_STOCK_ALERT_END"

STOCK_PERIOD_CHOICES = ("1d", "5d", "1mo", "3mo", "6mo", "1y")
STOCK_INTERVAL_CHOICES = ("15m", "30m", "60m", "90m", "1d", "1wk")
CRYPTO_PERIOD_CHOICES = ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y")
CRYPTO_INTERVAL_CHOICES = ("15m", "30m", "60m", "90m", "1d", "1wk")

INTERVAL_ALIASES = {
    "1h": "60m",
}

INTERVAL_MINUTES = {
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "90m": 90,
    "1d": 1440,
    "1wk": 10080,
}

PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
}

CRYPTO_ALIAS_TO_SYMBOL = {
    "BTC": "BTC",
    "XBT": "BTC",
    "BITCOIN": "BTC",
    "比特币": "BTC",
    "ETH": "ETH",
    "ETHEREUM": "ETH",
    "以太坊": "ETH",
    "SOL": "SOL",
    "DOGE": "DOGE",
    "DOGECOIN": "DOGE",
    "XRP": "XRP",
    "ADA": "ADA",
    "BNB": "BNB",
    "LTC": "LTC",
    "TRX": "TRX",
    "AVAX": "AVAX",
    "MATIC": "MATIC",
}

COINGECKO_SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "BNB": "binancecoin",
    "LTC": "litecoin",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
}

FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)

MACD_EVENT_TYPES = (
    "macd_golden_cross",
    "macd_dead_cross",
    "macd_golden_cross_above_zero",
    "macd_dead_cross_below_zero",
    "macd_zero_cross_up",
    "macd_zero_cross_down",
    "macd_hist_turn_positive",
    "macd_hist_turn_negative",
    "macd_hist_expand_up_n",
    "macd_hist_expand_down_n",
)
RSI_EVENT_TYPES = (
    "rsi_cross_30_up",
    "rsi_cross_70_down",
    "rsi_enter_overbought",
    "rsi_enter_oversold",
    "rsi_cross_50_up",
    "rsi_cross_50_down",
)
MA_EVENT_TYPES = (
    "price_cross_sma20_up",
    "price_cross_sma20_down",
    "price_cross_ema20_up",
    "price_cross_ema20_down",
    "ema20_cross_ema50_up",
    "ema20_cross_ema50_down",
    "ma_bull_alignment",
    "ma_bear_alignment",
)
BB_EVENT_TYPES = (
    "bb_touch_upper",
    "bb_touch_lower",
    "bb_close_outside_upper",
    "bb_close_outside_lower",
    "bb_reenter_from_upper",
    "bb_reenter_from_lower",
    "bb_squeeze_start",
    "bb_squeeze_breakout_up",
    "bb_squeeze_breakout_down",
)
VOLUME_EVENT_TYPES = (
    "volume_spike_up",
    "volume_spike_down",
    "volume_dry_up",
    "obv_cross_ma_up",
    "obv_cross_ma_down",
)
BREAKOUT_EVENT_TYPES = (
    "breakout_n_bar_high",
    "breakdown_n_bar_low",
    "donchian_breakout_up",
    "donchian_breakout_down",
    "swing_high_break",
    "swing_low_break",
)
FIB_EVENT_TYPES = (
    "fib_touch_0_382",
    "fib_touch_0_5",
    "fib_touch_0_618",
    "fib_reject_0_618_up",
    "fib_reject_0_618_down",
    "fib_break_0_618_up",
    "fib_break_0_618_down",
)
DIVERGENCE_EVENT_TYPES = (
    "rsi_regular_bull_div",
    "rsi_regular_bear_div",
    "macd_regular_bull_div",
    "macd_regular_bear_div",
    "obv_regular_bull_div",
    "obv_regular_bear_div",
    "rsi_hidden_bull_div",
    "rsi_hidden_bear_div",
    "macd_hidden_bull_div",
    "macd_hidden_bear_div",
)

EVENT_TYPE_CHOICES = (
    MACD_EVENT_TYPES
    + RSI_EVENT_TYPES
    + MA_EVENT_TYPES
    + BB_EVENT_TYPES
    + VOLUME_EVENT_TYPES
    + BREAKOUT_EVENT_TYPES
    + FIB_EVENT_TYPES
    + DIVERGENCE_EVENT_TYPES
)

MACD_HIST_EXPAND_EVENT_TYPES = ("macd_hist_expand_up_n", "macd_hist_expand_down_n")
MACD_EVENT_WITH_PROFILE_TYPES = tuple(t for t in EVENT_TYPE_CHOICES if t.startswith("macd_"))
EVENT_SEVERITY_CHOICES = ("auto", "info", "warning", "critical")
EVENT_PRESET_CHOICES = (
    "preset_stock_trend",
    "preset_stock_reversal",
    "preset_crypto_momentum_15m",
    "preset_crypto_divergence_15m",
    "preset_fib_pullback",
    "preset_breakout_follow",
)

MACD_PROFILES: dict[str, tuple[int, int, int]] = {
    "standard": (12, 26, 9),
    "fast_crypto": (8, 21, 5),
    "slow_trend": (19, 39, 9),
    "user_7_10_30": (7, 10, 30),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ts_to_iso(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return now_iso()


def iso_to_dt(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_chart_dir() -> None:
    CHART_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    ensure_state_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def acquire_lock(lock_path: Path, reason: str) -> Any:
    ensure_state_dir()
    handle = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(reason) from exc
    return handle


def acquire_check_lock() -> Any:
    return acquire_lock(LOCK_FILE, "another check process is already running")


def acquire_event_check_lock() -> Any:
    return acquire_lock(EVENT_LOCK_FILE, "another event-check process is already running")


def load_alerts() -> list[dict[str, Any]]:
    payload = read_json(ALERTS_FILE, {"alerts": []})
    alerts = payload.get("alerts", []) if isinstance(payload, dict) else []
    return alerts if isinstance(alerts, list) else []


def save_alerts(alerts: list[dict[str, Any]]) -> None:
    write_json(ALERTS_FILE, {"alerts": alerts})


def load_status() -> dict[str, Any]:
    payload = read_json(STATUS_FILE, {"conditions": {}})
    conditions = payload.get("conditions", {}) if isinstance(payload, dict) else {}
    return conditions if isinstance(conditions, dict) else {}


def save_status(conditions: dict[str, Any]) -> None:
    write_json(STATUS_FILE, {"conditions": conditions})


def load_event_rules() -> list[dict[str, Any]]:
    payload = read_json(EVENT_RULES_FILE, {"rules": []})
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    return rules if isinstance(rules, list) else []


def save_event_rules(rules: list[dict[str, Any]]) -> None:
    write_json(EVENT_RULES_FILE, {"rules": rules})


def load_event_status() -> dict[str, Any]:
    payload = read_json(EVENT_STATUS_FILE, {"conditions": {}})
    conditions = payload.get("conditions", {}) if isinstance(payload, dict) else {}
    return conditions if isinstance(conditions, dict) else {}


def save_event_status(conditions: dict[str, Any]) -> None:
    write_json(EVENT_STATUS_FILE, {"conditions": conditions})


def http_get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    merged_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
    }
    if headers:
        merged_headers.update(headers)
    req = Request(url, headers=merged_headers)
    with urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        text = resp.read().decode("utf-8")
    return json.loads(text)


def http_get_text(url: str, headers: dict[str, str] | None = None) -> str:
    merged_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain,text/csv,*/*",
    }
    if headers:
        merged_headers.update(headers)
    req = Request(url, headers=merged_headers)
    with urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8", errors="replace")


def normalize_crypto_symbol(raw: str) -> tuple[str, str]:
    s = raw.strip().replace("/", "-")
    su = s.upper()
    if su in CRYPTO_ALIAS_TO_SYMBOL:
        base = CRYPTO_ALIAS_TO_SYMBOL[su]
    elif s in CRYPTO_ALIAS_TO_SYMBOL:
        base = CRYPTO_ALIAS_TO_SYMBOL[s]
    elif su.endswith("-USD"):
        base = su[:-4]
    elif su.endswith("USDT"):
        base = su[:-4]
    else:
        base = su
    base = CRYPTO_ALIAS_TO_SYMBOL.get(base, base)
    return base, f"{base}-USD"


def normalize_stock_symbol(raw: str) -> str:
    return raw.strip().upper()


def resolve_asset_type(symbol: str) -> str:
    s = symbol.strip().replace("/", "-").upper()
    if s.endswith("-USD"):
        base = s[:-4]
    elif s.endswith("USDT"):
        base = s[:-4]
    else:
        base = s
    if base in CRYPTO_ALIAS_TO_SYMBOL or base in COINGECKO_SYMBOL_TO_ID:
        return "crypto"
    return "stock"


def canonical_interval(interval: str) -> str:
    token = interval.strip().lower()
    return INTERVAL_ALIASES.get(token, token)


def interval_to_minutes(interval: str) -> int:
    return INTERVAL_MINUTES.get(canonical_interval(interval), 0)


def period_to_days(period: str) -> int:
    return PERIOD_DAYS.get(period, 0)


def validate_chart_period_interval(asset_type: str, period: str, interval: str) -> tuple[str, str, str]:
    period = period.strip()
    interval = canonical_interval(interval)

    if asset_type == "stock":
        if period not in STOCK_PERIOD_CHOICES:
            raise ValueError(f"stock --period must be one of: {', '.join(STOCK_PERIOD_CHOICES)}")
        if interval not in STOCK_INTERVAL_CHOICES:
            raise ValueError(f"stock --interval must be one of: {', '.join(STOCK_INTERVAL_CHOICES)}")
    else:
        if period not in CRYPTO_PERIOD_CHOICES:
            raise ValueError(f"crypto --period must be one of: {', '.join(CRYPTO_PERIOD_CHOICES)}")
        if interval not in CRYPTO_INTERVAL_CHOICES:
            raise ValueError(f"crypto --interval must be one of: {', '.join(CRYPTO_INTERVAL_CHOICES)}")
        minutes = interval_to_minutes(interval)
        if minutes and minutes < 15:
            raise ValueError("crypto minimum interval precision is 15m")

    # Yahoo intraday ranges are generally limited to ~60 days.
    note = ""
    days = period_to_days(period)
    minutes = interval_to_minutes(interval)
    if days > 60 and 0 < minutes < 1440:
        note = f"interval auto-adjusted from {interval} to 1d because intraday history >60d is limited on Yahoo"
        interval = "1d"

    return period, interval, note


# ----------------------- Quote providers -----------------------

def fetch_from_yahoo_chart(symbol: str) -> tuple[float, str, str]:
    encoded = quote_plus(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1d&interval=1m"
    payload = http_get_json(url)
    result = payload.get("chart", {}).get("result")
    if not result:
        raise RuntimeError("yahoo_chart returned no result")

    node = result[0]
    meta = node.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        closes = node.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [x for x in closes if isinstance(x, (int, float))]
        if closes:
            price = closes[-1]
    if not isinstance(price, (int, float)):
        raise RuntimeError("yahoo_chart missing regularMarketPrice")

    as_of = ts_to_iso(meta.get("regularMarketTime"))
    return float(price), as_of, "yahoo_chart"


def fetch_from_coingecko(base_symbol: str) -> tuple[float, str, str]:
    coin_id = COINGECKO_SYMBOL_TO_ID.get(base_symbol)
    if not coin_id:
        raise RuntimeError(f"coingecko unsupported symbol: {base_symbol}")
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={quote_plus(coin_id)}&vs_currencies=usd&include_last_updated_at=true"
    )
    payload = http_get_json(url)
    node = payload.get(coin_id, {})
    price = node.get("usd")
    if not isinstance(price, (int, float)):
        raise RuntimeError("coingecko missing usd price")
    as_of = ts_to_iso(node.get("last_updated_at"))
    return float(price), as_of, "coingecko"


def fetch_from_coinbase(base_symbol: str) -> tuple[float, str, str]:
    url = f"https://api.coinbase.com/v2/prices/{quote_plus(base_symbol)}-USD/spot"
    payload = http_get_json(url)
    amount = payload.get("data", {}).get("amount")
    try:
        price = float(amount)
    except Exception as exc:
        raise RuntimeError("coinbase missing amount") from exc
    return price, now_iso(), "coinbase"


def fetch_from_binance(base_symbol: str) -> tuple[float, str, str]:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={quote_plus(base_symbol)}USDT"
    payload = http_get_json(url)
    amount = payload.get("price")
    try:
        price = float(amount)
    except Exception as exc:
        raise RuntimeError("binance missing price") from exc
    return price, now_iso(), "binance"


def fetch_from_nasdaq(stock_symbol: str) -> tuple[float, str, str]:
    if not re.fullmatch(r"[A-Z.\-]{1,12}", stock_symbol):
        raise RuntimeError("nasdaq supports standard ticker formats only")

    url = f"https://api.nasdaq.com/api/quote/{quote_plus(stock_symbol)}/info?assetclass=stocks"
    payload = http_get_json(
        url,
        headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nasdaq.com/",
        },
    )
    primary = payload.get("data", {}).get("primaryData", {})
    last_sale_price = str(primary.get("lastSalePrice", ""))
    cleaned = re.sub(r"[^0-9.]", "", last_sale_price)
    if not cleaned:
        raise RuntimeError("nasdaq missing lastSalePrice")
    return float(cleaned), now_iso(), "nasdaq"


def to_stooq_symbol(stock_symbol: str) -> str:
    s = stock_symbol.strip().lower()
    if "." not in s and re.fullmatch(r"[a-z]{1,6}", s):
        return f"{s}.us"
    return s


def parse_stooq_timestamp(date_txt: str, time_txt: str) -> str:
    if len(date_txt) == 8 and len(time_txt) == 6 and date_txt.isdigit() and time_txt.isdigit():
        return (
            f"{date_txt[0:4]}-{date_txt[4:6]}-{date_txt[6:8]}"
            f"T{time_txt[0:2]}:{time_txt[2:4]}:{time_txt[4:6]}Z"
        )
    return now_iso()


def fetch_from_stooq(stock_symbol: str) -> tuple[float, str, str]:
    stooq_symbol = to_stooq_symbol(stock_symbol)
    url = f"https://stooq.com/q/l/?s={quote_plus(stooq_symbol)}&i=1"
    text = http_get_text(url)
    first_line = text.strip().splitlines()[0]
    row = next(csv.reader([first_line]))
    if len(row) < 7:
        raise RuntimeError("stooq invalid csv")
    close_txt = row[6]
    try:
        price = float(close_txt)
    except Exception as exc:
        raise RuntimeError("stooq missing close") from exc
    as_of = parse_stooq_timestamp(row[1], row[2]) if len(row) >= 3 else now_iso()
    return price, as_of, "stooq"


def fetch_price(asset_type: str, symbol: str) -> dict[str, Any]:
    errors: list[str] = []

    if asset_type == "crypto":
        base, quote_symbol = normalize_crypto_symbol(symbol)
        providers: list[tuple[str, Callable[[], tuple[float, str, str]]]] = [
            ("yahoo_chart", lambda: fetch_from_yahoo_chart(quote_symbol)),
            ("coingecko", lambda: fetch_from_coingecko(base)),
            ("coinbase", lambda: fetch_from_coinbase(base)),
            ("binance", lambda: fetch_from_binance(base)),
        ]
        resolved_symbol = quote_symbol
    else:
        resolved_symbol = normalize_stock_symbol(symbol)
        providers = [
            ("yahoo_chart", lambda: fetch_from_yahoo_chart(resolved_symbol)),
            ("nasdaq", lambda: fetch_from_nasdaq(resolved_symbol)),
            ("stooq", lambda: fetch_from_stooq(resolved_symbol)),
        ]

    for provider_name, provider in providers:
        try:
            price, as_of, source = provider()
            return {
                "asset_type": asset_type,
                "input_symbol": symbol,
                "symbol": resolved_symbol,
                "price": float(price),
                "source": source,
                "provider": provider_name,
                "as_of": as_of,
                "checked_at": now_iso(),
            }
        except Exception as exc:
            errors.append(f"{provider_name}: {exc}")

    raise RuntimeError("all providers failed: " + " | ".join(errors))


# ----------------------- OHLC providers -----------------------

def fetch_ohlcv_from_yahoo(symbol: str, period: str, interval: str) -> tuple[list[dict[str, Any]], str, str]:
    encoded_symbol = quote_plus(symbol)
    encoded_period = quote_plus(period)
    encoded_interval = quote_plus(interval)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?range={encoded_period}&interval={encoded_interval}&includePrePost=false&events=div%2Csplits"
    )
    payload = http_get_json(url)
    result = payload.get("chart", {}).get("result")
    if not result:
        error_node = payload.get("chart", {}).get("error")
        raise RuntimeError(f"yahoo chart no result: {error_node}")

    node = result[0]
    timestamps = node.get("timestamp") or []
    quote = (node.get("indicators") or {}).get("quote") or []
    if not timestamps or not quote:
        raise RuntimeError("yahoo chart missing timestamps/quote")

    q0 = quote[0]
    opens = q0.get("open") or []
    highs = q0.get("high") or []
    lows = q0.get("low") or []
    closes = q0.get("close") or []
    volumes = q0.get("volume") or []

    candles: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        if idx >= len(opens) or idx >= len(highs) or idx >= len(lows) or idx >= len(closes):
            continue

        o = opens[idx]
        h = highs[idx]
        l = lows[idx]
        c = closes[idx]
        if not all(isinstance(v, (int, float)) for v in [o, h, l, c]):
            continue

        v = volumes[idx] if idx < len(volumes) and isinstance(volumes[idx], (int, float)) else 0.0
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        candles.append(
            {
                "dt": dt,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
            }
        )

    if not candles:
        raise RuntimeError("yahoo chart returned no valid candles")

    as_of = candles[-1]["dt"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return candles, as_of, "yahoo_chart"


def fetch_ohlcv_from_binance(base_symbol: str, period: str, interval: str) -> tuple[list[dict[str, Any]], str, str]:
    mapping = {
        "15m": "15m",
        "30m": "30m",
        "60m": "1h",
        "90m": "2h",
        "1d": "1d",
        "1wk": "1w",
    }
    if interval not in mapping:
        raise RuntimeError(f"binance unsupported interval: {interval}")

    binance_interval = mapping[interval]
    days = max(period_to_days(period), 1)
    step_minutes = max(interval_to_minutes(interval), 1)
    raw_limit = int(math.ceil((days * 24 * 60) / step_minutes)) + 5
    limit = min(max(raw_limit, 50), 1000)

    symbol = f"{base_symbol}USDT"
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={quote_plus(symbol)}&interval={quote_plus(binance_interval)}&limit={limit}"
    )
    payload = http_get_json(url)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("binance klines returned no rows")

    candles: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            dt = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc)
            o = float(row[1])
            h = float(row[2])
            l = float(row[3])
            c = float(row[4])
            v = float(row[5])
        except Exception:
            continue
        candles.append(
            {
                "dt": dt,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )

    if not candles:
        raise RuntimeError("binance klines returned no valid candles")

    as_of = candles[-1]["dt"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return candles, as_of, "binance_klines"


def aggregate_weekly(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for candle in candles:
        dt = candle["dt"]
        year, week, _ = dt.isocalendar()
        key = (int(year), int(week))

        bucket = grouped.get(key)
        if bucket is None:
            grouped[key] = {
                "dt": dt,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
            continue

        bucket["dt"] = dt
        bucket["high"] = max(bucket["high"], candle["high"])
        bucket["low"] = min(bucket["low"], candle["low"])
        bucket["close"] = candle["close"]
        bucket["volume"] += candle["volume"]

    out = sorted(grouped.values(), key=lambda x: x["dt"])
    return out


def fetch_ohlcv_from_stooq(stock_symbol: str, period: str, interval: str) -> tuple[list[dict[str, Any]], str, str]:
    if interval not in ("1d", "1wk"):
        raise RuntimeError("stooq history fallback supports only 1d or 1wk")

    stooq_symbol = to_stooq_symbol(stock_symbol)
    url = f"https://stooq.com/q/d/l/?s={quote_plus(stooq_symbol)}&i=d"
    text = http_get_text(url)

    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise RuntimeError("stooq history returned empty csv")

    days = max(period_to_days(period), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days + 7)

    candles: list[dict[str, Any]] = []
    for row in rows:
        date_txt = str(row.get("Date", "")).strip()
        if not date_txt:
            continue
        try:
            dt = datetime.strptime(date_txt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            o = float(row.get("Open", "nan"))
            h = float(row.get("High", "nan"))
            l = float(row.get("Low", "nan"))
            c = float(row.get("Close", "nan"))
            v_raw = row.get("Volume", "0")
            v = float(v_raw) if v_raw not in ("", "-") else 0.0
        except Exception:
            continue

        if dt < cutoff:
            continue
        if any(math.isnan(x) for x in [o, h, l, c]):
            continue

        candles.append(
            {
                "dt": dt,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )

    if not candles:
        raise RuntimeError("stooq history returned no candles in selected period")

    candles.sort(key=lambda x: x["dt"])
    if interval == "1wk":
        candles = aggregate_weekly(candles)

    as_of = candles[-1]["dt"].replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return candles, as_of, "stooq_history"


def fetch_chart_data(asset_type: str, symbol: str, period: str, interval: str) -> dict[str, Any]:
    errors: list[str] = []

    if asset_type == "crypto":
        base, resolved_symbol = normalize_crypto_symbol(symbol)
        providers: list[tuple[str, Callable[[], tuple[list[dict[str, Any]], str, str]]]] = [
            ("yahoo_chart", lambda: fetch_ohlcv_from_yahoo(resolved_symbol, period, interval)),
            ("binance_klines", lambda: fetch_ohlcv_from_binance(base, period, interval)),
        ]
    else:
        resolved_symbol = normalize_stock_symbol(symbol)
        providers = [("yahoo_chart", lambda: fetch_ohlcv_from_yahoo(resolved_symbol, period, interval))]
        if interval in ("1d", "1wk"):
            providers.append(("stooq_history", lambda: fetch_ohlcv_from_stooq(resolved_symbol, period, interval)))

    for provider_name, provider in providers:
        try:
            candles, as_of, source = provider()
            return {
                "asset_type": asset_type,
                "input_symbol": symbol,
                "symbol": resolved_symbol,
                "period": period,
                "interval": interval,
                "source": source,
                "provider": provider_name,
                "as_of": as_of,
                "checked_at": now_iso(),
                "candles": candles,
            }
        except Exception as exc:
            errors.append(f"{provider_name}: {exc}")

    raise RuntimeError("all chart providers failed: " + " | ".join(errors))


# ----------------------- Indicator math -----------------------

def rolling_mean(values: list[float], window: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if window <= 0:
        return out

    acc = 0.0
    for idx, value in enumerate(values):
        acc += value
        if idx >= window:
            acc -= values[idx - window]
        if idx >= window - 1:
            out[idx] = acc / window
    return out


def rolling_std(values: list[float], window: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if window <= 1:
        return out

    for idx in range(window - 1, n):
        win = values[idx - window + 1 : idx + 1]
        mean = sum(win) / window
        var = sum((v - mean) ** 2 for v in win) / window
        out[idx] = math.sqrt(var)
    return out


def ema_series(values: list[float], span: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if span <= 0:
        return out

    k = 2.0 / (span + 1.0)
    ema_val: float | None = None
    for idx, value in enumerate(values):
        if ema_val is None:
            ema_val = value
        else:
            ema_val = value * k + ema_val * (1.0 - k)
        if idx >= span - 1:
            out[idx] = ema_val
    return out


def macd_series_custom(
    closes: list[float], fast_span: int = 12, slow_span: int = 26, signal_span: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    if fast_span <= 0 or slow_span <= 0 or signal_span <= 0:
        raise ValueError("MACD spans must be positive integers")
    if fast_span >= slow_span:
        raise ValueError("MACD fast span must be less than slow span")

    ema_fast = ema_series(closes, fast_span)
    ema_slow = ema_series(closes, slow_span)

    macd_line: list[float | None] = [None] * len(closes)
    macd_compact: list[float] = []
    idx_map: list[int] = []

    for idx, (e_fast, e_slow) in enumerate(zip(ema_fast, ema_slow)):
        if e_fast is None or e_slow is None:
            continue
        value = e_fast - e_slow
        macd_line[idx] = value
        macd_compact.append(value)
        idx_map.append(idx)

    signal_compact = ema_series(macd_compact, signal_span)
    signal_line: list[float | None] = [None] * len(closes)
    hist_line: list[float | None] = [None] * len(closes)

    for compact_idx, real_idx in enumerate(idx_map):
        signal = signal_compact[compact_idx]
        if signal is None:
            continue
        macd_value = macd_line[real_idx]
        if macd_value is None:
            continue
        signal_line[real_idx] = signal
        hist_line[real_idx] = macd_value - signal

    return macd_line, signal_line, hist_line


def macd_series(closes: list[float]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    return macd_series_custom(closes, 12, 26, 9)


def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out

    gains = [0.0] * n
    losses = [0.0] * n
    for idx in range(1, n):
        diff = closes[idx] - closes[idx - 1]
        gains[idx] = max(diff, 0.0)
        losses[idx] = max(-diff, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period

    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))

    for idx in range(period + 1, n):
        avg_gain = ((avg_gain * (period - 1)) + gains[idx]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[idx]) / period

        if avg_loss == 0:
            out[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[idx] = 100.0 - (100.0 / (1.0 + rs))

    return out


def fibonacci_levels(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    hi = max(highs)
    lo = min(lows)
    diff = hi - lo
    if diff <= 0:
        return {"trend": "flat", "levels": []}

    uptrend = closes[-1] >= closes[0]
    levels: list[dict[str, float]] = []
    if uptrend:
        for ratio in FIB_RATIOS:
            levels.append({"ratio": ratio, "price": hi - diff * ratio})
        trend = "up"
    else:
        for ratio in FIB_RATIOS:
            levels.append({"ratio": ratio, "price": lo + diff * ratio})
        trend = "down"

    return {
        "trend": trend,
        "high": hi,
        "low": lo,
        "levels": levels,
    }


def series_to_plot_array(series: list[float | None]) -> list[float]:
    out: list[float] = []
    for value in series:
        if value is None:
            out.append(float("nan"))
        else:
            out.append(float(value))
    return out


def last_valid(series: list[float | None]) -> float | None:
    for value in reversed(series):
        if value is not None:
            return float(value)
    return None


def compute_indicators(candles: list[dict[str, Any]], flags: dict[str, bool]) -> dict[str, Any]:
    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]

    out: dict[str, Any] = {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }

    if flags.get("sma"):
        out["sma20"] = rolling_mean(closes, 20)
        out["sma50"] = rolling_mean(closes, 50)

    if flags.get("ema"):
        out["ema12"] = ema_series(closes, 12)
        out["ema26"] = ema_series(closes, 26)

    if flags.get("macd"):
        macd_line, signal_line, hist_line = macd_series(closes)
        out["macd_line"] = macd_line
        out["macd_signal"] = signal_line
        out["macd_hist"] = hist_line

    if flags.get("rsi"):
        out["rsi14"] = rsi_series(closes, 14)

    if flags.get("bb"):
        bb_mid = rolling_mean(closes, 20)
        bb_std = rolling_std(closes, 20)
        bb_upper: list[float | None] = [None] * len(closes)
        bb_lower: list[float | None] = [None] * len(closes)
        for idx, (mid, std) in enumerate(zip(bb_mid, bb_std)):
            if mid is None or std is None:
                continue
            bb_upper[idx] = mid + 2.0 * std
            bb_lower[idx] = mid - 2.0 * std
        out["bb_mid"] = bb_mid
        out["bb_upper"] = bb_upper
        out["bb_lower"] = bb_lower

    if flags.get("vol_ma"):
        out["vol_ma20"] = rolling_mean(volumes, 20)

    if flags.get("fib"):
        out["fib"] = fibonacci_levels(highs, lows, closes)

    return out


def nearest_fib_levels(fib: dict[str, Any], price: float) -> tuple[dict[str, float] | None, dict[str, float] | None]:
    levels = fib.get("levels") or []
    below = None
    above = None
    for level in levels:
        value = float(level["price"])
        if value <= price:
            if below is None or value > float(below["price"]):
                below = level
        if value >= price:
            if above is None or value < float(above["price"]):
                above = level
    return below, above


# ----------------------- Plotting -----------------------

def default_chart_path(symbol: str, period: str, interval: str, chart_type: str) -> Path:
    ensure_chart_dir()
    safe_symbol = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_symbol}_{period}_{interval}_{chart_type}_{stamp}.png"
    return CHART_DIR / filename


def render_chart_png(
    chart_payload: dict[str, Any],
    indicators: dict[str, Any],
    chart_type: str,
    show_volume: bool,
    show_rsi: bool,
    show_macd: bool,
    out_path: Path,
    width: float,
    height: float,
    dpi: int,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as exc:
        raise RuntimeError(
            "matplotlib is required for chart generation. Install via a virtualenv, e.g. "
            "python3 -m venv .venv && .venv/bin/pip install matplotlib"
        ) from exc

    candles = chart_payload["candles"]
    dates = [c["dt"].astimezone(timezone.utc).replace(tzinfo=None) for c in candles]
    x = [mdates.date2num(dt) for dt in dates]

    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    panel_names = ["price"]
    if show_volume:
        panel_names.append("volume")
    if show_rsi and "rsi14" in indicators:
        panel_names.append("rsi")
    if show_macd and "macd_line" in indicators:
        panel_names.append("macd")

    ratio_map = {
        "price": 5,
        "volume": 2,
        "rsi": 2,
        "macd": 2,
    }
    ratios = [ratio_map[name] for name in panel_names]

    fig, axes = plt.subplots(
        nrows=len(panel_names),
        ncols=1,
        figsize=(width, height),
        sharex=True,
        gridspec_kw={"height_ratios": ratios},
    )
    if len(panel_names) == 1:
        axes = [axes]

    ax_by_name = {name: axes[idx] for idx, name in enumerate(panel_names)}

    diffs = [x[idx] - x[idx - 1] for idx in range(1, len(x)) if x[idx] - x[idx - 1] > 0]
    if diffs:
        step = sorted(diffs)[len(diffs) // 2]
        width_candle = max(step * 0.6, 0.0006)
    else:
        width_candle = 0.02

    up_color = "#16a34a"
    down_color = "#dc2626"

    ax_price = ax_by_name["price"]
    if chart_type == "candlestick":
        for idx, xv in enumerate(x):
            o = opens[idx]
            h = highs[idx]
            l = lows[idx]
            c = closes[idx]
            color = up_color if c >= o else down_color

            ax_price.plot([xv, xv], [l, h], color=color, linewidth=0.9, alpha=0.9)

            body_bottom = min(o, c)
            body_height = abs(c - o)
            if body_height == 0:
                body_height = max((h - l) * 0.02, 1e-6)
            rect = Rectangle(
                (xv - width_candle / 2.0, body_bottom),
                width_candle,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.8,
                alpha=0.85,
            )
            ax_price.add_patch(rect)
    else:
        ax_price.plot(x, closes, color="#2563eb", linewidth=1.5, label="Close")

    if "sma20" in indicators:
        ax_price.plot(x, series_to_plot_array(indicators["sma20"]), linewidth=1.1, color="#f59e0b", label="SMA20")
    if "sma50" in indicators:
        ax_price.plot(x, series_to_plot_array(indicators["sma50"]), linewidth=1.1, color="#b45309", label="SMA50")

    if "ema12" in indicators:
        ax_price.plot(x, series_to_plot_array(indicators["ema12"]), linewidth=1.1, color="#0ea5e9", label="EMA12")
    if "ema26" in indicators:
        ax_price.plot(x, series_to_plot_array(indicators["ema26"]), linewidth=1.1, color="#6366f1", label="EMA26")

    if "bb_upper" in indicators and "bb_lower" in indicators and "bb_mid" in indicators:
        bb_upper = series_to_plot_array(indicators["bb_upper"])
        bb_lower = series_to_plot_array(indicators["bb_lower"])
        bb_mid = series_to_plot_array(indicators["bb_mid"])
        ax_price.plot(x, bb_upper, linewidth=1.0, color="#7c3aed", alpha=0.9, label="BB Upper")
        ax_price.plot(x, bb_lower, linewidth=1.0, color="#7c3aed", alpha=0.9, label="BB Lower")
        ax_price.plot(x, bb_mid, linewidth=0.9, color="#a78bfa", alpha=0.9, label="BB Mid")
        ax_price.fill_between(x, bb_lower, bb_upper, color="#c4b5fd", alpha=0.08)

    fib = indicators.get("fib")
    if fib and fib.get("levels"):
        for level in fib["levels"]:
            ratio = float(level["ratio"])
            value = float(level["price"])
            ax_price.axhline(value, color="#64748b", linewidth=0.8, alpha=0.35)
            ax_price.text(
                x[-1] + width_candle * 0.4,
                value,
                f"Fib {ratio:.3f}",
                fontsize=7,
                color="#475569",
                va="center",
            )

    ax_price.grid(True, alpha=0.15)
    ax_price.set_ylabel("Price (USD)")
    handles, labels = ax_price.get_legend_handles_labels()
    if handles:
        ax_price.legend(loc="upper left", fontsize=8, ncol=2)

    if "volume" in ax_by_name:
        ax_volume = ax_by_name["volume"]
        bar_colors = [up_color if closes[idx] >= opens[idx] else down_color for idx in range(len(closes))]
        ax_volume.bar(x, volumes, width=width_candle, color=bar_colors, alpha=0.45)
        if "vol_ma20" in indicators:
            ax_volume.plot(x, series_to_plot_array(indicators["vol_ma20"]), color="#0f766e", linewidth=1.2, label="Vol MA20")
            ax_volume.legend(loc="upper left", fontsize=8)
        ax_volume.set_ylabel("Volume")
        ax_volume.grid(True, alpha=0.15)

    if "rsi" in ax_by_name and "rsi14" in indicators:
        ax_rsi = ax_by_name["rsi"]
        ax_rsi.plot(x, series_to_plot_array(indicators["rsi14"]), color="#0891b2", linewidth=1.2, label="RSI14")
        ax_rsi.axhline(70, color="#dc2626", linewidth=0.9, linestyle="--", alpha=0.8)
        ax_rsi.axhline(30, color="#16a34a", linewidth=0.9, linestyle="--", alpha=0.8)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI")
        ax_rsi.grid(True, alpha=0.15)
        ax_rsi.legend(loc="upper left", fontsize=8)

    if "macd" in ax_by_name and "macd_line" in indicators and "macd_signal" in indicators and "macd_hist" in indicators:
        ax_macd = ax_by_name["macd"]
        macd_line = indicators["macd_line"]
        macd_signal = indicators["macd_signal"]
        macd_hist = indicators["macd_hist"]

        hist_vals = series_to_plot_array(macd_hist)
        hist_colors = ["#16a34a" if (not math.isnan(v) and v >= 0) else "#dc2626" for v in hist_vals]
        ax_macd.bar(x, hist_vals, width=width_candle, color=hist_colors, alpha=0.4, label="MACD Hist")
        ax_macd.plot(x, series_to_plot_array(macd_line), color="#1d4ed8", linewidth=1.1, label="MACD")
        ax_macd.plot(x, series_to_plot_array(macd_signal), color="#f97316", linewidth=1.1, label="Signal")
        ax_macd.axhline(0, color="#334155", linewidth=0.8, alpha=0.7)
        ax_macd.set_ylabel("MACD")
        ax_macd.grid(True, alpha=0.15)
        ax_macd.legend(loc="upper left", fontsize=8)

    minutes = interval_to_minutes(chart_payload["interval"])
    if 0 < minutes < 1440:
        # For intraday charts, prefer explicit hour-based ticks to avoid noisy auto-locator behavior.
        tick_hours = max(1, int((period_to_days(chart_payload["period"]) * 24) / 8))
        locator = mdates.HourLocator(interval=tick_hours)
        formatter = mdates.DateFormatter("%m-%d %H:%M")
    else:
        locator = mdates.AutoDateLocator(minticks=6, maxticks=10)
        formatter = mdates.DateFormatter("%Y-%m-%d")
    axes[-1].xaxis.set_major_locator(locator)
    axes[-1].xaxis.set_major_formatter(formatter)
    for tick in axes[-1].get_xticklabels():
        tick.set_rotation(30)
        tick.set_ha("right")

    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
    change_pct = ((last_close - prev_close) / prev_close * 100.0) if prev_close else 0.0

    fig.suptitle(
        f"{chart_payload['symbol']}  {chart_payload['asset_type']}  {chart_type}"
        f"  range={chart_payload['period']} interval={chart_payload['interval']}"
        f"  close={last_close:.4f} ({change_pct:+.2f}%)  source={chart_payload['source']}",
        fontsize=12,
    )
    fig.tight_layout(rect=[0.01, 0.02, 0.99, 0.95])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


# ----------------------- Alerts + notification -----------------------

def evaluate_condition(price: float, direction: str, threshold: float) -> bool:
    if direction == "above":
        return price > threshold
    return price < threshold


def format_alert_message(alert: dict[str, Any], quote: dict[str, Any]) -> str:
    direction = alert["direction"]
    symbol = quote["symbol"]
    relation = ">" if direction == "above" else "<"
    return (
        f"[PRICE ALERT] {symbol} {quote['price']:.6f} USD {relation} {alert['threshold']:.6f} USD "
        f"(source={quote['source']}, checked={quote['checked_at']}, as_of={quote['as_of']}, id={alert['id']})"
    )


def resolve_openclaw_bin() -> str:
    env_bin = (os.environ.get("OPENCLAW_BIN") or "").strip()
    if env_bin:
        return env_bin

    detected = shutil.which("openclaw")
    if detected:
        return detected

    candidates = [
        Path("/usr/local/bin/openclaw"),
        Path("/usr/bin/openclaw"),
        Path.home() / ".nvm/versions/node/v25.6.0/bin/openclaw",
    ]

    nvm_root = Path.home() / ".nvm/versions/node"
    if nvm_root.exists():
        for candidate in sorted(nvm_root.glob("v*/bin/openclaw"), reverse=True):
            candidates.insert(0, candidate)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return "openclaw"


def send_notification(alert: dict[str, Any], message: str, dry_run: bool = False, quiet: bool = False) -> bool:
    channel = (alert.get("channel") or "").strip()
    target = (alert.get("target") or "").strip()

    if not channel or not target:
        if not quiet:
            print(f"LOCAL_ALERT {alert['id']}: {message}")
        return True

    openclaw_bin = resolve_openclaw_bin()
    cmd = [
        openclaw_bin,
        "message",
        "send",
        "--channel",
        channel,
        "--target",
        target,
        "--message",
        message,
    ]

    if dry_run:
        if not quiet:
            print("DRY_RUN send:", " ".join(shlex.quote(part) for part in cmd))
        return True

    run_env = os.environ.copy()
    try:
        openclaw_path = Path(openclaw_bin)
        if openclaw_path.is_absolute():
            node_bin_dir = str(openclaw_path.parent)
            run_env["PATH"] = node_bin_dir + ":" + run_env.get("PATH", "/usr/bin:/bin")
    except Exception:
        pass

    proc = subprocess.run(cmd, capture_output=True, text=True, env=run_env)
    if proc.returncode == 0:
        if not quiet:
            print(f"DELIVERED {alert['id']} -> {channel}:{target}")
        return True

    if not quiet:
        print(f"DELIVERY_FAILED {alert['id']} rc={proc.returncode}")
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        if stderr:
            print("stderr:", stderr)
        if stdout:
            print("stdout:", stdout)
    return False


def send_media_notification(channel: str, target: str, message: str, media_path: Path, dry_run: bool = False) -> bool:
    openclaw_bin = resolve_openclaw_bin()
    cmd = [
        openclaw_bin,
        "message",
        "send",
        "--channel",
        channel,
        "--target",
        target,
        "--message",
        message,
        "--media",
        str(media_path),
    ]
    if dry_run:
        print("DRY_RUN send:", " ".join(shlex.quote(part) for part in cmd))
        return True

    run_env = os.environ.copy()
    try:
        openclaw_path = Path(openclaw_bin)
        if openclaw_path.is_absolute():
            node_bin_dir = str(openclaw_path.parent)
            run_env["PATH"] = node_bin_dir + ":" + run_env.get("PATH", "/usr/bin:/bin")
    except Exception:
        pass

    proc = subprocess.run(cmd, capture_output=True, text=True, env=run_env)
    if proc.returncode == 0:
        print(f"DELIVERED media -> {channel}:{target}")
        return True

    print(f"DELIVERY_FAILED media rc={proc.returncode}")
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    if stderr:
        print("stderr:", stderr)
    if stdout:
        print("stdout:", stdout)
    return False


# ----------------------- Cron helpers -----------------------

def read_crontab_lines() -> list[str]:
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or "") + "\n" + (proc.stdout or "")
        if "no crontab" in msg.lower():
            return []
        raise RuntimeError(f"failed to read crontab: {msg.strip()}")
    return proc.stdout.splitlines()


def write_crontab_lines(lines: list[str]) -> None:
    ensure_state_dir()
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", prefix="oc-alert-cron-", suffix=".tmp") as tmp:
        content = "\n".join(lines).rstrip() + "\n"
        tmp.write(content)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(["crontab", tmp_path], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "failed to install crontab").strip())
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def strip_managed_cron_block(lines: list[str]) -> tuple[list[str], bool]:
    out: list[str] = []
    inside = False
    removed = False
    for line in lines:
        stripped = line.strip()
        if stripped == CRON_BLOCK_START:
            inside = True
            removed = True
            continue
        if stripped == CRON_BLOCK_END:
            inside = False
            continue
        if not inside:
            out.append(line)
    return out, removed


def build_cron_schedule(minutes: int | None, cron_expr: str | None) -> str:
    if cron_expr:
        return cron_expr.strip()
    if minutes is None:
        return "*/5 * * * *"
    if minutes < 1 or minutes > 59:
        raise ValueError("--minutes must be in range 1..59")
    if minutes == 1:
        return "* * * * *"
    return f"*/{minutes} * * * *"


# ----------------------- Report helpers -----------------------

def build_indicator_summary(chart_payload: dict[str, Any], indicators: dict[str, Any]) -> list[str]:
    closes = indicators["closes"]
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
    change_pct = ((last_close - prev_close) / prev_close * 100.0) if prev_close else 0.0

    lines = [
        f"Symbol: {chart_payload['symbol']} ({chart_payload['asset_type']})",
        f"Range/Interval: {chart_payload['period']} / {chart_payload['interval']}",
        f"Last Close: {last_close:.6f} USD ({change_pct:+.2f}%)",
        f"Source: {chart_payload['source']} (as_of={chart_payload['as_of']})",
    ]

    sma20 = last_valid(indicators.get("sma20", []))
    sma50 = last_valid(indicators.get("sma50", []))
    if sma20 is not None or sma50 is not None:
        lines.append(f"SMA: 20={sma20:.6f} 50={sma50:.6f}" if sma20 is not None and sma50 is not None else "SMA: partial")

    ema12 = last_valid(indicators.get("ema12", []))
    ema26 = last_valid(indicators.get("ema26", []))
    if ema12 is not None or ema26 is not None:
        lines.append(f"EMA: 12={ema12:.6f} 26={ema26:.6f}" if ema12 is not None and ema26 is not None else "EMA: partial")

    macd_val = last_valid(indicators.get("macd_line", []))
    macd_sig = last_valid(indicators.get("macd_signal", []))
    macd_hist = last_valid(indicators.get("macd_hist", []))
    if macd_val is not None and macd_sig is not None and macd_hist is not None:
        lines.append(f"MACD: line={macd_val:.6f} signal={macd_sig:.6f} hist={macd_hist:.6f}")

    rsi_val = last_valid(indicators.get("rsi14", []))
    if rsi_val is not None:
        zone = "neutral"
        if rsi_val >= 70:
            zone = "overbought"
        elif rsi_val <= 30:
            zone = "oversold"
        lines.append(f"RSI14: {rsi_val:.2f} ({zone})")

    bb_upper = last_valid(indicators.get("bb_upper", []))
    bb_mid = last_valid(indicators.get("bb_mid", []))
    bb_lower = last_valid(indicators.get("bb_lower", []))
    if bb_upper is not None and bb_mid is not None and bb_lower is not None:
        position = "inside"
        if last_close > bb_upper:
            position = "above-upper"
        elif last_close < bb_lower:
            position = "below-lower"
        lines.append(f"Bollinger(20,2): upper={bb_upper:.6f} mid={bb_mid:.6f} lower={bb_lower:.6f} ({position})")

    fib = indicators.get("fib")
    if fib and fib.get("levels"):
        below, above = nearest_fib_levels(fib, last_close)
        trend = fib.get("trend", "unknown")
        low_txt = f"{below['ratio']:.3f}@{below['price']:.6f}" if below else "n/a"
        high_txt = f"{above['ratio']:.3f}@{above['price']:.6f}" if above else "n/a"
        lines.append(f"Fibonacci ({trend}): nearest_below={low_txt} nearest_above={high_txt}")

    return lines


# ----------------------- Event helpers -----------------------

def resolve_event_defaults(asset_type: str, period: str, interval: str) -> tuple[str, str]:
    out_period = period.strip() if period else ""
    out_interval = interval.strip() if interval else ""

    if asset_type == "stock":
        if not out_period:
            out_period = "3mo"
        if not out_interval:
            out_interval = "1d"
    else:
        if not out_period:
            out_period = "5d"
        if not out_interval:
            out_interval = "15m"

    return out_period, out_interval


def normalize_event_symbol(asset_type: str, raw_symbol: str) -> tuple[str, str]:
    if asset_type == "crypto":
        base, quote_symbol = normalize_crypto_symbol(raw_symbol)
        return base, quote_symbol
    symbol = normalize_stock_symbol(raw_symbol)
    return symbol, symbol


def resolve_macd_profile_params(
    asset_type: str,
    macd_profile: str,
    macd_fast: int | None,
    macd_slow: int | None,
    macd_signal: int | None,
) -> dict[str, Any]:
    profile = macd_profile.strip().lower() if macd_profile else "auto"
    if profile == "auto":
        profile = "fast_crypto" if asset_type == "crypto" else "standard"

    if profile == "custom":
        if macd_fast is None or macd_slow is None or macd_signal is None:
            raise ValueError("--macd-fast/--macd-slow/--macd-signal are required when --macd-profile custom")
        fast, slow, signal = int(macd_fast), int(macd_slow), int(macd_signal)
    else:
        tpl = MACD_PROFILES.get(profile)
        if tpl is None:
            raise ValueError(f"unknown macd profile: {profile}")
        fast, slow, signal = tpl

    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD spans must be positive integers")
    if fast >= slow:
        raise ValueError("MACD fast span must be less than MACD slow span")

    return {
        "macd_profile": profile,
        "macd_fast": int(fast),
        "macd_slow": int(slow),
        "macd_signal": int(signal),
    }


def extract_macd_params(rule: dict[str, Any]) -> tuple[int, int, int, str]:
    params = rule.get("params") if isinstance(rule.get("params"), dict) else {}
    profile = str(params.get("macd_profile", "standard"))
    try:
        fast = int(params.get("macd_fast", 12))
        slow = int(params.get("macd_slow", 26))
        signal = int(params.get("macd_signal", 9))
    except Exception as exc:
        raise RuntimeError("invalid stored MACD params for event rule") from exc
    if fast <= 0 or slow <= 0 or signal <= 0 or fast >= slow:
        raise RuntimeError("invalid stored MACD params for event rule")
    return fast, slow, signal, profile


def obv_series(closes: list[float], volumes: list[float]) -> list[float]:
    if not closes:
        return []
    out = [0.0]
    for idx in range(1, len(closes)):
        prev = out[-1]
        if closes[idx] > closes[idx - 1]:
            out.append(prev + volumes[idx])
        elif closes[idx] < closes[idx - 1]:
            out.append(prev - volumes[idx])
        else:
            out.append(prev)
    return out


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("1", "true", "yes", "y", "on"):
            return True
        if token in ("0", "false", "no", "n", "off", ""):
            return False
    return default


def parse_int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    if min_value is not None and out < min_value:
        out = min_value
    if max_value is not None and out > max_value:
        out = max_value
    return out


def parse_float(value: Any, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        out = float(value)
    except Exception:
        out = float(default)
    if min_value is not None and out < min_value:
        out = min_value
    if max_value is not None and out > max_value:
        out = max_value
    return out


def normalize_event_params_for_compare(event_type: str, raw_params: Any) -> dict[str, Any]:
    params = raw_params if isinstance(raw_params, dict) else {}
    out: dict[str, Any] = {}

    severity = str(params.get("severity", "auto")).strip().lower()
    if severity not in EVENT_SEVERITY_CHOICES:
        severity = "auto"
    out["severity"] = severity

    attach_chart = parse_bool(params.get("attach_chart", False), default=False)
    out["attach_chart"] = attach_chart
    if attach_chart:
        chart_type = str(params.get("snapshot_chart_type", "candlestick")).strip().lower()
        if chart_type not in ("candlestick", "line"):
            chart_type = "candlestick"
        out["snapshot_chart_type"] = chart_type
        out["snapshot_width"] = parse_float(params.get("snapshot_width", 14.0), 14.0, min_value=6.0)
        out["snapshot_height"] = parse_float(params.get("snapshot_height", 8.0), 8.0, min_value=4.0)
        out["snapshot_dpi"] = parse_int(params.get("snapshot_dpi", 150), 150, min_value=80, max_value=400)

    if event_type in MACD_EVENT_WITH_PROFILE_TYPES:
        try:
            fast = parse_int(params.get("macd_fast", 12), 12, min_value=1)
            slow = parse_int(params.get("macd_slow", 26), 26, min_value=2)
            signal = parse_int(params.get("macd_signal", 9), 9, min_value=1)
            if fast >= slow:
                fast, slow, signal = 12, 26, 9
            profile = str(params.get("macd_profile", "standard")).strip().lower() or "standard"
            if profile not in ("standard", "fast_crypto", "slow_trend", "user_7_10_30", "custom"):
                profile = "standard"
        except Exception:
            fast, slow, signal, profile = 12, 26, 9, "standard"
        out["macd_profile"] = profile
        out["macd_fast"] = int(fast)
        out["macd_slow"] = int(slow)
        out["macd_signal"] = int(signal)

    if event_type in MACD_HIST_EXPAND_EVENT_TYPES:
        out["hist_expand_bars"] = parse_int(params.get("hist_expand_bars", 3), 3, min_value=2)

    if event_type in (
        "breakout_n_bar_high",
        "breakdown_n_bar_low",
        "donchian_breakout_up",
        "donchian_breakout_down",
        "bb_squeeze_breakout_up",
        "bb_squeeze_breakout_down",
        "volume_spike_up",
        "volume_spike_down",
        "volume_dry_up",
    ):
        out["lookback_bars"] = parse_int(params.get("lookback_bars", 20), 20, min_value=2, max_value=300)

    if event_type in ("bb_squeeze_start", "bb_squeeze_breakout_up", "bb_squeeze_breakout_down"):
        out["bb_width_threshold"] = parse_float(params.get("bb_width_threshold", 0.06), 0.06, min_value=0.005, max_value=1.0)

    if event_type in ("volume_spike_up", "volume_spike_down"):
        out["volume_spike_multiplier"] = parse_float(
            params.get("volume_spike_multiplier", 1.8), 1.8, min_value=1.0, max_value=20.0
        )

    if event_type == "volume_dry_up":
        out["volume_dry_threshold"] = parse_float(
            params.get("volume_dry_threshold", 0.6), 0.6, min_value=0.05, max_value=1.0
        )

    if event_type in BREAKOUT_EVENT_TYPES:
        out["pivot_left"] = parse_int(params.get("pivot_left", 3), 3, min_value=1, max_value=20)
        out["pivot_right"] = parse_int(params.get("pivot_right", 3), 3, min_value=1, max_value=20)

    if event_type in FIB_EVENT_TYPES:
        out["fib_anchor_bars"] = parse_int(params.get("fib_anchor_bars", 120), 120, min_value=20, max_value=1000)
        out["fib_touch_tolerance"] = parse_float(
            params.get("fib_touch_tolerance", 0.002), 0.002, min_value=0.0, max_value=0.05
        )

    if event_type in DIVERGENCE_EVENT_TYPES:
        out["pivot_left"] = parse_int(params.get("pivot_left", 3), 3, min_value=1, max_value=20)
        out["pivot_right"] = parse_int(params.get("pivot_right", 3), 3, min_value=1, max_value=20)
        out["min_pivot_gap"] = parse_int(params.get("min_pivot_gap", 5), 5, min_value=1, max_value=200)
        out["max_pivot_gap"] = parse_int(params.get("max_pivot_gap", 120), 120, min_value=2, max_value=800)
        if out["max_pivot_gap"] < out["min_pivot_gap"]:
            out["max_pivot_gap"] = out["min_pivot_gap"]
        out["min_price_delta_pct"] = parse_float(
            params.get("min_price_delta_pct", 0.3), 0.3, min_value=0.0, max_value=100.0
        )
        out["min_indicator_delta"] = parse_float(
            params.get("min_indicator_delta", 0.1), 0.1, min_value=0.0, max_value=1000000.0
        )
        out["dedup_window_bars"] = parse_int(params.get("dedup_window_bars", 20), 20, min_value=2, max_value=400)

    return out


def resolve_event_severity(event_type: str, params: dict[str, Any]) -> str:
    chosen = str(params.get("severity", "auto")).strip().lower()
    if chosen in ("info", "warning", "critical"):
        return chosen

    if event_type in (
        "breakout_n_bar_high",
        "breakdown_n_bar_low",
        "donchian_breakout_up",
        "donchian_breakout_down",
        "fib_break_0_618_up",
        "fib_break_0_618_down",
    ):
        return "critical"
    if (
        "bear" in event_type
        or "dead" in event_type
        or event_type.endswith("_down")
        or event_type.startswith("bb_close_outside")
        or "div" in event_type
    ):
        return "warning"
    return "info"


def find_pivot_indices(series: list[float | None], left: int, right: int, kind: str) -> list[int]:
    n = len(series)
    out: list[int] = []
    if left < 1 or right < 1 or n <= left + right:
        return out
    for idx in range(left, n - right):
        value = series[idx]
        if value is None:
            continue
        pivot_ok = True
        for probe in range(idx - left, idx + right + 1):
            if probe == idx:
                continue
            other = series[probe]
            if other is None:
                pivot_ok = False
                break
            if kind == "high":
                if float(other) >= float(value):
                    pivot_ok = False
                    break
            else:
                if float(other) <= float(value):
                    pivot_ok = False
                    break
        if pivot_ok:
            out.append(idx)
    return out


def find_recent_pivot_pair(indices: list[int], min_gap: int, max_gap: int, max_age: int, last_idx: int) -> tuple[int, int] | None:
    if len(indices) < 2:
        return None

    for j in range(len(indices) - 1, 0, -1):
        p2 = indices[j]
        if last_idx - p2 > max_age:
            continue
        for i in range(j - 1, -1, -1):
            p1 = indices[i]
            gap = p2 - p1
            if gap < min_gap:
                continue
            if gap > max_gap:
                break
            return p1, p2
    return None


def evaluate_macd_cross_event(
    event_type: str,
    macd_line: list[float | None],
    signal_line: list[float | None],
    hist_line: list[float | None],
    confirm_bars: int,
    hist_expand_bars: int,
) -> tuple[bool, dict[str, Any]]:
    if confirm_bars < 1:
        confirm_bars = 1
    n = len(macd_line)
    start = n - confirm_bars
    pre = start - 1

    detail: dict[str, Any] = {
        "confirm_bars": confirm_bars,
    }

    if pre < 0:
        detail["reason"] = "not_enough_bars"
        return False, detail

    if macd_line[pre] is None or signal_line[pre] is None or hist_line[pre] is None:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail

    cur_macd: list[float] = []
    cur_sig: list[float] = []
    cur_hist: list[float] = []
    for idx in range(start, n):
        mv = macd_line[idx]
        sv = signal_line[idx]
        hv = hist_line[idx]
        if mv is None or sv is None or hv is None:
            detail["reason"] = "insufficient_indicator_history"
            return False, detail
        cur_macd.append(float(mv))
        cur_sig.append(float(sv))
        cur_hist.append(float(hv))

    pre_macd = float(macd_line[pre])  # type: ignore[arg-type]
    pre_sig = float(signal_line[pre])  # type: ignore[arg-type]
    pre_hist = float(hist_line[pre])  # type: ignore[arg-type]
    last_macd = cur_macd[-1]
    last_sig = cur_sig[-1]
    last_hist = cur_hist[-1]

    if event_type == "macd_golden_cross":
        condition = pre_macd <= pre_sig and all(cur_macd[idx] > cur_sig[idx] for idx in range(len(cur_macd)))
    elif event_type == "macd_dead_cross":
        condition = pre_macd >= pre_sig and all(cur_macd[idx] < cur_sig[idx] for idx in range(len(cur_macd)))
    elif event_type == "macd_golden_cross_above_zero":
        condition = (
            pre_macd <= pre_sig
            and all(cur_macd[idx] > cur_sig[idx] for idx in range(len(cur_macd)))
            and all(cur_macd[idx] > 0 and cur_sig[idx] > 0 for idx in range(len(cur_macd)))
        )
    elif event_type == "macd_dead_cross_below_zero":
        condition = (
            pre_macd >= pre_sig
            and all(cur_macd[idx] < cur_sig[idx] for idx in range(len(cur_macd)))
            and all(cur_macd[idx] < 0 and cur_sig[idx] < 0 for idx in range(len(cur_macd)))
        )
    elif event_type == "macd_zero_cross_up":
        condition = pre_macd <= 0 and all(value > 0 for value in cur_macd)
    elif event_type == "macd_zero_cross_down":
        condition = pre_macd >= 0 and all(value < 0 for value in cur_macd)
    elif event_type == "macd_hist_turn_positive":
        condition = pre_hist <= 0 and all(value > 0 for value in cur_hist)
    elif event_type == "macd_hist_turn_negative":
        condition = pre_hist >= 0 and all(value < 0 for value in cur_hist)
    elif event_type in ("macd_hist_expand_up_n", "macd_hist_expand_down_n"):
        hist_expand_bars = max(2, int(hist_expand_bars))
        if n < hist_expand_bars:
            detail["reason"] = "not_enough_hist_bars"
            detail["hist_expand_bars"] = hist_expand_bars
            return False, detail
        win: list[float] = []
        for idx in range(n - hist_expand_bars, n):
            hv = hist_line[idx]
            if hv is None:
                detail["reason"] = "insufficient_indicator_history"
                return False, detail
            win.append(float(hv))
        if event_type == "macd_hist_expand_up_n":
            condition = all(value > 0 for value in win) and all(win[idx] > win[idx - 1] for idx in range(1, len(win)))
        else:
            condition = all(value < 0 for value in win) and all(win[idx] < win[idx - 1] for idx in range(1, len(win)))
        detail["hist_expand_bars"] = hist_expand_bars
        detail["hist_window"] = win
    else:
        raise RuntimeError(f"unsupported event type: {event_type}")

    detail.update(
        {
            "pre_macd": pre_macd,
            "pre_signal": pre_sig,
            "pre_hist": pre_hist,
            "last_macd": last_macd,
            "last_signal": last_sig,
            "last_hist": last_hist,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_rsi_event(event_type: str, rsi_line: list[float | None], confirm_bars: int) -> tuple[bool, dict[str, Any]]:
    confirm_bars = max(1, int(confirm_bars))
    n = len(rsi_line)
    start = n - confirm_bars
    pre = start - 1
    detail: dict[str, Any] = {"confirm_bars": confirm_bars}

    if pre < 0:
        detail["reason"] = "not_enough_bars"
        return False, detail
    if rsi_line[pre] is None:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail

    cur: list[float] = []
    for idx in range(start, n):
        value = rsi_line[idx]
        if value is None:
            detail["reason"] = "insufficient_indicator_history"
            return False, detail
        cur.append(float(value))

    pre_rsi = float(rsi_line[pre])  # type: ignore[arg-type]
    last_rsi = cur[-1]

    if event_type == "rsi_cross_30_up":
        condition = pre_rsi <= 30.0 and all(v > 30.0 for v in cur)
        level = 30.0
    elif event_type == "rsi_cross_70_down":
        condition = pre_rsi >= 70.0 and all(v < 70.0 for v in cur)
        level = 70.0
    elif event_type == "rsi_enter_overbought":
        condition = pre_rsi < 70.0 and all(v >= 70.0 for v in cur)
        level = 70.0
    elif event_type == "rsi_enter_oversold":
        condition = pre_rsi > 30.0 and all(v <= 30.0 for v in cur)
        level = 30.0
    elif event_type == "rsi_cross_50_up":
        condition = pre_rsi <= 50.0 and all(v > 50.0 for v in cur)
        level = 50.0
    elif event_type == "rsi_cross_50_down":
        condition = pre_rsi >= 50.0 and all(v < 50.0 for v in cur)
        level = 50.0
    else:
        raise RuntimeError(f"unsupported RSI event type: {event_type}")

    detail.update(
        {
            "threshold": level,
            "pre_rsi": pre_rsi,
            "last_rsi": last_rsi,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_ma_event(
    event_type: str,
    closes: list[float],
    sma20: list[float | None],
    sma50: list[float | None],
    ema20: list[float | None],
    ema50: list[float | None],
    confirm_bars: int,
) -> tuple[bool, dict[str, Any]]:
    confirm_bars = max(1, int(confirm_bars))
    n = len(closes)
    start = n - confirm_bars
    pre = start - 1
    detail: dict[str, Any] = {"confirm_bars": confirm_bars}
    if pre < 0:
        detail["reason"] = "not_enough_bars"
        return False, detail

    def need(series: list[float | None], idx: int) -> float:
        value = series[idx]
        if value is None:
            raise RuntimeError("insufficient_indicator_history")
        return float(value)

    try:
        pre_close = float(closes[pre])
        last_close = float(closes[-1])
        pre_sma20 = need(sma20, pre)
        pre_sma50 = need(sma50, pre)
        pre_ema20 = need(ema20, pre)
        pre_ema50 = need(ema50, pre)
        cur_sma20 = [need(sma20, idx) for idx in range(start, n)]
        cur_sma50 = [need(sma50, idx) for idx in range(start, n)]
        cur_ema20 = [need(ema20, idx) for idx in range(start, n)]
        cur_ema50 = [need(ema50, idx) for idx in range(start, n)]
        cur_closes = [float(closes[idx]) for idx in range(start, n)]
    except RuntimeError:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail

    if event_type == "price_cross_sma20_up":
        condition = pre_close <= pre_sma20 and all(cur_closes[i] > cur_sma20[i] for i in range(len(cur_closes)))
    elif event_type == "price_cross_sma20_down":
        condition = pre_close >= pre_sma20 and all(cur_closes[i] < cur_sma20[i] for i in range(len(cur_closes)))
    elif event_type == "price_cross_ema20_up":
        condition = pre_close <= pre_ema20 and all(cur_closes[i] > cur_ema20[i] for i in range(len(cur_closes)))
    elif event_type == "price_cross_ema20_down":
        condition = pre_close >= pre_ema20 and all(cur_closes[i] < cur_ema20[i] for i in range(len(cur_closes)))
    elif event_type == "ema20_cross_ema50_up":
        condition = pre_ema20 <= pre_ema50 and all(cur_ema20[i] > cur_ema50[i] for i in range(len(cur_ema20)))
    elif event_type == "ema20_cross_ema50_down":
        condition = pre_ema20 >= pre_ema50 and all(cur_ema20[i] < cur_ema50[i] for i in range(len(cur_ema20)))
    elif event_type == "ma_bull_alignment":
        condition = all(
            cur_closes[i] > cur_sma20[i] > cur_sma50[i] and cur_ema20[i] > cur_ema50[i]
            for i in range(len(cur_closes))
        )
    elif event_type == "ma_bear_alignment":
        condition = all(
            cur_closes[i] < cur_sma20[i] < cur_sma50[i] and cur_ema20[i] < cur_ema50[i]
            for i in range(len(cur_closes))
        )
    else:
        raise RuntimeError(f"unsupported MA event type: {event_type}")

    detail.update(
        {
            "pre_close": pre_close,
            "last_close": last_close,
            "pre_sma20": pre_sma20,
            "pre_sma50": pre_sma50,
            "pre_ema20": pre_ema20,
            "pre_ema50": pre_ema50,
            "last_sma20": cur_sma20[-1],
            "last_sma50": cur_sma50[-1],
            "last_ema20": cur_ema20[-1],
            "last_ema50": cur_ema50[-1],
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_bb_event(
    event_type: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    bb_upper: list[float | None],
    bb_mid: list[float | None],
    bb_lower: list[float | None],
    confirm_bars: int,
    lookback_bars: int,
    bb_width_threshold: float,
) -> tuple[bool, dict[str, Any]]:
    confirm_bars = max(1, int(confirm_bars))
    lookback_bars = max(2, int(lookback_bars))
    n = len(closes)
    start = n - confirm_bars
    pre = start - 1
    detail: dict[str, Any] = {
        "confirm_bars": confirm_bars,
        "lookback_bars": lookback_bars,
        "bb_width_threshold": bb_width_threshold,
    }
    if pre < 0:
        detail["reason"] = "not_enough_bars"
        return False, detail

    def need(series: list[float | None], idx: int) -> float:
        value = series[idx]
        if value is None:
            raise RuntimeError("insufficient_indicator_history")
        return float(value)

    try:
        pre_upper = need(bb_upper, pre)
        pre_lower = need(bb_lower, pre)
        pre_mid = need(bb_mid, pre)
        cur_upper = [need(bb_upper, idx) for idx in range(start, n)]
        cur_lower = [need(bb_lower, idx) for idx in range(start, n)]
        cur_mid = [need(bb_mid, idx) for idx in range(start, n)]
    except RuntimeError:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail

    last_open = float(opens[-1])
    last_high = float(highs[-1])
    last_low = float(lows[-1])
    last_close = float(closes[-1])
    pre_close = float(closes[pre])
    last_upper = cur_upper[-1]
    last_lower = cur_lower[-1]
    last_mid = cur_mid[-1]

    def bw(upper: float, lower: float, mid: float) -> float:
        denom = abs(mid) if abs(mid) > 1e-12 else 1e-12
        return (upper - lower) / denom

    pre_bw = bw(pre_upper, pre_lower, pre_mid)
    cur_bw = [bw(cur_upper[idx], cur_lower[idx], cur_mid[idx]) for idx in range(len(cur_upper))]
    last_bw = cur_bw[-1]

    if event_type == "bb_touch_upper":
        condition = last_high >= last_upper
    elif event_type == "bb_touch_lower":
        condition = last_low <= last_lower
    elif event_type == "bb_close_outside_upper":
        condition = last_close > last_upper
    elif event_type == "bb_close_outside_lower":
        condition = last_close < last_lower
    elif event_type == "bb_reenter_from_upper":
        condition = pre_close > pre_upper and all(closes[idx] <= cur_upper[idx - start] for idx in range(start, n))
    elif event_type == "bb_reenter_from_lower":
        condition = pre_close < pre_lower and all(closes[idx] >= cur_lower[idx - start] for idx in range(start, n))
    elif event_type == "bb_squeeze_start":
        condition = pre_bw > bb_width_threshold and all(value <= bb_width_threshold for value in cur_bw)
    elif event_type in ("bb_squeeze_breakout_up", "bb_squeeze_breakout_down"):
        win_start = max(0, n - lookback_bars)
        squeeze_vals: list[float] = []
        for idx in range(win_start, n):
            up = bb_upper[idx]
            lo = bb_lower[idx]
            mid = bb_mid[idx]
            if up is None or lo is None or mid is None:
                continue
            squeeze_vals.append(bw(float(up), float(lo), float(mid)))
        if not squeeze_vals:
            detail["reason"] = "insufficient_indicator_history"
            return False, detail
        squeezed_recently = min(squeeze_vals) <= bb_width_threshold
        if event_type == "bb_squeeze_breakout_up":
            condition = squeezed_recently and last_close > last_upper
        else:
            condition = squeezed_recently and last_close < last_lower
        detail["squeeze_window_min_bw"] = min(squeeze_vals)
    else:
        raise RuntimeError(f"unsupported BB event type: {event_type}")

    detail.update(
        {
            "pre_close": pre_close,
            "last_open": last_open,
            "last_high": last_high,
            "last_low": last_low,
            "last_close": last_close,
            "pre_upper": pre_upper,
            "pre_lower": pre_lower,
            "last_upper": last_upper,
            "last_lower": last_lower,
            "last_mid": last_mid,
            "pre_bb_width": pre_bw,
            "last_bb_width": last_bw,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_volume_event(
    event_type: str,
    closes: list[float],
    volumes: list[float],
    confirm_bars: int,
    volume_spike_multiplier: float,
    volume_dry_threshold: float,
) -> tuple[bool, dict[str, Any]]:
    confirm_bars = max(1, int(confirm_bars))
    n = len(closes)
    start = n - confirm_bars
    pre = start - 1
    detail: dict[str, Any] = {"confirm_bars": confirm_bars}
    if pre < 0:
        detail["reason"] = "not_enough_bars"
        return False, detail

    vol_ma20 = rolling_mean(volumes, 20)
    if vol_ma20[-1] is None:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail

    last_volume = float(volumes[-1])
    last_close = float(closes[-1])
    pre_close = float(closes[pre])
    last_vol_ma20 = float(vol_ma20[-1])  # type: ignore[arg-type]

    if event_type == "volume_spike_up":
        condition = last_close > pre_close and last_volume >= last_vol_ma20 * volume_spike_multiplier
        detail["volume_spike_multiplier"] = volume_spike_multiplier
    elif event_type == "volume_spike_down":
        condition = last_close < pre_close and last_volume >= last_vol_ma20 * volume_spike_multiplier
        detail["volume_spike_multiplier"] = volume_spike_multiplier
    elif event_type == "volume_dry_up":
        condition = last_volume <= last_vol_ma20 * volume_dry_threshold
        detail["volume_dry_threshold"] = volume_dry_threshold
    elif event_type in ("obv_cross_ma_up", "obv_cross_ma_down"):
        obv_line = obv_series(closes, volumes)
        obv_ma = rolling_mean(obv_line, 20)
        if obv_ma[pre] is None:
            detail["reason"] = "insufficient_indicator_history"
            return False, detail
        pre_obv = float(obv_line[pre])
        pre_obv_ma = float(obv_ma[pre])  # type: ignore[arg-type]

        cur_obv: list[float] = []
        cur_obv_ma: list[float] = []
        for idx in range(start, n):
            ma_value = obv_ma[idx]
            if ma_value is None:
                detail["reason"] = "insufficient_indicator_history"
                return False, detail
            cur_obv.append(float(obv_line[idx]))
            cur_obv_ma.append(float(ma_value))

        if event_type == "obv_cross_ma_up":
            condition = pre_obv <= pre_obv_ma and all(cur_obv[i] > cur_obv_ma[i] for i in range(len(cur_obv)))
        else:
            condition = pre_obv >= pre_obv_ma and all(cur_obv[i] < cur_obv_ma[i] for i in range(len(cur_obv)))

        detail.update(
            {
                "pre_obv": pre_obv,
                "pre_obv_ma20": pre_obv_ma,
                "last_obv": cur_obv[-1],
                "last_obv_ma20": cur_obv_ma[-1],
            }
        )
    else:
        raise RuntimeError(f"unsupported volume event type: {event_type}")

    detail.update(
        {
            "pre_close": pre_close,
            "last_close": last_close,
            "last_volume": last_volume,
            "last_vol_ma20": last_vol_ma20,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_breakout_event(
    event_type: str,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    confirm_bars: int,
    lookback_bars: int,
    pivot_left: int,
    pivot_right: int,
) -> tuple[bool, dict[str, Any]]:
    confirm_bars = max(1, int(confirm_bars))
    lookback_bars = max(2, int(lookback_bars))
    n = len(closes)
    start = n - confirm_bars
    pre = start - 1
    detail: dict[str, Any] = {
        "confirm_bars": confirm_bars,
        "lookback_bars": lookback_bars,
        "pivot_left": pivot_left,
        "pivot_right": pivot_right,
    }
    if pre < 1:
        detail["reason"] = "not_enough_bars"
        return False, detail

    def rolling_prev_high(idx: int) -> float | None:
        lo = max(0, idx - lookback_bars)
        hi = idx
        if hi <= lo:
            return None
        return max(highs[lo:hi])

    def rolling_prev_low(idx: int) -> float | None:
        lo = max(0, idx - lookback_bars)
        hi = idx
        if hi <= lo:
            return None
        return min(lows[lo:hi])

    pre_close = float(closes[pre])
    last_close = float(closes[-1])
    last_high = float(highs[-1])
    last_low = float(lows[-1])

    if event_type in ("breakout_n_bar_high", "breakdown_n_bar_low", "donchian_breakout_up", "donchian_breakout_down"):
        pre_ref_high = rolling_prev_high(pre)
        pre_ref_low = rolling_prev_low(pre)
        if pre_ref_high is None or pre_ref_low is None:
            detail["reason"] = "not_enough_bars"
            return False, detail

        refs_high: list[float] = []
        refs_low: list[float] = []
        for idx in range(start, n):
            rh = rolling_prev_high(idx)
            rl = rolling_prev_low(idx)
            if rh is None or rl is None:
                detail["reason"] = "not_enough_bars"
                return False, detail
            refs_high.append(float(rh))
            refs_low.append(float(rl))

        if event_type == "breakout_n_bar_high":
            condition = pre_close <= pre_ref_high and all(closes[idx] > refs_high[idx - start] for idx in range(start, n))
            detail["reference_level"] = refs_high[-1]
        elif event_type == "breakdown_n_bar_low":
            condition = pre_close >= pre_ref_low and all(closes[idx] < refs_low[idx - start] for idx in range(start, n))
            detail["reference_level"] = refs_low[-1]
        elif event_type == "donchian_breakout_up":
            condition = highs[pre] <= pre_ref_high and all(highs[idx] > refs_high[idx - start] for idx in range(start, n))
            detail["reference_level"] = refs_high[-1]
        else:
            condition = lows[pre] >= pre_ref_low and all(lows[idx] < refs_low[idx - start] for idx in range(start, n))
            detail["reference_level"] = refs_low[-1]
    elif event_type in ("swing_high_break", "swing_low_break"):
        piv_kind = "high" if event_type == "swing_high_break" else "low"
        series = [float(v) for v in highs] if piv_kind == "high" else [float(v) for v in lows]
        pivots = find_pivot_indices([float(v) for v in series], max(1, pivot_left), max(1, pivot_right), piv_kind)
        pivots = [idx for idx in pivots if idx < start]
        if not pivots:
            detail["reason"] = "no_swing_pivot"
            return False, detail
        pivot_idx = pivots[-1]
        level = float(series[pivot_idx])
        if event_type == "swing_high_break":
            condition = pre_close <= level and all(closes[idx] > level for idx in range(start, n))
        else:
            condition = pre_close >= level and all(closes[idx] < level for idx in range(start, n))
        detail["swing_level"] = level
        detail["swing_index"] = pivot_idx
    else:
        raise RuntimeError(f"unsupported breakout event type: {event_type}")

    detail.update(
        {
            "pre_close": pre_close,
            "last_close": last_close,
            "last_high": last_high,
            "last_low": last_low,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def fib_level_price(fib: dict[str, Any], ratio: float) -> float | None:
    levels = fib.get("levels") if isinstance(fib, dict) else None
    if not isinstance(levels, list):
        return None
    for level in levels:
        if not isinstance(level, dict):
            continue
        try:
            rv = float(level.get("ratio"))
            pv = float(level.get("price"))
        except Exception:
            continue
        if abs(rv - ratio) <= 1e-9:
            return pv
    return None


def evaluate_fib_event(
    event_type: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    confirm_bars: int,
    fib_anchor_bars: int,
    fib_touch_tolerance: float,
) -> tuple[bool, dict[str, Any]]:
    confirm_bars = max(1, int(confirm_bars))
    fib_anchor_bars = max(20, int(fib_anchor_bars))
    n = len(closes)
    start = n - confirm_bars
    pre = start - 1
    detail: dict[str, Any] = {
        "confirm_bars": confirm_bars,
        "fib_anchor_bars": fib_anchor_bars,
        "fib_touch_tolerance": fib_touch_tolerance,
    }
    if pre < 0:
        detail["reason"] = "not_enough_bars"
        return False, detail

    anchor_start = max(0, n - fib_anchor_bars)
    fib = fibonacci_levels(highs[anchor_start:], lows[anchor_start:], closes[anchor_start:])
    ratio_map = {
        "fib_touch_0_382": 0.382,
        "fib_touch_0_5": 0.5,
        "fib_touch_0_618": 0.618,
        "fib_reject_0_618_up": 0.618,
        "fib_reject_0_618_down": 0.618,
        "fib_break_0_618_up": 0.618,
        "fib_break_0_618_down": 0.618,
    }
    ratio = ratio_map.get(event_type)
    if ratio is None:
        raise RuntimeError(f"unsupported Fibonacci event type: {event_type}")
    level = fib_level_price(fib, ratio)
    if level is None:
        detail["reason"] = "fib_level_missing"
        return False, detail

    pre_close = float(closes[pre])
    last_open = float(opens[-1])
    last_high = float(highs[-1])
    last_low = float(lows[-1])
    last_close = float(closes[-1])

    if event_type in ("fib_touch_0_382", "fib_touch_0_5", "fib_touch_0_618"):
        touched = last_low <= level <= last_high
        near = abs(last_close - level) / (abs(level) if abs(level) > 1e-12 else 1e-12) <= fib_touch_tolerance
        condition = touched or near
    elif event_type == "fib_reject_0_618_up":
        condition = last_low <= level and last_close > level and last_close > last_open
    elif event_type == "fib_reject_0_618_down":
        condition = last_high >= level and last_close < level and last_close < last_open
    elif event_type == "fib_break_0_618_up":
        condition = pre_close <= level and all(closes[idx] > level for idx in range(start, n))
    else:
        condition = pre_close >= level and all(closes[idx] < level for idx in range(start, n))

    detail.update(
        {
            "fib_ratio": ratio,
            "fib_level": float(level),
            "fib_trend": fib.get("trend"),
            "pre_close": pre_close,
            "last_open": last_open,
            "last_high": last_high,
            "last_low": last_low,
            "last_close": last_close,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_divergence_event(
    event_type: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    indicator_series: list[float | None],
    indicator_name: str,
    confirm_bars: int,
    pivot_left: int,
    pivot_right: int,
    min_pivot_gap: int,
    max_pivot_gap: int,
    min_price_delta_pct: float,
    min_indicator_delta: float,
    dedup_window_bars: int,
) -> tuple[bool, dict[str, Any]]:
    n = len(closes)
    last_idx = n - 1
    detail: dict[str, Any] = {
        "confirm_bars": confirm_bars,
        "pivot_left": pivot_left,
        "pivot_right": pivot_right,
        "min_pivot_gap": min_pivot_gap,
        "max_pivot_gap": max_pivot_gap,
        "min_price_delta_pct": min_price_delta_pct,
        "min_indicator_delta": min_indicator_delta,
        "dedup_window_bars": dedup_window_bars,
        "indicator_name": indicator_name,
    }
    if last_idx < 5:
        detail["reason"] = "not_enough_bars"
        return False, detail

    is_bull = "_bull_" in event_type
    is_hidden = "_hidden_" in event_type
    pivot_kind = "low" if is_bull else "high"

    price_series: list[float | None]
    if pivot_kind == "low":
        price_series = [float(v) for v in lows]
    else:
        price_series = [float(v) for v in highs]

    pivots = find_pivot_indices(price_series, pivot_left, pivot_right, pivot_kind)
    pair = find_recent_pivot_pair(pivots, min_pivot_gap, max_pivot_gap, dedup_window_bars, last_idx)
    if pair is None:
        detail["reason"] = "no_valid_pivot_pair"
        return False, detail
    i1, i2 = pair

    price1 = float(price_series[i1])  # type: ignore[arg-type]
    price2 = float(price_series[i2])  # type: ignore[arg-type]
    ind1 = indicator_series[i1]
    ind2 = indicator_series[i2]
    if ind1 is None or ind2 is None:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail
    ind1f = float(ind1)
    ind2f = float(ind2)

    min_price_ratio = min_price_delta_pct / 100.0
    if is_bull:
        if is_hidden:
            price_cond = price2 > price1 * (1.0 + min_price_ratio)
            ind_cond = ind2f < ind1f - min_indicator_delta
        else:
            price_cond = price2 < price1 * (1.0 - min_price_ratio)
            ind_cond = ind2f > ind1f + min_indicator_delta
        confirm_cond = all(float(closes[idx]) > float(closes[i2]) for idx in range(max(0, n - confirm_bars), n))
    else:
        if is_hidden:
            price_cond = price2 < price1 * (1.0 - min_price_ratio)
            ind_cond = ind2f > ind1f + min_indicator_delta
        else:
            price_cond = price2 > price1 * (1.0 + min_price_ratio)
            ind_cond = ind2f < ind1f - min_indicator_delta
        confirm_cond = all(float(closes[idx]) < float(closes[i2]) for idx in range(max(0, n - confirm_bars), n))

    condition = bool(price_cond and ind_cond and confirm_cond)
    detail.update(
        {
            "pivot_a_index": i1,
            "pivot_b_index": i2,
            "pivot_a_price": price1,
            "pivot_b_price": price2,
            "pivot_a_indicator": ind1f,
            "pivot_b_indicator": ind2f,
            "price_condition": price_cond,
            "indicator_condition": ind_cond,
            "confirm_condition": confirm_cond,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def resolve_snapshot_flags_for_event(event_type: str) -> dict[str, bool]:
    flags = {
        "sma": False,
        "ema": False,
        "macd": False,
        "rsi": False,
        "bb": False,
        "vol_ma": False,
        "fib": False,
    }
    if event_type in MACD_EVENT_TYPES or event_type.startswith("macd_"):
        flags["macd"] = True
    if event_type in RSI_EVENT_TYPES or event_type.startswith("rsi_"):
        flags["rsi"] = True
    if event_type in MA_EVENT_TYPES:
        flags["sma"] = True
        flags["ema"] = True
    if event_type in BB_EVENT_TYPES:
        flags["bb"] = True
    if event_type in VOLUME_EVENT_TYPES or event_type.startswith("obv_"):
        flags["vol_ma"] = True
    if event_type in FIB_EVENT_TYPES:
        flags["fib"] = True
    if event_type in BREAKOUT_EVENT_TYPES:
        flags["sma"] = True
    return flags


def resolve_event_rule_chart_context(rule: dict[str, Any]) -> dict[str, str]:
    event_type = str(rule.get("event_type", "")).strip().lower()
    if event_type not in EVENT_TYPE_CHOICES:
        raise RuntimeError(f"unsupported event type: {event_type}")

    asset_type = str(rule.get("asset_type", "")).strip().lower()
    if asset_type not in ("crypto", "stock"):
        raise RuntimeError(f"invalid asset type in rule: {asset_type}")

    period = str(rule.get("period", "")).strip()
    interval = str(rule.get("interval", "")).strip()
    period, interval, _ = validate_chart_period_interval(asset_type, period, interval)

    chart_symbol = str(rule.get("quote_symbol") or rule.get("symbol") or "").strip()
    if not chart_symbol:
        raise RuntimeError("event rule missing symbol")

    key = f"{asset_type}|{chart_symbol}|{period}|{interval}"
    return {
        "asset_type": asset_type,
        "period": period,
        "interval": interval,
        "chart_symbol": chart_symbol,
        "key": key,
    }


def build_event_snapshot(
    rule: dict[str, Any],
    evaluation: dict[str, Any],
    chart_payload: dict[str, Any] | None = None,
) -> Path:
    event_type = str(rule.get("event_type", "")).strip().lower()
    params = normalize_event_params_for_compare(event_type, rule.get("params", {}))

    if chart_payload is None:
        ctx = resolve_event_rule_chart_context(rule)
        chart_payload = fetch_chart_data(ctx["asset_type"], ctx["chart_symbol"], ctx["period"], ctx["interval"])

    period = str(chart_payload["period"])
    interval = str(chart_payload["interval"])
    flags = resolve_snapshot_flags_for_event(event_type)
    indicators = compute_indicators(chart_payload["candles"], flags)

    chart_type = str(params.get("snapshot_chart_type", "candlestick"))
    out_path = default_chart_path(chart_payload["symbol"], period, interval, f"event_{chart_type}")
    render_chart_png(
        chart_payload=chart_payload,
        indicators=indicators,
        chart_type=chart_type,
        show_volume=True,
        show_rsi=bool(flags.get("rsi", False)),
        show_macd=bool(flags.get("macd", False)),
        out_path=out_path,
        width=float(params.get("snapshot_width", 14.0)),
        height=float(params.get("snapshot_height", 8.0)),
        dpi=int(params.get("snapshot_dpi", 150)),
    )
    return out_path


def evaluate_event_rule_on_chart(rule: dict[str, Any], chart_payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(rule.get("event_type", "")).strip().lower()
    if event_type not in EVENT_TYPE_CHOICES:
        raise RuntimeError(f"unsupported event type: {event_type}")

    params = normalize_event_params_for_compare(event_type, rule.get("params", {}))
    confirm_bars = max(1, int(rule.get("confirm_bars", 1)))
    candles = chart_payload["candles"]
    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]

    if event_type in MACD_EVENT_TYPES:
        fast, slow, signal, profile = extract_macd_params({"params": params})
        macd_line, signal_line, hist_line = macd_series_custom(closes, fast, slow, signal)
        hist_expand_bars = int(params.get("hist_expand_bars", 3))
        condition, detail = evaluate_macd_cross_event(
            event_type,
            macd_line,
            signal_line,
            hist_line,
            confirm_bars,
            hist_expand_bars,
        )
        detail["macd_profile"] = profile
        detail["macd_fast"] = fast
        detail["macd_slow"] = slow
        detail["macd_signal"] = signal
    elif event_type in RSI_EVENT_TYPES:
        rsi_line = rsi_series(closes, 14)
        condition, detail = evaluate_rsi_event(event_type, rsi_line, confirm_bars)
    elif event_type in MA_EVENT_TYPES:
        sma20 = rolling_mean(closes, 20)
        sma50 = rolling_mean(closes, 50)
        ema20 = ema_series(closes, 20)
        ema50 = ema_series(closes, 50)
        condition, detail = evaluate_ma_event(event_type, closes, sma20, sma50, ema20, ema50, confirm_bars)
    elif event_type in BB_EVENT_TYPES:
        bb_mid = rolling_mean(closes, 20)
        bb_std = rolling_std(closes, 20)
        bb_upper: list[float | None] = [None] * len(closes)
        bb_lower: list[float | None] = [None] * len(closes)
        for idx, (mid, std) in enumerate(zip(bb_mid, bb_std)):
            if mid is None or std is None:
                continue
            bb_upper[idx] = mid + 2.0 * std
            bb_lower[idx] = mid - 2.0 * std
        condition, detail = evaluate_bb_event(
            event_type,
            opens,
            highs,
            lows,
            closes,
            bb_upper,
            bb_mid,
            bb_lower,
            confirm_bars,
            int(params.get("lookback_bars", 20)),
            float(params.get("bb_width_threshold", 0.06)),
        )
    elif event_type in VOLUME_EVENT_TYPES:
        condition, detail = evaluate_volume_event(
            event_type,
            closes,
            volumes,
            confirm_bars,
            float(params.get("volume_spike_multiplier", 1.8)),
            float(params.get("volume_dry_threshold", 0.6)),
        )
    elif event_type in BREAKOUT_EVENT_TYPES:
        condition, detail = evaluate_breakout_event(
            event_type,
            highs,
            lows,
            closes,
            confirm_bars,
            int(params.get("lookback_bars", 20)),
            int(params.get("pivot_left", 3)),
            int(params.get("pivot_right", 3)),
        )
    elif event_type in FIB_EVENT_TYPES:
        condition, detail = evaluate_fib_event(
            event_type,
            opens,
            highs,
            lows,
            closes,
            confirm_bars,
            int(params.get("fib_anchor_bars", 120)),
            float(params.get("fib_touch_tolerance", 0.002)),
        )
    elif event_type in DIVERGENCE_EVENT_TYPES:
        if event_type.startswith("rsi_"):
            indicator = rsi_series(closes, 14)
            indicator_name = "rsi14"
        elif event_type.startswith("macd_"):
            fast, slow, signal, profile = extract_macd_params({"params": params})
            macd_line, _, _ = macd_series_custom(closes, fast, slow, signal)
            indicator = macd_line
            indicator_name = "macd_line"
        else:
            indicator = [float(v) for v in obv_series(closes, volumes)]
            indicator_name = "obv"

        condition, detail = evaluate_divergence_event(
            event_type,
            closes,
            highs,
            lows,
            indicator,
            indicator_name,
            confirm_bars,
            int(params.get("pivot_left", 3)),
            int(params.get("pivot_right", 3)),
            int(params.get("min_pivot_gap", 5)),
            int(params.get("max_pivot_gap", 120)),
            float(params.get("min_price_delta_pct", 0.3)),
            float(params.get("min_indicator_delta", 0.1)),
            int(params.get("dedup_window_bars", 20)),
        )
        if event_type.startswith("macd_"):
            detail["macd_profile"] = profile  # type: ignore[name-defined]
            detail["macd_fast"] = fast  # type: ignore[name-defined]
            detail["macd_slow"] = slow  # type: ignore[name-defined]
            detail["macd_signal"] = signal  # type: ignore[name-defined]
    else:
        raise RuntimeError(f"unsupported event type: {event_type}")

    detail["severity"] = resolve_event_severity(event_type, params)
    detail["attach_chart"] = bool(params.get("attach_chart", False))
    detail["params"] = params

    return {
        "event_type": event_type,
        "condition": bool(condition),
        "chart": {
            "symbol": chart_payload["symbol"],
            "period": chart_payload["period"],
            "interval": chart_payload["interval"],
            "source": chart_payload["source"],
            "as_of": chart_payload["as_of"],
            "checked_at": chart_payload["checked_at"],
        },
        "detail": detail,
    }


def evaluate_event_rule(rule: dict[str, Any]) -> dict[str, Any]:
    ctx = resolve_event_rule_chart_context(rule)
    chart_payload = fetch_chart_data(ctx["asset_type"], ctx["chart_symbol"], ctx["period"], ctx["interval"])
    return evaluate_event_rule_on_chart(rule, chart_payload)


def build_event_chart_cache(
    rules: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]], dict[str, str], dict[str, int]]:
    rule_ctx_by_id: dict[str, dict[str, str]] = {}
    chart_cache: dict[str, dict[str, Any]] = {}
    chart_cache_error: dict[str, str] = {}

    enabled_rules = 0
    reused_rules = 0
    fetches = 0
    failures = 0

    for rule in rules:
        if not bool(rule.get("enabled", True)):
            continue
        enabled_rules += 1
        rule_id = str(rule.get("id"))
        try:
            ctx = resolve_event_rule_chart_context(rule)
            rule_ctx_by_id[rule_id] = ctx
            key = ctx["key"]
            if key in chart_cache or key in chart_cache_error:
                reused_rules += 1
                continue
            try:
                chart_cache[key] = fetch_chart_data(ctx["asset_type"], ctx["chart_symbol"], ctx["period"], ctx["interval"])
                fetches += 1
            except Exception as exc:
                chart_cache_error[key] = str(exc)
                failures += 1
        except Exception as exc:
            chart_cache_error[f"rule:{rule_id}"] = str(exc)
            failures += 1

    metrics = {
        "enabled_rules": enabled_rules,
        "chart_cache_keys": len(chart_cache),
        "chart_cache_fetches": fetches,
        "chart_cache_failures": failures,
        "chart_cache_reused_rules": reused_rules,
    }
    return rule_ctx_by_id, chart_cache, chart_cache_error, metrics


def can_trigger_with_cooldown(last_triggered_at: str, cooldown_minutes: int) -> bool:
    if cooldown_minutes <= 0:
        return True
    dt = iso_to_dt(last_triggered_at)
    if dt is None:
        return True
    elapsed = datetime.now(timezone.utc) - dt
    return elapsed >= timedelta(minutes=cooldown_minutes)


def format_event_message(rule: dict[str, Any], evaluation: dict[str, Any]) -> str:
    event_type = str(rule.get("event_type", ""))
    chart = evaluation.get("chart", {})
    detail = evaluation.get("detail", {})
    severity = str(detail.get("severity", "info")).lower()

    parts = [
        f"[EVENT ALERT][{severity.upper()}] {chart.get('symbol', rule.get('symbol'))} {event_type}",
        f"tf={chart.get('period')}/{chart.get('interval')}",
        f"source={chart.get('source')}",
        f"as_of={chart.get('as_of')}",
        f"id={rule.get('id')}",
    ]

    def append_float(name: str, value: Any) -> None:
        if isinstance(value, (int, float)):
            parts.append(f"{name}={float(value):.6f}")

    if event_type.startswith("macd_"):
        profile = detail.get("macd_profile")
        fast = detail.get("macd_fast")
        slow = detail.get("macd_slow")
        signal = detail.get("macd_signal")
        if profile and isinstance(fast, int) and isinstance(slow, int) and isinstance(signal, int):
            parts.append(f"profile={profile}:{fast},{slow},{signal}")
        elif profile:
            parts.append(f"profile={profile}")

        parts.append(f"confirm={detail.get('confirm_bars')}")

        append_float("pre_macd", detail.get("pre_macd"))
        append_float("pre_signal", detail.get("pre_signal"))
        append_float("pre_hist", detail.get("pre_hist"))
        append_float("macd", detail.get("last_macd"))
        append_float("signal", detail.get("last_signal"))
        append_float("hist", detail.get("last_hist"))

        if event_type in MACD_HIST_EXPAND_EVENT_TYPES:
            hist_expand_bars = detail.get("hist_expand_bars")
            if isinstance(hist_expand_bars, int):
                parts.append(f"hist_expand_bars={hist_expand_bars}")
            hist_window = detail.get("hist_window")
            if isinstance(hist_window, list) and hist_window:
                serialized = [f"{float(v):.6f}" for v in hist_window if isinstance(v, (int, float))]
                if len(serialized) == len(hist_window):
                    parts.append(f"hist_window={','.join(serialized)}")
    elif event_type in RSI_EVENT_TYPES:
        append_float("pre_rsi", detail.get("pre_rsi"))
        append_float("rsi", detail.get("last_rsi"))
        append_float("threshold", detail.get("threshold"))
        parts.append(f"confirm={detail.get('confirm_bars')}")
    elif event_type in MA_EVENT_TYPES:
        append_float("pre_close", detail.get("pre_close"))
        append_float("close", detail.get("last_close"))
        append_float("sma20", detail.get("last_sma20"))
        append_float("sma50", detail.get("last_sma50"))
        append_float("ema20", detail.get("last_ema20"))
        append_float("ema50", detail.get("last_ema50"))
        parts.append(f"confirm={detail.get('confirm_bars')}")
    elif event_type in BB_EVENT_TYPES:
        append_float("close", detail.get("last_close"))
        append_float("bb_upper", detail.get("last_upper"))
        append_float("bb_mid", detail.get("last_mid"))
        append_float("bb_lower", detail.get("last_lower"))
        append_float("bb_width", detail.get("last_bb_width"))
        append_float("bb_width_threshold", detail.get("bb_width_threshold"))
    elif event_type in VOLUME_EVENT_TYPES:
        append_float("close", detail.get("last_close"))
        append_float("volume", detail.get("last_volume"))
        append_float("vol_ma20", detail.get("last_vol_ma20"))
        append_float("obv", detail.get("last_obv"))
        append_float("obv_ma20", detail.get("last_obv_ma20"))
    elif event_type in BREAKOUT_EVENT_TYPES:
        append_float("close", detail.get("last_close"))
        append_float("high", detail.get("last_high"))
        append_float("low", detail.get("last_low"))
        append_float("level", detail.get("reference_level"))
        append_float("swing_level", detail.get("swing_level"))
        parts.append(f"lookback={detail.get('lookback_bars')}")
    elif event_type in FIB_EVENT_TYPES:
        append_float("close", detail.get("last_close"))
        append_float("fib_level", detail.get("fib_level"))
        append_float("fib_ratio", detail.get("fib_ratio"))
        parts.append(f"fib_trend={detail.get('fib_trend')}")
    elif event_type in DIVERGENCE_EVENT_TYPES:
        append_float("p1_price", detail.get("pivot_a_price"))
        append_float("p2_price", detail.get("pivot_b_price"))
        append_float("p1_ind", detail.get("pivot_a_indicator"))
        append_float("p2_ind", detail.get("pivot_b_indicator"))
        parts.append(f"pivot_idx={detail.get('pivot_a_index')}->{detail.get('pivot_b_index')}")
        parts.append(f"ind={detail.get('indicator_name')}")
        parts.append(f"confirm={detail.get('confirm_bars')}")

    reason = detail.get("reason")
    if reason:
        parts.append(f"reason={reason}")

    return " ".join(str(p) for p in parts)

# ----------------------- Command handlers -----------------------

def cmd_quote(args: argparse.Namespace) -> int:
    asset_type = args.type
    if asset_type == "auto":
        asset_type = resolve_asset_type(args.symbol)

    quote = fetch_price(asset_type, args.symbol)
    if args.json:
        print(json.dumps(quote, ensure_ascii=False, indent=2))
    else:
        print(
            f"{quote['symbol']} ({quote['asset_type']}): {quote['price']:.6f} USD "
            f"source={quote['source']} as_of={quote['as_of']} checked={quote['checked_at']}"
        )
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    ensure_state_dir()

    if bool(args.channel) ^ bool(args.target):
        raise ValueError("--channel and --target must be provided together")

    threshold = args.above if args.above is not None else args.below
    if threshold is None:
        raise ValueError("either --above or --below is required")
    if threshold <= 0:
        raise ValueError("threshold must be > 0")

    direction = "above" if args.above is not None else "below"

    if args.type == "crypto":
        base, normalized = normalize_crypto_symbol(args.symbol)
        symbol_for_alert = base
        quote_symbol = normalized
    else:
        symbol_for_alert = normalize_stock_symbol(args.symbol)
        quote_symbol = symbol_for_alert

    alerts = load_alerts()

    for existing in alerts:
        if (
            existing.get("asset_type") == args.type
            and existing.get("symbol") == symbol_for_alert
            and existing.get("direction") == direction
            and float(existing.get("threshold", -1)) == float(threshold)
            and (existing.get("channel") or "") == (args.channel or "")
            and (existing.get("target") or "") == (args.target or "")
            and bool(existing.get("enabled", True))
        ):
            if args.json:
                print(json.dumps(existing, ensure_ascii=False, indent=2))
            else:
                print(f"EXISTS {existing['id']} {existing['asset_type']} {existing['symbol']} {direction} {threshold}")
            return 0

    alert = {
        "id": secrets.token_hex(4),
        "asset_type": args.type,
        "symbol": symbol_for_alert,
        "quote_symbol": quote_symbol,
        "direction": direction,
        "threshold": float(threshold),
        "channel": args.channel or "",
        "target": args.target or "",
        "note": args.note or "",
        "repeat_mode": args.repeat,
        "enabled": True,
        "created_at": now_iso(),
    }
    alerts.append(alert)
    save_alerts(alerts)

    if args.json:
        print(json.dumps(alert, ensure_ascii=False, indent=2))
    else:
        dest = f"{alert['channel']}:{alert['target']}" if alert["channel"] and alert["target"] else "local-log-only"
        print(
            f"ADDED {alert['id']} {alert['asset_type']} {alert['symbol']} "
            f"when {alert['direction']} {alert['threshold']} -> {dest}"
        )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    alerts = load_alerts()
    if args.json:
        print(json.dumps({"alerts": alerts}, ensure_ascii=False, indent=2))
        return 0

    if not alerts:
        print("No alerts configured.")
        return 0

    print("ID       TYPE    SYMBOL     RULE             MODE        DESTINATION              ENABLED   CREATED_AT")
    for alert in alerts:
        rule = f"{alert.get('direction')} {alert.get('threshold')}"
        dest = f"{alert.get('channel')}:{alert.get('target')}" if alert.get("channel") and alert.get("target") else "local-log-only"
        repeat_mode = str(alert.get("repeat_mode", "edge"))
        print(
            f"{str(alert.get('id','')):8} {str(alert.get('asset_type','')):7} {str(alert.get('symbol','')):10} "
            f"{rule:16} {repeat_mode:10} {dest:24} {str(alert.get('enabled', True)):8} {str(alert.get('created_at',''))}"
        )
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    alerts = load_alerts()
    kept = [a for a in alerts if a.get("id") != args.id]
    if len(kept) == len(alerts):
        print(f"NOT_FOUND {args.id}")
        return 1
    save_alerts(kept)

    status = load_status()
    if args.id in status:
        status.pop(args.id, None)
        save_status(status)

    print(f"REMOVED {args.id}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    lock_handle = acquire_check_lock()
    try:
        alerts = load_alerts()
        status = load_status()

        triggered = 0
        checked = 0
        errors = 0
        results: list[dict[str, Any]] = []

        for alert in alerts:
            if not bool(alert.get("enabled", True)):
                continue

            checked += 1
            alert_id = str(alert.get("id"))
            previous = status.get(alert_id, {})
            prev_condition = bool(previous.get("last_condition", False))

            try:
                quote = fetch_price(str(alert.get("asset_type")), str(alert.get("quote_symbol") or alert.get("symbol")))
                condition_now = evaluate_condition(float(quote["price"]), str(alert.get("direction")), float(alert.get("threshold")))
                repeat_mode = str(alert.get("repeat_mode", "edge")).strip().lower()
                should_notify = condition_now and (repeat_mode == "continuous" or not prev_condition)

                message = ""
                delivered = False
                if should_notify:
                    message = format_alert_message(alert, quote)
                    delivered = send_notification(alert, message, dry_run=args.dry_run, quiet=args.quiet)
                    triggered += 1

                status[alert_id] = {
                    "last_checked_at": quote["checked_at"],
                    "last_price": quote["price"],
                    "last_source": quote["source"],
                    "last_as_of": quote["as_of"],
                    "last_condition": condition_now,
                    "last_error": "",
                    "last_triggered_at": now_iso() if should_notify else previous.get("last_triggered_at", ""),
                    "last_triggered_price": quote["price"] if should_notify else previous.get("last_triggered_price"),
                    "last_delivery_ok": delivered if should_notify else previous.get("last_delivery_ok"),
                }

                row = {
                    "id": alert_id,
                    "symbol": quote["symbol"],
                    "price": quote["price"],
                    "threshold": alert.get("threshold"),
                    "direction": alert.get("direction"),
                    "condition": condition_now,
                    "triggered": should_notify,
                    "source": quote["source"],
                    "checked_at": quote["checked_at"],
                    "error": "",
                }
                results.append(row)

                if not args.quiet:
                    state_txt = "TRIGGERED" if should_notify else ("ARMED" if condition_now else "WAIT")
                    print(
                        f"{state_txt:9} id={alert_id} symbol={quote['symbol']} price={quote['price']:.6f} "
                        f"rule={alert.get('direction')} {float(alert.get('threshold')):.6f} source={quote['source']}"
                    )
                    if should_notify and message:
                        print(f"MESSAGE   {message}")

            except Exception as exc:
                errors += 1
                status[alert_id] = {
                    "last_checked_at": now_iso(),
                    "last_price": previous.get("last_price"),
                    "last_source": previous.get("last_source", ""),
                    "last_as_of": previous.get("last_as_of", ""),
                    "last_condition": previous.get("last_condition", False),
                    "last_error": str(exc),
                    "last_triggered_at": previous.get("last_triggered_at", ""),
                    "last_triggered_price": previous.get("last_triggered_price"),
                    "last_delivery_ok": previous.get("last_delivery_ok"),
                }
                results.append(
                    {
                        "id": alert_id,
                        "symbol": alert.get("symbol"),
                        "price": None,
                        "threshold": alert.get("threshold"),
                        "direction": alert.get("direction"),
                        "condition": None,
                        "triggered": False,
                        "source": "",
                        "checked_at": now_iso(),
                        "error": str(exc),
                    }
                )
                if not args.quiet:
                    print(f"ERROR     id={alert_id} symbol={alert.get('symbol')} error={exc}")

        save_status(status)

        summary = {
            "checked": checked,
            "triggered": triggered,
            "errors": errors,
            "dry_run": bool(args.dry_run),
            "timestamp": now_iso(),
        }

        if args.json:
            print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
        elif not args.quiet:
            print(f"SUMMARY   checked={checked} triggered={triggered} errors={errors} dry_run={bool(args.dry_run)}")

        if errors > 0 and args.fail_on_error:
            return 2
        return 0
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
        except Exception:
            pass


def build_event_params_from_args(event_type: str, asset_type: str, args: argparse.Namespace) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "severity": str(args.severity),
        "attach_chart": bool(args.attach_chart),
        "snapshot_chart_type": str(args.snapshot_chart_type),
        "snapshot_width": float(args.snapshot_width),
        "snapshot_height": float(args.snapshot_height),
        "snapshot_dpi": int(args.snapshot_dpi),
        "lookback_bars": int(args.lookback_bars),
        "bb_width_threshold": float(args.bb_width_threshold),
        "volume_spike_multiplier": float(args.volume_spike_multiplier),
        "volume_dry_threshold": float(args.volume_dry_threshold),
        "fib_anchor_bars": int(args.fib_anchor_bars),
        "fib_touch_tolerance": float(args.fib_touch_tolerance),
        "pivot_left": int(args.pivot_left),
        "pivot_right": int(args.pivot_right),
        "min_pivot_gap": int(args.min_pivot_gap),
        "max_pivot_gap": int(args.max_pivot_gap),
        "min_price_delta_pct": float(args.min_price_delta_pct),
        "min_indicator_delta": float(args.min_indicator_delta),
        "dedup_window_bars": int(args.dedup_window_bars),
    }
    if event_type in MACD_EVENT_WITH_PROFILE_TYPES:
        raw.update(resolve_macd_profile_params(asset_type, args.macd_profile, args.macd_fast, args.macd_slow, args.macd_signal))
    if event_type in MACD_HIST_EXPAND_EVENT_TYPES:
        raw["hist_expand_bars"] = max(2, int(args.hist_expand_bars))
    return normalize_event_params_for_compare(event_type, raw)


def upsert_event_rule(
    rules: list[dict[str, Any]],
    event_type: str,
    asset_type: str,
    symbol_for_rule: str,
    quote_symbol: str,
    period: str,
    interval: str,
    confirm_bars: int,
    cooldown_minutes: int,
    dedup_mode: str,
    params: dict[str, Any],
    channel: str,
    target: str,
    note: str,
) -> tuple[dict[str, Any], bool]:
    norm_params = normalize_event_params_for_compare(event_type, params)
    for existing in rules:
        existing_event_type = str(existing.get("event_type", "")).strip().lower()
        existing_params = normalize_event_params_for_compare(existing_event_type, existing.get("params", {}))
        if (
            bool(existing.get("enabled", True))
            and existing_event_type == event_type
            and str(existing.get("asset_type", "")).strip().lower() == asset_type
            and str(existing.get("symbol", "")) == symbol_for_rule
            and str(existing.get("period", "")) == period
            and str(existing.get("interval", "")) == interval
            and int(existing.get("confirm_bars", 1)) == confirm_bars
            and int(existing.get("cooldown_minutes", 0)) == cooldown_minutes
            and str(existing.get("dedup_mode", "cross_once")).lower() == dedup_mode
            and str(existing.get("channel", "")) == channel
            and str(existing.get("target", "")) == target
            and existing_params == norm_params
        ):
            return existing, False

    rule = {
        "id": secrets.token_hex(4),
        "event_type": event_type,
        "asset_type": asset_type,
        "symbol": symbol_for_rule,
        "quote_symbol": quote_symbol,
        "period": period,
        "interval": interval,
        "confirm_bars": confirm_bars,
        "cooldown_minutes": cooldown_minutes,
        "dedup_mode": dedup_mode,
        "params": norm_params,
        "channel": channel,
        "target": target,
        "note": note,
        "enabled": True,
        "created_at": now_iso(),
    }
    rules.append(rule)
    return rule, True


def cmd_event_add(args: argparse.Namespace) -> int:
    ensure_state_dir()

    if bool(args.channel) ^ bool(args.target):
        raise ValueError("--channel and --target must be provided together")

    event_type = str(args.event_type).strip().lower()
    if event_type not in EVENT_TYPE_CHOICES:
        raise ValueError(f"--event-type must be one of: {', '.join(EVENT_TYPE_CHOICES)}")

    asset_type = str(args.type).strip().lower()
    if asset_type == "auto":
        asset_type = resolve_asset_type(args.symbol)
    if asset_type not in ("crypto", "stock"):
        raise ValueError("--type must resolve to crypto or stock")

    period, interval = resolve_event_defaults(asset_type, args.period, args.interval)
    period, interval, auto_note = validate_chart_period_interval(asset_type, period, interval)

    symbol_for_rule, quote_symbol = normalize_event_symbol(asset_type, args.symbol)
    confirm_bars = max(1, int(args.confirm_bars))
    cooldown_minutes = max(0, int(args.cooldown_minutes))
    dedup_mode = str(args.dedup_mode).strip().lower()

    params = build_event_params_from_args(event_type, asset_type, args)
    rules = load_event_rules()
    rule, created = upsert_event_rule(
        rules=rules,
        event_type=event_type,
        asset_type=asset_type,
        symbol_for_rule=symbol_for_rule,
        quote_symbol=quote_symbol,
        period=period,
        interval=interval,
        confirm_bars=confirm_bars,
        cooldown_minutes=cooldown_minutes,
        dedup_mode=dedup_mode,
        params=params,
        channel=str(args.channel or ""),
        target=str(args.target or ""),
        note=str(args.note or ""),
    )
    if created:
        save_event_rules(rules)

    if args.json:
        payload = {"rule": rule, "note": auto_note, "created": bool(created)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        action = "EVENT_ADDED" if created else "EXISTS"
        dest = f"{rule['channel']}:{rule['target']}" if rule["channel"] and rule["target"] else "local-log-only"
        print(
            f"{action} {rule['id']} {rule['event_type']} {rule['asset_type']} {rule['symbol']} "
            f"tf={rule['period']}/{rule['interval']} confirm={rule['confirm_bars']} cooldown={rule['cooldown_minutes']}m "
            f"dedup={rule['dedup_mode']} -> {dest}"
        )
        if auto_note:
            print(f"NOTE {auto_note}")
    return 0


def build_preset_specs(preset: str, asset_type: str) -> list[dict[str, Any]]:
    if preset in ("preset_stock_trend", "preset_stock_reversal") and asset_type != "stock":
        raise ValueError(f"{preset} requires --type stock")
    if preset in ("preset_crypto_momentum_15m", "preset_crypto_divergence_15m") and asset_type != "crypto":
        raise ValueError(f"{preset} requires --type crypto")

    bundles: dict[str, list[dict[str, Any]]] = {
        "preset_stock_trend": [
            {"event_type": "ma_bull_alignment"},
            {"event_type": "price_cross_sma20_up"},
            {"event_type": "ema20_cross_ema50_up"},
            {"event_type": "bb_squeeze_breakout_up", "params": {"lookback_bars": 20}},
        ],
        "preset_stock_reversal": [
            {"event_type": "rsi_enter_oversold"},
            {"event_type": "rsi_cross_30_up"},
            {"event_type": "bb_reenter_from_lower"},
            {"event_type": "macd_golden_cross"},
        ],
        "preset_crypto_momentum_15m": [
            {"event_type": "macd_golden_cross_above_zero"},
            {"event_type": "rsi_cross_50_up"},
            {"event_type": "volume_spike_up"},
            {"event_type": "breakout_n_bar_high", "params": {"lookback_bars": 20}},
        ],
        "preset_crypto_divergence_15m": [
            {"event_type": "rsi_regular_bull_div"},
            {"event_type": "macd_regular_bull_div"},
            {"event_type": "obv_regular_bull_div"},
            {"event_type": "rsi_hidden_bull_div"},
        ],
        "preset_fib_pullback": [
            {"event_type": "fib_touch_0_5"},
            {"event_type": "fib_touch_0_618"},
            {"event_type": "fib_reject_0_618_up"},
        ],
        "preset_breakout_follow": [
            {"event_type": "breakout_n_bar_high", "params": {"lookback_bars": 20}},
            {"event_type": "donchian_breakout_up", "params": {"lookback_bars": 20}},
            {"event_type": "volume_spike_up"},
        ],
    }
    return bundles[preset]


def cmd_event_install_preset(args: argparse.Namespace) -> int:
    ensure_state_dir()
    if bool(args.channel) ^ bool(args.target):
        raise ValueError("--channel and --target must be provided together")

    preset = str(args.preset).strip()
    if preset not in EVENT_PRESET_CHOICES:
        raise ValueError(f"--preset must be one of: {', '.join(EVENT_PRESET_CHOICES)}")

    asset_type = str(args.type).strip().lower()
    if asset_type == "auto":
        asset_type = resolve_asset_type(args.symbol)
    if asset_type not in ("crypto", "stock"):
        raise ValueError("--type must resolve to crypto or stock")

    period, interval = resolve_event_defaults(asset_type, args.period, args.interval)
    if preset in ("preset_stock_trend", "preset_stock_reversal"):
        period = period or "6mo"
        interval = interval or "1d"
    if preset in ("preset_crypto_momentum_15m", "preset_crypto_divergence_15m"):
        period = period or "5d"
        interval = interval or "15m"
    period, interval, auto_note = validate_chart_period_interval(asset_type, period, interval)

    symbol_for_rule, quote_symbol = normalize_event_symbol(asset_type, args.symbol)
    confirm_bars = max(1, int(args.confirm_bars))
    cooldown_minutes = max(0, int(args.cooldown_minutes))
    dedup_mode = str(args.dedup_mode).strip().lower()

    specs = build_preset_specs(preset, asset_type)
    rules = load_event_rules()
    created_count = 0
    out_rules: list[dict[str, Any]] = []
    for spec in specs:
        event_type = str(spec["event_type"]).strip().lower()
        raw_params: dict[str, Any] = {}
        if event_type in MACD_EVENT_WITH_PROFILE_TYPES:
            raw_params.update(resolve_macd_profile_params(asset_type, args.macd_profile, args.macd_fast, args.macd_slow, args.macd_signal))
        raw_params.update(spec.get("params", {}))
        raw_params.update(
            {
                "severity": str(args.severity),
                "attach_chart": bool(args.attach_chart),
                "snapshot_chart_type": str(args.snapshot_chart_type),
                "snapshot_width": float(args.snapshot_width),
                "snapshot_height": float(args.snapshot_height),
                "snapshot_dpi": int(args.snapshot_dpi),
                "lookback_bars": int(args.lookback_bars),
                "bb_width_threshold": float(args.bb_width_threshold),
                "volume_spike_multiplier": float(args.volume_spike_multiplier),
                "volume_dry_threshold": float(args.volume_dry_threshold),
                "fib_anchor_bars": int(args.fib_anchor_bars),
                "fib_touch_tolerance": float(args.fib_touch_tolerance),
                "pivot_left": int(args.pivot_left),
                "pivot_right": int(args.pivot_right),
                "min_pivot_gap": int(args.min_pivot_gap),
                "max_pivot_gap": int(args.max_pivot_gap),
                "min_price_delta_pct": float(args.min_price_delta_pct),
                "min_indicator_delta": float(args.min_indicator_delta),
                "dedup_window_bars": int(args.dedup_window_bars),
                "hist_expand_bars": int(args.hist_expand_bars),
            }
        )
        params = normalize_event_params_for_compare(event_type, raw_params)
        rule, created = upsert_event_rule(
            rules=rules,
            event_type=event_type,
            asset_type=asset_type,
            symbol_for_rule=symbol_for_rule,
            quote_symbol=quote_symbol,
            period=period,
            interval=interval,
            confirm_bars=confirm_bars,
            cooldown_minutes=cooldown_minutes,
            dedup_mode=dedup_mode,
            params=params,
            channel=str(args.channel or ""),
            target=str(args.target or ""),
            note=str(args.note or f"preset={preset}"),
        )
        if created:
            created_count += 1
        out_rules.append(rule)

    save_event_rules(rules)
    payload = {
        "preset": preset,
        "asset_type": asset_type,
        "symbol": symbol_for_rule,
        "period": period,
        "interval": interval,
        "created": created_count,
        "total": len(out_rules),
        "note": auto_note,
        "rules": out_rules,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"PRESET_INSTALLED preset={preset} symbol={symbol_for_rule} tf={period}/{interval} "
            f"created={created_count} total={len(out_rules)}"
        )
        if auto_note:
            print(f"NOTE {auto_note}")
    return 0


def cmd_event_list(args: argparse.Namespace) -> int:
    rules = load_event_rules()
    if args.json:
        print(json.dumps({"rules": rules}, ensure_ascii=False, indent=2))
        return 0

    if not rules:
        print("No event rules configured.")
        return 0

    print("ID       EVENT_TYPE                      TYPE    SYMBOL     TF               CONF  CD(min)  DEDUP       DESTINATION              ENABLED")
    for rule in rules:
        tf = f"{rule.get('period')}/{rule.get('interval')}"
        dest = f"{rule.get('channel')}:{rule.get('target')}" if rule.get("channel") and rule.get("target") else "local-log-only"
        print(
            f"{str(rule.get('id','')):8} {str(rule.get('event_type','')):30} {str(rule.get('asset_type','')):7} "
            f"{str(rule.get('symbol','')):10} {tf:16} {int(rule.get('confirm_bars',1)):4}  "
            f"{int(rule.get('cooldown_minutes',0)):7}  {str(rule.get('dedup_mode','cross_once')):10} "
            f"{dest:24} {str(rule.get('enabled', True))}"
        )
    return 0


def cmd_event_rm(args: argparse.Namespace) -> int:
    rules = load_event_rules()
    kept = [rule for rule in rules if str(rule.get("id")) != args.id]
    if len(kept) == len(rules):
        print(f"NOT_FOUND {args.id}")
        return 1
    save_event_rules(kept)

    status = load_event_status()
    if args.id in status:
        status.pop(args.id, None)
        save_event_status(status)

    print(f"EVENT_REMOVED {args.id}")
    return 0


def cmd_event_check(args: argparse.Namespace) -> int:
    lock_handle = acquire_event_check_lock()
    try:
        started = time.perf_counter()
        rules = load_event_rules()
        status = load_event_status()

        triggered = 0
        checked = 0
        errors = 0
        results: list[dict[str, Any]] = []
        rule_ctx_by_id, chart_cache, chart_cache_error, cache_metrics = build_event_chart_cache(rules)

        for rule in rules:
            if not bool(rule.get("enabled", True)):
                continue

            checked += 1
            rule_id = str(rule.get("id"))
            previous = status.get(rule_id, {})
            prev_condition = bool(previous.get("last_condition", False))

            try:
                ctx = rule_ctx_by_id.get(rule_id)
                if ctx is None:
                    raise RuntimeError(chart_cache_error.get(f"rule:{rule_id}", "rule context missing"))
                cache_key = ctx["key"]
                if cache_key in chart_cache_error:
                    raise RuntimeError(chart_cache_error[cache_key])
                chart_payload = chart_cache.get(cache_key)
                if chart_payload is None:
                    raise RuntimeError("cached chart payload missing")

                evaluation = evaluate_event_rule_on_chart(rule, chart_payload)
                condition_now = bool(evaluation.get("condition", False))

                dedup_mode = str(rule.get("dedup_mode", "cross_once")).strip().lower()
                base_trigger = condition_now and (dedup_mode == "continuous" or not prev_condition)
                cooldown_minutes = max(0, int(rule.get("cooldown_minutes", 0)))
                cooldown_ok = can_trigger_with_cooldown(str(previous.get("last_triggered_at", "")), cooldown_minutes)
                should_notify = base_trigger and cooldown_ok

                event_type = str(rule.get("event_type", "")).strip().lower()
                params = normalize_event_params_for_compare(event_type, rule.get("params", {}))

                message = ""
                delivered = False
                snapshot_path = ""
                if should_notify:
                    message = format_event_message(rule, evaluation)
                    attach_chart = bool(params.get("attach_chart", False))
                    if attach_chart:
                        try:
                            snap_path = build_event_snapshot(rule, evaluation, chart_payload=chart_payload)
                            snapshot_path = str(snap_path)
                            if rule.get("channel") and rule.get("target"):
                                delivered = send_media_notification(
                                    str(rule.get("channel")),
                                    str(rule.get("target")),
                                    message,
                                    snap_path,
                                    dry_run=args.dry_run,
                                )
                            else:
                                delivered = send_notification(rule, message, dry_run=args.dry_run, quiet=args.quiet)
                                if not args.quiet:
                                    print(f"SNAPSHOT  id={rule_id} path={snapshot_path}")
                        except Exception as snap_exc:
                            message = f"{message} snapshot_error={snap_exc}"
                            delivered = send_notification(rule, message, dry_run=args.dry_run, quiet=args.quiet)
                    else:
                        delivered = send_notification(rule, message, dry_run=args.dry_run, quiet=args.quiet)
                    triggered += 1

                chart = evaluation.get("chart", {})
                detail = evaluation.get("detail", {})
                status[rule_id] = {
                    "last_checked_at": chart.get("checked_at", now_iso()),
                    "last_condition": condition_now,
                    "last_error": "",
                    "last_event_source": chart.get("source", ""),
                    "last_event_as_of": chart.get("as_of", ""),
                    "last_detail": detail,
                    "last_triggered_at": now_iso() if should_notify else previous.get("last_triggered_at", ""),
                    "last_delivery_ok": delivered if should_notify else previous.get("last_delivery_ok"),
                    "last_snapshot_path": snapshot_path if should_notify else previous.get("last_snapshot_path", ""),
                }

                row = {
                    "id": rule_id,
                    "event_type": rule.get("event_type"),
                    "symbol": chart.get("symbol", rule.get("symbol")),
                    "timeframe": f"{chart.get('period', rule.get('period'))}/{chart.get('interval', rule.get('interval'))}",
                    "condition": condition_now,
                    "triggered": should_notify,
                    "source": chart.get("source", ""),
                    "checked_at": chart.get("checked_at", now_iso()),
                    "error": "",
                    "detail": detail,
                    "snapshot_path": snapshot_path,
                }
                results.append(row)

                if not args.quiet:
                    if should_notify:
                        state_txt = "TRIGGERED"
                    elif condition_now and base_trigger and not cooldown_ok:
                        state_txt = "COOLDOWN"
                    elif condition_now:
                        state_txt = "ARMED"
                    else:
                        state_txt = "WAIT"
                    print(
                        f"{state_txt:9} id={rule_id} event={rule.get('event_type')} symbol={row['symbol']} "
                        f"tf={row['timeframe']} source={row['source']}"
                    )
                    if should_notify and message:
                        print(f"MESSAGE   {message}")
                    if should_notify and snapshot_path:
                        print(f"SNAPSHOT  {snapshot_path}")

            except Exception as exc:
                errors += 1
                status[rule_id] = {
                    "last_checked_at": now_iso(),
                    "last_condition": previous.get("last_condition", False),
                    "last_error": str(exc),
                    "last_event_source": previous.get("last_event_source", ""),
                    "last_event_as_of": previous.get("last_event_as_of", ""),
                    "last_detail": previous.get("last_detail", {}),
                    "last_triggered_at": previous.get("last_triggered_at", ""),
                    "last_delivery_ok": previous.get("last_delivery_ok"),
                    "last_snapshot_path": previous.get("last_snapshot_path", ""),
                }
                results.append(
                    {
                        "id": rule_id,
                        "event_type": rule.get("event_type"),
                        "symbol": rule.get("symbol"),
                        "timeframe": f"{rule.get('period')}/{rule.get('interval')}",
                        "condition": None,
                        "triggered": False,
                        "source": "",
                        "checked_at": now_iso(),
                        "error": str(exc),
                        "detail": {},
                        "snapshot_path": "",
                    }
                )
                if not args.quiet:
                    print(f"ERROR     id={rule_id} event={rule.get('event_type')} symbol={rule.get('symbol')} error={exc}")

        save_event_status(status)

        summary = {
            "checked": checked,
            "triggered": triggered,
            "errors": errors,
            "dry_run": bool(args.dry_run),
            "timestamp": now_iso(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            **cache_metrics,
        }
        if args.json:
            print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
        elif not args.quiet:
            print(f"SUMMARY   checked={checked} triggered={triggered} errors={errors} dry_run={bool(args.dry_run)}")
            if args.show_metrics:
                print(
                    "METRICS   "
                    f"duration_ms={summary['duration_ms']} "
                    f"cache_keys={summary['chart_cache_keys']} "
                    f"cache_fetches={summary['chart_cache_fetches']} "
                    f"cache_failures={summary['chart_cache_failures']} "
                    f"cache_reused_rules={summary['chart_cache_reused_rules']}"
                )

        if errors > 0 and args.fail_on_error:
            return 2
        return 0
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
        except Exception:
            pass


def cmd_event_backtest(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    rules = load_event_rules()
    rule_id = str(args.rule_id)
    rule = next((r for r in rules if str(r.get("id")) == rule_id), None)
    if rule is None:
        raise ValueError(f"rule id not found: {rule_id}")

    asset_type = str(rule.get("asset_type", "")).strip().lower()
    period = str(rule.get("period", "")).strip()
    interval = str(rule.get("interval", "")).strip()
    symbol = str(rule.get("quote_symbol") or rule.get("symbol") or "").strip()
    if not symbol:
        raise RuntimeError("selected rule has empty symbol")

    chart_payload = fetch_chart_data(asset_type, symbol, period, interval)
    candles_all = list(chart_payload["candles"])
    if len(candles_all) < 5:
        raise RuntimeError("not enough candles for backtest")

    max_bars = parse_int(args.max_bars, len(candles_all), min_value=5, max_value=len(candles_all))
    candles = candles_all[-max_bars:]

    simulated_payload = dict(chart_payload)
    dedup_mode = str(rule.get("dedup_mode", "cross_once")).strip().lower()
    prev_condition = False
    trigger_points: list[dict[str, Any]] = []
    errors = 0

    for idx in range(4, len(candles)):
        partial = dict(simulated_payload)
        partial["candles"] = candles[: idx + 1]
        dt = partial["candles"][-1]["dt"]
        partial["as_of"] = dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        partial["checked_at"] = partial["as_of"]
        try:
            evaluation = evaluate_event_rule_on_chart(rule, partial)
            condition_now = bool(evaluation.get("condition", False))
            should_trigger = condition_now and (dedup_mode == "continuous" or not prev_condition)
            if should_trigger:
                trigger_points.append(
                    {
                        "index": idx,
                        "as_of": partial["as_of"],
                        "event_type": rule.get("event_type"),
                        "condition": condition_now,
                        "detail": evaluation.get("detail", {}),
                    }
                )
            prev_condition = condition_now
        except Exception:
            errors += 1

    summary = {
        "rule_id": rule_id,
        "event_type": rule.get("event_type"),
        "symbol": chart_payload["symbol"],
        "timeframe": f"{period}/{interval}",
        "bars_used": len(candles),
        "evaluated_steps": max(0, len(candles) - 4),
        "trigger_count": len(trigger_points),
        "errors": errors,
        "first_trigger_as_of": trigger_points[0]["as_of"] if trigger_points else "",
        "last_trigger_as_of": trigger_points[-1]["as_of"] if trigger_points else "",
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }

    if args.json:
        print(json.dumps({"summary": summary, "triggers": trigger_points}, ensure_ascii=False, indent=2))
    else:
        print(
            f"BACKTEST rule={rule_id} event={rule.get('event_type')} symbol={chart_payload['symbol']} "
            f"tf={period}/{interval} bars={len(candles)} steps={summary['evaluated_steps']} "
            f"triggers={len(trigger_points)} errors={errors} duration_ms={summary['duration_ms']}"
        )
        for row in trigger_points[:20]:
            print(f"TRIGGER  idx={row['index']} as_of={row['as_of']}")
        if len(trigger_points) > 20:
            print(f"... and {len(trigger_points) - 20} more triggers")
    return 0


def cmd_install_cron(args: argparse.Namespace) -> int:
    ensure_state_dir()
    schedule = build_cron_schedule(args.minutes, args.cron)
    script_path = Path(args.script_path).expanduser().resolve() if args.script_path else Path(__file__).resolve()

    cmd = (
        f"/usr/bin/env python3 {shlex.quote(str(script_path))} check --quiet "
        f">> {shlex.quote(str(LOG_FILE))} 2>&1"
    )
    managed_job = f"{schedule} {cmd}"

    existing = read_crontab_lines()
    cleaned, _ = strip_managed_cron_block(existing)
    if cleaned and cleaned[-1].strip() != "":
        cleaned.append("")
    cleaned.extend([CRON_BLOCK_START, managed_job, CRON_BLOCK_END])
    write_crontab_lines(cleaned)

    print("CRON_INSTALLED")
    print(f"schedule: {schedule}")
    print(f"job: {managed_job}")
    print(f"log: {LOG_FILE}")
    return 0


def cmd_uninstall_cron(_: argparse.Namespace) -> int:
    existing = read_crontab_lines()
    cleaned, removed = strip_managed_cron_block(existing)
    if not removed:
        print("CRON_NOT_FOUND")
        return 0
    write_crontab_lines(cleaned)
    print("CRON_REMOVED")
    return 0


def build_chart_flags(args: argparse.Namespace) -> dict[str, bool]:
    if args.all_indicators:
        return {
            "sma": True,
            "ema": True,
            "macd": True,
            "rsi": True,
            "bb": True,
            "vol_ma": True,
            "fib": True,
        }

    return {
        "sma": bool(args.sma),
        "ema": bool(args.ema),
        "macd": bool(args.macd),
        "rsi": bool(args.rsi),
        "bb": bool(args.bb),
        "vol_ma": bool(args.vol_ma),
        "fib": bool(args.fib),
    }


def resolve_chart_defaults(asset_type: str, period: str, interval: str) -> tuple[str, str]:
    out_period = period.strip() if period else ""
    out_interval = interval.strip() if interval else ""

    if asset_type == "stock":
        if not out_period:
            out_period = "6mo"
        if not out_interval:
            out_interval = "1d"
    else:
        if not out_period:
            out_period = "5d"
        if not out_interval:
            out_interval = "15m"

    return out_period, out_interval


def cmd_chart(args: argparse.Namespace) -> int:
    asset_type = args.type
    if asset_type == "auto":
        asset_type = resolve_asset_type(args.symbol)

    if bool(args.channel) ^ bool(args.target):
        raise ValueError("--channel and --target must be provided together")

    period, interval = resolve_chart_defaults(asset_type, args.period, args.interval)
    period, interval, auto_note = validate_chart_period_interval(asset_type, period, interval)

    chart_payload = fetch_chart_data(asset_type, args.symbol, period, interval)
    flags = build_chart_flags(args)
    indicators = compute_indicators(chart_payload["candles"], flags)

    out_path = Path(args.out).expanduser() if args.out else default_chart_path(chart_payload["symbol"], period, interval, args.chart_type)
    render_chart_png(
        chart_payload=chart_payload,
        indicators=indicators,
        chart_type=args.chart_type,
        show_volume=not args.no_volume,
        show_rsi=flags.get("rsi", False),
        show_macd=flags.get("macd", False),
        out_path=out_path,
        width=float(args.width),
        height=float(args.height),
        dpi=int(args.dpi),
    )

    summary_lines = build_indicator_summary(chart_payload, indicators)
    if auto_note:
        summary_lines.append(f"Note: {auto_note}")
    summary_lines.append(f"Chart Path: {out_path}")

    delivered = False
    if args.channel and args.target:
        message = args.message or f"{chart_payload['symbol']} chart generated ({period}/{interval})."
        delivered = send_media_notification(args.channel, args.target, message, out_path, dry_run=args.dry_run_send)

    if args.json:
        payload = {
            "chart": {
                "path": str(out_path),
                "asset_type": asset_type,
                "symbol": chart_payload["symbol"],
                "period": period,
                "interval": interval,
                "source": chart_payload["source"],
                "as_of": chart_payload["as_of"],
                "note": auto_note,
            },
            "summary": summary_lines,
            "delivery": {
                "attempted": bool(args.channel and args.target),
                "ok": delivered,
                "dry_run": bool(args.dry_run_send),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n".join(summary_lines))
        print(f"CHART_PATH:{out_path}")
        if args.channel and args.target:
            print(f"DELIVERY:{'OK' if delivered else 'FAILED'} channel={args.channel} target={args.target} dry_run={bool(args.dry_run_send)}")

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    if not args.all_indicators:
        args.all_indicators = True

    # Default to candlestick in report mode.
    args.chart_type = "candlestick"
    rc = cmd_chart(args)
    return rc


# ----------------------- Parser -----------------------

def add_chart_like_args(parser: argparse.ArgumentParser, include_type: bool = True) -> None:
    if include_type:
        parser.add_argument("--type", choices=["auto", "crypto", "stock"], default="auto")
    parser.add_argument("symbol", help="Asset symbol, e.g. BTC or AAPL")
    parser.add_argument("--period", default="", help="Chart range period")
    parser.add_argument("--interval", default="", help="Chart interval")
    parser.add_argument("--out", default="", help="Output PNG path")
    parser.add_argument("--width", type=float, default=16.0, help="Figure width")
    parser.add_argument("--height", type=float, default=9.0, help="Figure height")
    parser.add_argument("--dpi", type=int, default=160, help="PNG DPI")

    parser.add_argument("--sma", action="store_true", help="Enable SMA20/SMA50")
    parser.add_argument("--ema", action="store_true", help="Enable EMA12/EMA26")
    parser.add_argument("--macd", action="store_true", help="Enable MACD(12,26,9)")
    parser.add_argument("--rsi", action="store_true", help="Enable RSI14")
    parser.add_argument("--bb", action="store_true", help="Enable Bollinger Bands(20,2)")
    parser.add_argument("--vol-ma", action="store_true", help="Enable Volume MA20")
    parser.add_argument("--fib", action="store_true", help="Enable Fibonacci retracement levels")
    parser.add_argument("--all-indicators", action="store_true", help="Enable all supported indicators")
    parser.add_argument("--no-volume", action="store_true", help="Hide volume panel")

    parser.add_argument("--channel", default="", help="Delivery channel (optional)")
    parser.add_argument("--target", default="", help="Delivery target (optional)")
    parser.add_argument("--message", default="", help="Message text when delivering chart")
    parser.add_argument("--dry-run-send", action="store_true", help="Print send command without delivery")
    parser.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crypto/stock alert helper with fallback providers and chart generation")
    sub = parser.add_subparsers(dest="command", required=True)

    p_quote = sub.add_parser("quote", help="Fetch current quote")
    p_quote.add_argument("symbol", help="Asset symbol, e.g. BTC or AAPL")
    p_quote.add_argument("--type", choices=["auto", "crypto", "stock"], default="auto")
    p_quote.add_argument("--json", action="store_true")
    p_quote.set_defaults(func=cmd_quote)

    p_add = sub.add_parser("add", help="Add an alert")
    p_add.add_argument("--type", choices=["crypto", "stock"], required=True)
    p_add.add_argument("--symbol", required=True)
    group = p_add.add_mutually_exclusive_group(required=True)
    group.add_argument("--above", type=float)
    group.add_argument("--below", type=float)
    p_add.add_argument("--channel", default="", help="message channel, e.g. telegram")
    p_add.add_argument("--target", default="", help="channel target, e.g. @name or chat id")
    p_add.add_argument("--note", default="")
    p_add.add_argument("--repeat", choices=["edge", "continuous"], default="edge", help="edge: notify only on crossing, continuous: notify every check while condition is true")
    p_add.add_argument("--json", action="store_true")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List configured alerts")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("rm", help="Remove an alert by id")
    p_rm.add_argument("id")
    p_rm.set_defaults(func=cmd_rm)

    p_check = sub.add_parser("check", help="Evaluate all alerts and send notifications")
    p_check.add_argument("--dry-run", action="store_true")
    p_check.add_argument("--quiet", action="store_true")
    p_check.add_argument("--json", action="store_true")
    p_check.add_argument("--fail-on-error", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_event_add = sub.add_parser("event-add", help="Add an event reminder rule")
    p_event_add.add_argument("--event-type", choices=EVENT_TYPE_CHOICES, required=True)
    p_event_add.add_argument("--type", choices=["auto", "crypto", "stock"], default="auto")
    p_event_add.add_argument("--symbol", required=True)
    p_event_add.add_argument("--period", default="", help="Rule timeframe period")
    p_event_add.add_argument("--interval", default="", help="Rule timeframe interval")
    p_event_add.add_argument("--confirm-bars", type=int, default=1, help="Require signal confirmation over N bars")
    p_event_add.add_argument("--hist-expand-bars", type=int, default=3, help="Bars used by MACD histogram expansion events (>=2)")
    p_event_add.add_argument("--lookback-bars", type=int, default=20, help="Lookback bars for breakout/squeeze/volume events")
    p_event_add.add_argument("--bb-width-threshold", type=float, default=0.06, help="BB squeeze threshold (bandwidth ratio)")
    p_event_add.add_argument("--volume-spike-multiplier", type=float, default=1.8, help="Volume spike multiplier vs MA20")
    p_event_add.add_argument("--volume-dry-threshold", type=float, default=0.6, help="Volume dry-up threshold vs MA20")
    p_event_add.add_argument("--fib-anchor-bars", type=int, default=120, help="Fibonacci anchor lookback bars")
    p_event_add.add_argument("--fib-touch-tolerance", type=float, default=0.002, help="Fibonacci touch tolerance ratio")
    p_event_add.add_argument("--pivot-left", type=int, default=3, help="Pivot left bars for swing/divergence")
    p_event_add.add_argument("--pivot-right", type=int, default=3, help="Pivot right bars for swing/divergence")
    p_event_add.add_argument("--min-pivot-gap", type=int, default=5, help="Minimum bars between two pivots")
    p_event_add.add_argument("--max-pivot-gap", type=int, default=120, help="Maximum bars between two pivots")
    p_event_add.add_argument("--min-price-delta-pct", type=float, default=0.3, help="Minimum price delta percent for divergence")
    p_event_add.add_argument("--min-indicator-delta", type=float, default=0.1, help="Minimum indicator delta for divergence")
    p_event_add.add_argument("--dedup-window-bars", type=int, default=20, help="Recent-window bars for divergence re-arm")
    p_event_add.add_argument("--cooldown-minutes", type=int, default=60, help="Minimum minutes between triggers")
    p_event_add.add_argument("--dedup-mode", choices=["cross_once", "continuous"], default="cross_once")
    p_event_add.add_argument("--macd-profile", choices=["auto", "standard", "fast_crypto", "slow_trend", "user_7_10_30", "custom"], default="auto")
    p_event_add.add_argument("--macd-fast", type=int, default=None)
    p_event_add.add_argument("--macd-slow", type=int, default=None)
    p_event_add.add_argument("--macd-signal", type=int, default=None)
    p_event_add.add_argument("--severity", choices=EVENT_SEVERITY_CHOICES, default="auto")
    p_event_add.add_argument("--attach-chart", action="store_true", help="Attach chart snapshot on trigger")
    p_event_add.add_argument("--snapshot-chart-type", choices=["candlestick", "line"], default="candlestick")
    p_event_add.add_argument("--snapshot-width", type=float, default=14.0)
    p_event_add.add_argument("--snapshot-height", type=float, default=8.0)
    p_event_add.add_argument("--snapshot-dpi", type=int, default=150)
    p_event_add.add_argument("--channel", default="", help="message channel, e.g. telegram")
    p_event_add.add_argument("--target", default="", help="channel target, e.g. @name or chat id")
    p_event_add.add_argument("--note", default="")
    p_event_add.add_argument("--json", action="store_true")
    p_event_add.set_defaults(func=cmd_event_add)

    p_event_list = sub.add_parser("event-list", help="List event reminder rules")
    p_event_list.add_argument("--json", action="store_true")
    p_event_list.set_defaults(func=cmd_event_list)

    p_event_rm = sub.add_parser("event-rm", help="Remove an event rule by id")
    p_event_rm.add_argument("id")
    p_event_rm.set_defaults(func=cmd_event_rm)

    p_event_check = sub.add_parser("event-check", help="Evaluate event rules and send notifications")
    p_event_check.add_argument("--dry-run", action="store_true")
    p_event_check.add_argument("--quiet", action="store_true")
    p_event_check.add_argument("--json", action="store_true")
    p_event_check.add_argument("--show-metrics", action="store_true", help="Print cache/duration metrics in text mode")
    p_event_check.add_argument("--fail-on-error", action="store_true")
    p_event_check.set_defaults(func=cmd_event_check)

    p_event_backtest = sub.add_parser("event-backtest", help="Backtest one event rule on historical candles")
    p_event_backtest.add_argument("--rule-id", required=True, help="Event rule id from event-list")
    p_event_backtest.add_argument("--max-bars", type=int, default=500, help="Maximum latest bars to simulate")
    p_event_backtest.add_argument("--json", action="store_true")
    p_event_backtest.set_defaults(func=cmd_event_backtest)

    p_event_preset = sub.add_parser("event-install-preset", help="Install a preset bundle of event rules (idempotent)")
    p_event_preset.add_argument("--preset", choices=EVENT_PRESET_CHOICES, required=True)
    p_event_preset.add_argument("--type", choices=["auto", "crypto", "stock"], default="auto")
    p_event_preset.add_argument("--symbol", required=True)
    p_event_preset.add_argument("--period", default="")
    p_event_preset.add_argument("--interval", default="")
    p_event_preset.add_argument("--confirm-bars", type=int, default=1)
    p_event_preset.add_argument("--hist-expand-bars", type=int, default=3)
    p_event_preset.add_argument("--lookback-bars", type=int, default=20)
    p_event_preset.add_argument("--bb-width-threshold", type=float, default=0.06)
    p_event_preset.add_argument("--volume-spike-multiplier", type=float, default=1.8)
    p_event_preset.add_argument("--volume-dry-threshold", type=float, default=0.6)
    p_event_preset.add_argument("--fib-anchor-bars", type=int, default=120)
    p_event_preset.add_argument("--fib-touch-tolerance", type=float, default=0.002)
    p_event_preset.add_argument("--pivot-left", type=int, default=3)
    p_event_preset.add_argument("--pivot-right", type=int, default=3)
    p_event_preset.add_argument("--min-pivot-gap", type=int, default=5)
    p_event_preset.add_argument("--max-pivot-gap", type=int, default=120)
    p_event_preset.add_argument("--min-price-delta-pct", type=float, default=0.3)
    p_event_preset.add_argument("--min-indicator-delta", type=float, default=0.1)
    p_event_preset.add_argument("--dedup-window-bars", type=int, default=20)
    p_event_preset.add_argument("--cooldown-minutes", type=int, default=60)
    p_event_preset.add_argument("--dedup-mode", choices=["cross_once", "continuous"], default="cross_once")
    p_event_preset.add_argument("--macd-profile", choices=["auto", "standard", "fast_crypto", "slow_trend", "user_7_10_30", "custom"], default="auto")
    p_event_preset.add_argument("--macd-fast", type=int, default=None)
    p_event_preset.add_argument("--macd-slow", type=int, default=None)
    p_event_preset.add_argument("--macd-signal", type=int, default=None)
    p_event_preset.add_argument("--severity", choices=EVENT_SEVERITY_CHOICES, default="auto")
    p_event_preset.add_argument("--attach-chart", action="store_true")
    p_event_preset.add_argument("--snapshot-chart-type", choices=["candlestick", "line"], default="candlestick")
    p_event_preset.add_argument("--snapshot-width", type=float, default=14.0)
    p_event_preset.add_argument("--snapshot-height", type=float, default=8.0)
    p_event_preset.add_argument("--snapshot-dpi", type=int, default=150)
    p_event_preset.add_argument("--channel", default="")
    p_event_preset.add_argument("--target", default="")
    p_event_preset.add_argument("--note", default="")
    p_event_preset.add_argument("--json", action="store_true")
    p_event_preset.set_defaults(func=cmd_event_install_preset)

    p_install = sub.add_parser("install-cron", help="Install managed crontab entry")
    p_install.add_argument("--minutes", type=int, default=5, help="check interval in minutes (1..59)")
    p_install.add_argument("--cron", default="", help="custom cron expr, overrides --minutes")
    p_install.add_argument("--script-path", default="", help="override script path in cron job")
    p_install.set_defaults(func=cmd_install_cron)

    p_uninstall = sub.add_parser("uninstall-cron", help="Remove managed crontab entry")
    p_uninstall.set_defaults(func=cmd_uninstall_cron)

    p_chart = sub.add_parser("chart", help="Generate chart image with optional indicators")
    add_chart_like_args(p_chart, include_type=True)
    p_chart.add_argument("--chart-type", choices=["candlestick", "line"], default="candlestick")
    p_chart.set_defaults(func=cmd_chart)

    p_report = sub.add_parser("report", help="Generate chart + full technical indicator summary")
    add_chart_like_args(p_report, include_type=True)
    p_report.set_defaults(func=cmd_report, all_indicators=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
