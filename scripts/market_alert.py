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

EVENT_TYPE_CHOICES = (
    "macd_golden_cross",
    "macd_dead_cross",
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


def evaluate_macd_cross_event(
    event_type: str,
    macd_line: list[float | None],
    signal_line: list[float | None],
    confirm_bars: int,
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

    if macd_line[pre] is None or signal_line[pre] is None:
        detail["reason"] = "insufficient_indicator_history"
        return False, detail

    for idx in range(start, n):
        if macd_line[idx] is None or signal_line[idx] is None:
            detail["reason"] = "insufficient_indicator_history"
            return False, detail

    pre_macd = float(macd_line[pre])  # type: ignore[arg-type]
    pre_sig = float(signal_line[pre])  # type: ignore[arg-type]
    last_macd = float(macd_line[-1])  # type: ignore[arg-type]
    last_sig = float(signal_line[-1])  # type: ignore[arg-type]

    if event_type == "macd_golden_cross":
        condition = pre_macd <= pre_sig and all(float(macd_line[idx]) > float(signal_line[idx]) for idx in range(start, n))
    elif event_type == "macd_dead_cross":
        condition = pre_macd >= pre_sig and all(float(macd_line[idx]) < float(signal_line[idx]) for idx in range(start, n))
    else:
        raise RuntimeError(f"unsupported event type: {event_type}")

    detail.update(
        {
            "pre_macd": pre_macd,
            "pre_signal": pre_sig,
            "last_macd": last_macd,
            "last_signal": last_sig,
            "reason": "ok" if condition else "condition_false",
        }
    )
    return condition, detail


def evaluate_event_rule(rule: dict[str, Any]) -> dict[str, Any]:
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

    chart_payload = fetch_chart_data(asset_type, chart_symbol, period, interval)
    candles = chart_payload["candles"]
    closes = [float(c["close"]) for c in candles]

    confirm_bars = max(1, int(rule.get("confirm_bars", 1)))
    if event_type in ("macd_golden_cross", "macd_dead_cross"):
        fast, slow, signal, profile = extract_macd_params(rule)
        macd_line, signal_line, hist_line = macd_series_custom(closes, fast, slow, signal)
        condition, detail = evaluate_macd_cross_event(event_type, macd_line, signal_line, confirm_bars)
        detail["macd_profile"] = profile
        detail["macd_fast"] = fast
        detail["macd_slow"] = slow
        detail["macd_signal"] = signal
        detail["last_hist"] = last_valid(hist_line)
    else:
        raise RuntimeError(f"unsupported event type: {event_type}")

    return {
        "event_type": event_type,
        "condition": bool(condition),
        "chart": {
            "symbol": chart_payload["symbol"],
            "period": period,
            "interval": interval,
            "source": chart_payload["source"],
            "as_of": chart_payload["as_of"],
            "checked_at": chart_payload["checked_at"],
        },
        "detail": detail,
    }


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

    parts = [
        f"[EVENT ALERT] {chart.get('symbol', rule.get('symbol'))} {event_type}",
        f"tf={chart.get('period')}/{chart.get('interval')}",
        f"source={chart.get('source')}",
        f"as_of={chart.get('as_of')}",
        f"id={rule.get('id')}",
    ]

    if event_type in ("macd_golden_cross", "macd_dead_cross"):
        lm = detail.get("last_macd")
        ls = detail.get("last_signal")
        lh = detail.get("last_hist")
        profile = detail.get("macd_profile")
        spans = f"{detail.get('macd_fast')},{detail.get('macd_slow')},{detail.get('macd_signal')}"
        if isinstance(lm, (int, float)) and isinstance(ls, (int, float)):
            parts.append(f"macd={float(lm):.6f}")
            parts.append(f"signal={float(ls):.6f}")
        if isinstance(lh, (int, float)):
            parts.append(f"hist={float(lh):.6f}")
        if profile:
            parts.append(f"profile={profile}:{spans}")
        parts.append(f"confirm={detail.get('confirm_bars')}")

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

    params: dict[str, Any] = {}
    if event_type in ("macd_golden_cross", "macd_dead_cross"):
        params = resolve_macd_profile_params(asset_type, args.macd_profile, args.macd_fast, args.macd_slow, args.macd_signal)

    rules = load_event_rules()
    for existing in rules:
        if (
            bool(existing.get("enabled", True))
            and str(existing.get("event_type", "")).lower() == event_type
            and str(existing.get("asset_type", "")).lower() == asset_type
            and str(existing.get("symbol", "")) == symbol_for_rule
            and str(existing.get("period", "")) == period
            and str(existing.get("interval", "")) == interval
            and int(existing.get("confirm_bars", 1)) == confirm_bars
            and int(existing.get("cooldown_minutes", 0)) == cooldown_minutes
            and str(existing.get("dedup_mode", "cross_once")).lower() == dedup_mode
            and str(existing.get("channel", "")) == str(args.channel or "")
            and str(existing.get("target", "")) == str(args.target or "")
            and existing.get("params", {}) == params
        ):
            if args.json:
                print(json.dumps(existing, ensure_ascii=False, indent=2))
            else:
                print(f"EXISTS {existing.get('id')} {event_type} {asset_type} {symbol_for_rule} {period}/{interval}")
            return 0

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
        "params": params,
        "channel": args.channel or "",
        "target": args.target or "",
        "note": args.note or "",
        "enabled": True,
        "created_at": now_iso(),
    }
    rules.append(rule)
    save_event_rules(rules)

    if args.json:
        payload = {"rule": rule, "note": auto_note}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        dest = f"{rule['channel']}:{rule['target']}" if rule["channel"] and rule["target"] else "local-log-only"
        print(
            f"EVENT_ADDED {rule['id']} {rule['event_type']} {rule['asset_type']} {rule['symbol']} "
            f"tf={rule['period']}/{rule['interval']} confirm={rule['confirm_bars']} cooldown={rule['cooldown_minutes']}m "
            f"dedup={rule['dedup_mode']} -> {dest}"
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

    print("ID       EVENT_TYPE            TYPE    SYMBOL     TF               CONF  CD(min)  DEDUP       DESTINATION              ENABLED")
    for rule in rules:
        tf = f"{rule.get('period')}/{rule.get('interval')}"
        dest = f"{rule.get('channel')}:{rule.get('target')}" if rule.get("channel") and rule.get("target") else "local-log-only"
        print(
            f"{str(rule.get('id','')):8} {str(rule.get('event_type','')):20} {str(rule.get('asset_type','')):7} "
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
        rules = load_event_rules()
        status = load_event_status()

        triggered = 0
        checked = 0
        errors = 0
        results: list[dict[str, Any]] = []

        for rule in rules:
            if not bool(rule.get("enabled", True)):
                continue

            checked += 1
            rule_id = str(rule.get("id"))
            previous = status.get(rule_id, {})
            prev_condition = bool(previous.get("last_condition", False))

            try:
                evaluation = evaluate_event_rule(rule)
                condition_now = bool(evaluation.get("condition", False))

                dedup_mode = str(rule.get("dedup_mode", "cross_once")).strip().lower()
                base_trigger = condition_now and (dedup_mode == "continuous" or not prev_condition)
                cooldown_minutes = max(0, int(rule.get("cooldown_minutes", 0)))
                cooldown_ok = can_trigger_with_cooldown(str(previous.get("last_triggered_at", "")), cooldown_minutes)
                should_notify = base_trigger and cooldown_ok

                message = ""
                delivered = False
                if should_notify:
                    message = format_event_message(rule, evaluation)
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
    p_event_add.add_argument("--cooldown-minutes", type=int, default=60, help="Minimum minutes between triggers")
    p_event_add.add_argument("--dedup-mode", choices=["cross_once", "continuous"], default="cross_once")
    p_event_add.add_argument("--macd-profile", choices=["auto", "standard", "fast_crypto", "slow_trend", "user_7_10_30", "custom"], default="auto")
    p_event_add.add_argument("--macd-fast", type=int, default=None)
    p_event_add.add_argument("--macd-slow", type=int, default=None)
    p_event_add.add_argument("--macd-signal", type=int, default=None)
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
    p_event_check.add_argument("--fail-on-error", action="store_true")
    p_event_check.set_defaults(func=cmd_event_check)

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
