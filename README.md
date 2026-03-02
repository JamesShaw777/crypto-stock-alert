# crypto-stock-alert

OpenClaw skill + Python CLI for:

- Crypto and stock price lookup
- Threshold alerts (`above` / `below`)
- Event-based reminders (Phase 2 MACD set)
- Scheduled checks via cron
- Chart image generation (candlestick/line)
- Technical indicators (SMA, EMA, MACD, RSI, Bollinger Bands, Fibonacci)

Typical requests this skill handles:

- "Alert me when BTC is above 50,000"
- "Show me AAPL candlestick chart with MACD + RSI"
- "Generate a BTC 15m chart with Fibonacci levels"

## Features

- Unified workflow for crypto + stocks
- Multi-source fallback for both quote and chart data
- Edge-triggered alerts to avoid repeated spam
- Lock protection for concurrent `check` executions
- Lock protection for concurrent `event-check` executions
- PNG chart output with indicator overlays
- Optional delivery via `openclaw message send --media`

## Repository Structure

- `SKILL.md` - OpenClaw skill metadata and invocation guidance
- `scripts/market_alert.py` - Main CLI
- `openclaw_crypto_stock_alert_skill.md` - Design notes (Chinese)
- `docs/EVENT_ALERTS_TODO.md` - phased event-reminder implementation backlog

## Roadmap

Event reminder expansion (MACD/RSI/MA/BB/Volume/Fibonacci/divergence) is tracked in:

- `docs/EVENT_ALERTS_TODO.md`

All new event features are implemented in phases, and docs are updated after each phase.

Currently implemented event types (Phase 2):

- `macd_golden_cross`
- `macd_dead_cross`
- `macd_golden_cross_above_zero`
- `macd_dead_cross_below_zero`
- `macd_zero_cross_up`
- `macd_zero_cross_down`
- `macd_hist_turn_positive`
- `macd_hist_turn_negative`
- `macd_hist_expand_up_n`
- `macd_hist_expand_down_n`

## Requirements

- Python 3.9+
- OpenClaw CLI in `PATH`
- `crontab` for periodic checks
- Network access to market data APIs

For chart/report commands, install `matplotlib` in a virtualenv:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install matplotlib
```

Then run chart/report with `.venv/bin/python` or activate the venv first.

## Quick Start

### 1) Quote price

```bash
python3 scripts/market_alert.py quote BTC --type crypto
python3 scripts/market_alert.py quote AAPL --type stock
```

### 2) Add alerts

```bash
# BTC > 50000
python3 scripts/market_alert.py add \
  --type crypto --symbol BTC --above 50000 \
  --channel telegram --target @your_chat

# AAPL < 200
python3 scripts/market_alert.py add \
  --type stock --symbol AAPL --below 200 \
  --channel telegram --target @your_chat
```

If `--channel` and `--target` are omitted, alerts are still evaluated, but output stays local.

### 3) Check alerts now

```bash
python3 scripts/market_alert.py check --dry-run
python3 scripts/market_alert.py check
```

### 4) Install periodic checks

```bash
python3 scripts/market_alert.py install-cron --minutes 5
python3 scripts/market_alert.py uninstall-cron
```

### 5) Add event reminder rules (Phase 2 MACD)

```bash
# MACD golden cross, crypto 15m, using your requested 7/10/30 profile
python3 scripts/market_alert.py event-add \
  --event-type macd_golden_cross \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --macd-profile user_7_10_30 \
  --confirm-bars 1 \
  --cooldown-minutes 30

# MACD dead cross, stock daily
python3 scripts/market_alert.py event-add \
  --event-type macd_dead_cross \
  --type stock --symbol AAPL \
  --period 3mo --interval 1d \
  --macd-profile standard

# MACD histogram expanding up for N bars (crypto 15m)
python3 scripts/market_alert.py event-add \
  --event-type macd_hist_expand_up_n \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --macd-profile user_7_10_30 \
  --hist-expand-bars 4
