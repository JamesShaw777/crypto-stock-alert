#!/usr/bin/env python3
"""OpenClaw market alert helper for crypto and stocks.

Features:
- Fetch quotes with multi-provider fallback
- Manage threshold alerts (above/below)
- Periodic checks with edge-triggered notifications (crossing threshold)
- Install/uninstall a managed system crontab entry
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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

CRON_BLOCK_START = "# OPENCLAW_CRYPTO_STOCK_ALERT_START"
CRON_BLOCK_END = "# OPENCLAW_CRYPTO_STOCK_ALERT_END"

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


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ts_to_iso(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return now_iso()


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


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


def acquire_check_lock() -> Any:
    ensure_state_dir()
    handle = LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("another check process is already running") from exc
    return handle


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
        providers: list[Callable[[], tuple[float, str, str]]] = [
            lambda: fetch_from_yahoo_chart(quote_symbol),
            lambda: fetch_from_coingecko(base),
            lambda: fetch_from_coinbase(base),
            lambda: fetch_from_binance(base),
        ]
        resolved_symbol = quote_symbol
    else:
        resolved_symbol = normalize_stock_symbol(symbol)
        providers = [
            lambda: fetch_from_yahoo_chart(resolved_symbol),
            lambda: fetch_from_nasdaq(resolved_symbol),
            lambda: fetch_from_stooq(resolved_symbol),
        ]

    for provider in providers:
        try:
            price, as_of, source = provider()
            return {
                "asset_type": asset_type,
                "input_symbol": symbol,
                "symbol": resolved_symbol,
                "price": float(price),
                "source": source,
                "as_of": as_of,
                "checked_at": now_iso(),
            }
        except Exception as exc:
            provider_name = getattr(provider, "__name__", "provider")
            errors.append(f"{provider_name}: {exc}")

    raise RuntimeError("all providers failed: " + " | ".join(errors))


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


def send_notification(alert: dict[str, Any], message: str, dry_run: bool = False, quiet: bool = False) -> bool:
    channel = (alert.get("channel") or "").strip()
    target = (alert.get("target") or "").strip()

    if not channel or not target:
        if not quiet:
            print(f"LOCAL_ALERT {alert['id']}: {message}")
        return True

    cmd = [
        "openclaw",
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

    proc = subprocess.run(cmd, capture_output=True, text=True)
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

    print("ID       TYPE    SYMBOL     RULE             DESTINATION              ENABLED   CREATED_AT")
    for alert in alerts:
        rule = f"{alert.get('direction')} {alert.get('threshold')}"
        dest = f"{alert.get('channel')}:{alert.get('target')}" if alert.get("channel") and alert.get("target") else "local-log-only"
        print(
            f"{str(alert.get('id','')):8} {str(alert.get('asset_type','')):7} {str(alert.get('symbol','')):10} "
            f"{rule:16} {dest:24} {str(alert.get('enabled', True)):8} {str(alert.get('created_at',''))}"
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
                just_triggered = condition_now and not prev_condition

                message = ""
                delivered = False
                if just_triggered:
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
                    "last_triggered_at": now_iso() if just_triggered else previous.get("last_triggered_at", ""),
                    "last_triggered_price": quote["price"] if just_triggered else previous.get("last_triggered_price"),
                    "last_delivery_ok": delivered if just_triggered else previous.get("last_delivery_ok"),
                }

                row = {
                    "id": alert_id,
                    "symbol": quote["symbol"],
                    "price": quote["price"],
                    "threshold": alert.get("threshold"),
                    "direction": alert.get("direction"),
                    "condition": condition_now,
                    "triggered": just_triggered,
                    "source": quote["source"],
                    "checked_at": quote["checked_at"],
                    "error": "",
                }
                results.append(row)

                if not args.quiet:
                    state_txt = "TRIGGERED" if just_triggered else ("ARMED" if condition_now else "WAIT")
                    print(
                        f"{state_txt:9} id={alert_id} symbol={quote['symbol']} price={quote['price']:.6f} "
                        f"rule={alert.get('direction')} {float(alert.get('threshold')):.6f} source={quote['source']}"
                    )
                    if just_triggered and message:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crypto/stock alert helper with fallback providers")
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

    p_install = sub.add_parser("install-cron", help="Install managed crontab entry")
    p_install.add_argument("--minutes", type=int, default=5, help="check interval in minutes (1..59)")
    p_install.add_argument("--cron", default="", help="custom cron expr, overrides --minutes")
    p_install.add_argument("--script-path", default="", help="override script path in cron job")
    p_install.set_defaults(func=cmd_install_cron)

    p_uninstall = sub.add_parser("uninstall-cron", help="Remove managed crontab entry")
    p_uninstall.set_defaults(func=cmd_uninstall_cron)

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
