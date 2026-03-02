# crypto-stock-alert

OpenClaw skill + Python CLI for:

- Crypto and stock price lookup
- Threshold alerts (`above` / `below`)
- Event-based reminders (Phase 1-7 completed)
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

All event phases are now completed (Phase 1-7), and follow-up improvements are tracked in the same TODO file.

Current event engine coverage:

- MACD events (10 types)
- RSI events (6 types)
- MA/Trend events (8 types)
- Bollinger events (9 types)
- Volume/OBV events (5 types)
- Breakout/structure events (6 types)
- Fibonacci events (7 types)
- Divergence events (10 types)
- Total implemented event types: `61`

Additional event tooling:

- `event-backtest` for deterministic historical replay
- `event-install-preset` for idempotent bundle installs
- Per-rule severity (`info`/`warning`/`critical` via `--severity`)
- Optional chart snapshot delivery on trigger (`--attach-chart`)

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

### 5) Add event reminder rules (all event families)

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

# RSI crossover event
python3 scripts/market_alert.py event-add \
  --event-type rsi_cross_50_up \
  --type crypto --symbol BTC \
  --period 5d --interval 15m

# Divergence event with configurable pivot params
python3 scripts/market_alert.py event-add \
  --event-type rsi_regular_bull_div \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --pivot-left 3 --pivot-right 3 \
  --min-pivot-gap 5 --max-pivot-gap 120 \
  --min-price-delta-pct 0.3 --min-indicator-delta 0.1 \
  --dedup-window-bars 20

# Trigger with chart snapshot attachment
python3 scripts/market_alert.py event-add \
  --event-type breakout_n_bar_high \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --attach-chart --severity critical
```

### 6) Check/list/remove event rules

```bash
python3 scripts/market_alert.py event-list
python3 scripts/market_alert.py event-check --dry-run
python3 scripts/market_alert.py event-backtest --rule-id <RULE_ID> --max-bars 400
python3 scripts/market_alert.py event-rm <RULE_ID>
```

### 6.1) Install event preset bundles (idempotent)

```bash
python3 scripts/market_alert.py event-install-preset \
  --preset preset_crypto_momentum_15m \
  --type crypto --symbol BTC \
  --period 5d --interval 15m
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
  --event-type <EVENT_TYPE> \
  --type auto|crypto|stock \
  --symbol <SYMBOL> \
  [--period PERIOD] [--interval INTERVAL] \
  [--confirm-bars N] \
  [--hist-expand-bars N] \
  [--lookback-bars N] \
  [--bb-width-threshold X] \
  [--volume-spike-multiplier X] [--volume-dry-threshold X] \
  [--fib-anchor-bars N] [--fib-touch-tolerance X] \
  [--pivot-left N] [--pivot-right N] \
  [--min-pivot-gap N] [--max-pivot-gap N] \
  [--min-price-delta-pct X] [--min-indicator-delta X] \
  [--dedup-window-bars N] \
  [--cooldown-minutes N] \
  [--dedup-mode cross_once|continuous] \
  [--macd-profile auto|standard|fast_crypto|slow_trend|user_7_10_30|custom] \
  [--macd-fast N --macd-slow N --macd-signal N] \
  [--severity auto|info|warning|critical] \
  [--attach-chart] [--snapshot-chart-type candlestick|line] \
  [--snapshot-width N] [--snapshot-height N] [--snapshot-dpi N] \
  [--channel CHANNEL --target TARGET] [--note TEXT] [--json]
```

`<EVENT_TYPE>` families:

- MACD: `macd_*` (cross/zero/hist + divergence)
- RSI: `rsi_*` (threshold/cross + divergence)
- MA/Trend: `price_cross_*`, `ema20_cross_ema50_*`, `ma_*_alignment`
- Bollinger: `bb_touch_*`, `bb_close_outside_*`, `bb_reenter_*`, `bb_squeeze_*`
- Volume/OBV: `volume_*`, `obv_cross_ma_*`, `obv_regular_*_div`
- Breakout: `breakout_n_bar_high`, `breakdown_n_bar_low`, `donchian_*`, `swing_*_break`
- Fibonacci: `fib_touch_*`, `fib_reject_*`, `fib_break_*`

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
python3 scripts/market_alert.py event-check [--dry-run] [--quiet] [--json] [--show-metrics] [--prefetch-workers N] [--fail-on-error]
```

### `event-backtest`

```bash
python3 scripts/market_alert.py event-backtest --rule-id <RULE_ID> [--max-bars N] [--json]
```

### `event-install-preset`

```bash
python3 scripts/market_alert.py event-install-preset \
  --preset preset_stock_trend|preset_stock_reversal|preset_crypto_momentum_15m|\
preset_crypto_divergence_15m|preset_fib_pullback|preset_breakout_follow \
  --type auto|crypto|stock \
  --symbol <SYMBOL> \
  [--period PERIOD] [--interval INTERVAL] \
  [preset/event parameters...]
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
- `event-backtest`: replay one saved rule across historical candles deterministically
- `event-install-preset`: install preset bundles idempotently
- `--severity`: tag event message as `info`/`warning`/`critical` (or `auto`)
- `--attach-chart`: generate and send chart snapshot together with event message
- Event checks reuse shared chart cache per `asset+symbol+timeframe` key to reduce duplicate API fetches
- Use `event-check --show-metrics` (text mode) or `event-check --json` to view cache/duration metrics
- Tune prefetch concurrency with `--prefetch-workers` (or `OPENCLAW_EVENT_PREFETCH_WORKERS`)
- HTTP layer includes retry + pacing safeguards for 429/5xx/network bursts

Optional network tuning env vars:

- `OPENCLAW_HTTP_MAX_RETRIES` (default `2`)
- `OPENCLAW_HTTP_RETRY_BASE_SECONDS` (default `0.4`)
- `OPENCLAW_HTTP_MIN_INTERVAL_SECONDS` (default `0.12`)

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

Example request:

> "Install a BTC 15m momentum event pack, then backtest one rule."

Execution mapping:

1. `event-install-preset --preset preset_crypto_momentum_15m --type crypto --symbol BTC --period 5d --interval 15m`
2. `event-list` and pick a rule id
3. `event-backtest --rule-id <RULE_ID> --max-bars 400`

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