```

### 6) Check/list/remove event rules

```bash
python3 scripts/market_alert.py event-list
python3 scripts/market_alert.py event-check --dry-run
python3 scripts/market_alert.py event-rm <RULE_ID>
```

### 7) Generate charts

```bash
# Stock (all indicators)
.venv/bin/python scripts/market_alert.py chart AAPL --type stock --period 6mo --interval 1d --all-indicators

# Crypto (15m minimum precision)
.venv/bin/python scripts/market_alert.py chart BTC --type crypto --period 5d --interval 15m --all-indicators
```

### 8) Generate quick technical report

```bash
.venv/bin/python scripts/market_alert.py report BTC --type crypto --period 5d --interval 15m
```

## Commands

### `quote`

```bash
python3 scripts/market_alert.py quote <SYMBOL> [--type auto|crypto|stock] [--json]
```

### `add`

```bash
python3 scripts/market_alert.py add \
  --type crypto|stock \
  --symbol <SYMBOL> \
  (--above <PRICE> | --below <PRICE>) \
  [--channel <CHANNEL>] [--target <TARGET>] [--note <TEXT>] [--json]
```

Rules:

- `--above` and `--below` are mutually exclusive
- Threshold must be `> 0`
- `--channel` and `--target` must be set together

### `list`

```bash
python3 scripts/market_alert.py list [--json]
```

### `rm`

```bash
python3 scripts/market_alert.py rm <ALERT_ID>
```

### `check`

```bash
python3 scripts/market_alert.py check [--dry-run] [--quiet] [--json] [--fail-on-error]
```

### `event-add`

```bash
python3 scripts/market_alert.py event-add \
  --event-type <MACD_EVENT_TYPE> \
  --type auto|crypto|stock \
  --symbol <SYMBOL> \
  [--period PERIOD] [--interval INTERVAL] \
  [--confirm-bars N] \
  [--hist-expand-bars N] \
  [--cooldown-minutes N] \
  [--dedup-mode cross_once|continuous] \
  [--macd-profile auto|standard|fast_crypto|slow_trend|user_7_10_30|custom] \
  [--macd-fast N --macd-slow N --macd-signal N] \
  [--channel CHANNEL --target TARGET] [--note TEXT] [--json]
```

`<MACD_EVENT_TYPE>` choices:

- `macd_golden_cross`
- `macd_dead_cross`
- `macd_golden_cross_above_zero`
- `macd_dead_cross_below_zero`
- `macd_zero_cross_up`
- `macd_zero_cross_down`
- `macd_hist_turn_positive`
- `macd_hist_turn_negative`
- `macd_hist_expand_up_n`
- `macd_hist_expand_down_n`

### `event-list`

```bash
python3 scripts/market_alert.py event-list [--json]
```

### `event-rm`

```bash
python3 scripts/market_alert.py event-rm <RULE_ID>
```

### `event-check`

```bash
python3 scripts/market_alert.py event-check [--dry-run] [--quiet] [--json] [--fail-on-error]
```

### `install-cron`

```bash
python3 scripts/market_alert.py install-cron [--minutes N] [--cron "EXPR"] [--script-path PATH]
```

### `uninstall-cron`

```bash
python3 scripts/market_alert.py uninstall-cron
```

### `chart`

```bash
.venv/bin/python scripts/market_alert.py chart <SYMBOL> \
  [--type auto|crypto|stock] \
  [--period PERIOD] [--interval INTERVAL] \
  [--chart-type candlestick|line] \
  [--sma] [--ema] [--macd] [--rsi] [--bb] [--vol-ma] [--fib] [--all-indicators] \
  [--no-volume] \
  [--out PATH] [--dpi N] [--width N] [--height N] \
  [--channel CHANNEL --target TARGET --message TEXT] [--dry-run-send] [--json]
```

### `report`

`report` behaves like `chart` but enforces a full indicator summary and outputs a chart path.

```bash
.venv/bin/python scripts/market_alert.py report <SYMBOL> [chart/report options]
```

## Market Data Fallback

### Quote fallback

- Crypto: `Yahoo -> CoinGecko -> Coinbase -> Binance`
- Stock: `Yahoo -> Nasdaq -> Stooq`

### Chart fallback

- Crypto: `Yahoo OHLCV -> Binance klines`
- Stock: `Yahoo OHLCV -> Stooq history` (daily/weekly fallback)

## Timeframe and Precision Rules

### Stocks

Allowed `--period` values:

- `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`

Allowed chart intervals:

- `15m`, `30m`, `60m`, `90m`, `1d`, `1wk`

### Crypto

Allowed `--period` values:

- `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`

Allowed chart intervals:

- `15m`, `30m`, `60m`, `90m`, `1d`, `1wk`

Constraint:

- Crypto minimum interval precision is **15m**

Note:

- If intraday interval is requested with periods longer than 60 days, interval may auto-adjust to `1d` because Yahoo intraday history is limited.

## Indicator Set

Supported indicators:

- `SMA20`, `SMA50`
- `EMA12`, `EMA26`
- `MACD(12,26,9)`
- `RSI14`
- `Bollinger Bands(20,2)`
- `Volume MA20`
- `Fibonacci retracement`

## Alert Semantics

Alerts are edge-triggered:

- Notify only when condition changes from `false -> true`
- If price stays above/below threshold, no repeated notification
- If condition resets and crosses again, new notification is sent

`check` is lock-protected (`check.lock`) to avoid duplicate triggers under concurrent execution.

Event reminders follow rule-level dedup/cooldown settings:

- `dedup_mode=cross_once`: trigger on new condition crossing only
- `dedup_mode=continuous`: trigger while condition remains true (respecting cooldown)
- `cooldown_minutes`: minimum spacing between repeated event notifications

`event-check` is lock-protected (`event_check.lock`) to avoid duplicate triggers under concurrent execution.

## State Files

Default directory:

```text
~/.openclaw/skills-data/crypto-stock-alert/
```

Files:

- `alerts.json` - alert rules
- `status.json` - latest condition/check state
- `event_rules.json` - event reminder rules
- `event_status.json` - latest event-check state per rule
- `check.log` - cron check output
- `check.lock` - runtime lock for `check`
- `event_check.lock` - runtime lock for `event-check`
- `charts/` - generated PNG files

Override state directory:

```bash
export OPENCLAW_MARKET_ALERT_STATE_DIR=/custom/path
```

## OpenClaw Intent Mapping

Example request:

> "Set an alert when BTC exceeds 50,000 and check every 5 minutes."

Execution mapping:

1. `add --type crypto --symbol BTC --above 50000`
2. `install-cron --minutes 5`
3. `check --dry-run`

Example request:

> "Generate a BTC 15m candlestick chart with MACD and Fibonacci."

Execution mapping:

1. `chart BTC --type crypto --period 5d --interval 15m --macd --fib`
2. Return `CHART_PATH`
3. If asked, deliver via `--channel/--target`

Example request:

> "Remind me when BTC MACD gives a golden cross on 15m using 7/10/30."

Execution mapping:

1. `event-add --event-type macd_golden_cross --type crypto --symbol BTC --period 5d --interval 15m --macd-profile user_7_10_30`
2. `event-check --dry-run`
3. Schedule periodic checks by running `event-check` via cron or heartbeat workflow

## Troubleshooting

### No alert delivery

- Verify alert has `channel` and `target`
- Test direct send path:

```bash
openclaw message send --channel telegram --target @your_chat --message "test"
```

### Chart command fails with matplotlib error

Install in venv and run with venv Python:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install matplotlib
python scripts/market_alert.py chart BTC --type crypto --period 5d --interval 15m
```

### Cron not running

```bash
crontab -l
tail -n 200 ~/.openclaw/skills-data/crypto-stock-alert/check.log
```

## Disclaimer

This project is for automation and monitoring workflows. It is not investment advice.
