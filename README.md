# crypto-stock-alert

OpenClaw skill + CLI helper for monitoring **cryptocurrency** and **stock** prices, with threshold alerts and automatic periodic checks.

This project is designed for prompts like:

- "Alert me when Bitcoin goes above 50,000 USD"
- "Alert me when AAPL drops below 200"

It translates those intents into executable checks and notifications.

## Features

- Monitor both crypto and stocks from one script
- Configure `above` and `below` threshold alerts
- Run one-time checks or scheduled checks
- Deliver notifications through `openclaw message send`
- Built-in data-source fallback per asset class
- Edge-triggered alerts to avoid message spam
- File-lock protection to avoid duplicate triggers from concurrent runs
- No third-party Python dependencies required

## Repository Layout

- `SKILL.md`: OpenClaw skill metadata + workflow guidance
- `scripts/market_alert.py`: Core CLI script
- `openclaw_crypto_stock_alert_skill.md`: Extended design notes (Chinese)

## Requirements

- Python 3.9+
- OpenClaw CLI installed and available in `PATH`
- Network access to market data providers
- `crontab` available (for periodic checks)

## Installation

### Option A: Use as an OpenClaw workspace skill

Place this repository at:

```bash
~/.openclaw/workspace/skills/crypto-stock-alert
```

Then verify:

```bash
openclaw skills info crypto-stock-alert
```

### Option B: Use as a standalone script

Run directly from any directory:

```bash
python3 scripts/market_alert.py --help
```

## Quick Start

### 1) Fetch a quote

```bash
python3 scripts/market_alert.py quote BTC --type crypto
python3 scripts/market_alert.py quote AAPL --type stock
```

### 2) Add an alert

Bitcoin above 50,000:

```bash
python3 scripts/market_alert.py add \
  --type crypto \
  --symbol BTC \
  --above 50000 \
  --channel telegram \
  --target @your_chat
```

AAPL below 200:

```bash
python3 scripts/market_alert.py add \
  --type stock \
  --symbol AAPL \
  --below 200 \
  --channel telegram \
  --target @your_chat
```

If `--channel`/`--target` are omitted, the alert still evaluates, but output is local-only (stdout/log).

### 3) Check alerts immediately

Dry-run (safe test, no outbound sends):

```bash
python3 scripts/market_alert.py check --dry-run
```

Real delivery mode:

```bash
python3 scripts/market_alert.py check
```

### 4) Install periodic checks (every 5 minutes)

```bash
python3 scripts/market_alert.py install-cron --minutes 5
```

Remove managed cron block:

```bash
python3 scripts/market_alert.py uninstall-cron
```

## Command Reference

### `quote`

Get current price with fallback provider chain.

```bash
python3 scripts/market_alert.py quote <SYMBOL> [--type auto|crypto|stock] [--json]
```

Examples:

```bash
python3 scripts/market_alert.py quote BTC --type crypto
python3 scripts/market_alert.py quote ETH-USD --type auto
python3 scripts/market_alert.py quote MSFT --type stock --json
```

### `add`

Create an alert rule.

```bash
python3 scripts/market_alert.py add \
  --type crypto|stock \
  --symbol <SYMBOL> \
  (--above <PRICE> | --below <PRICE>) \
  [--channel <CHANNEL>] \
  [--target <TARGET>] \
  [--note <TEXT>] \
  [--json]
```

Notes:

- `--above` and `--below` are mutually exclusive
- Threshold must be `> 0`
- `--channel` and `--target` must be provided together
- Duplicate active rules are de-duplicated

### `list`

Show configured alerts.

```bash
python3 scripts/market_alert.py list
python3 scripts/market_alert.py list --json
```

### `rm`

Delete one alert by ID.

```bash
python3 scripts/market_alert.py rm <ALERT_ID>
```

### `check`

Evaluate all enabled alerts and send notifications when threshold crossing occurs.

```bash
python3 scripts/market_alert.py check [--dry-run] [--quiet] [--json] [--fail-on-error]
```

Flags:

- `--dry-run`: evaluate and format notifications without sending
- `--quiet`: suppress per-alert log lines
- `--json`: emit machine-readable summary/results
- `--fail-on-error`: non-zero exit when provider checks fail

### `install-cron`

Install a managed cron entry for periodic checks.

```bash
python3 scripts/market_alert.py install-cron [--minutes N] [--cron "EXPR"] [--script-path PATH]
```

Behavior:

- Writes a managed block between:
  - `# OPENCLAW_CRYPTO_STOCK_ALERT_START`
  - `# OPENCLAW_CRYPTO_STOCK_ALERT_END`
- Re-installs cleanly (removes previous managed block first)

### `uninstall-cron`

Remove the managed cron block.

```bash
python3 scripts/market_alert.py uninstall-cron
```

## Data Providers and Fallback Strategy

The script tries providers in sequence and returns the first successful response.

### Crypto quote order

1. Yahoo Finance chart API
2. CoinGecko simple price API
3. Coinbase spot price API
4. Binance ticker API

### Stock quote order

1. Yahoo Finance chart API
2. Nasdaq quote API
3. Stooq CSV API

This design handles common outages such as rate limits or temporary endpoint failures.

## Alert Semantics (Important)

Alerts are **edge-triggered**, not level-triggered.

- Trigger occurs only when condition changes from `false -> true`
- If price stays above/below threshold, no repeated spam on every check
- If price moves back and crosses again later, a new alert is emitted

## Concurrency Safety

`check` uses a file lock (`check.lock`) to prevent duplicate runs at the same time.

If another check is running, a second invocation exits with:

```text
ERROR: another check process is already running
```

## State and Logs

Default state directory:

```text
~/.openclaw/skills-data/crypto-stock-alert/
```

Files:

- `alerts.json`: configured rules
- `status.json`: last check state and trigger state per alert
- `check.log`: cron check output (when installed by `install-cron`)
- `check.lock`: runtime lock file for concurrent check protection

Override state directory via environment variable:

```bash
export OPENCLAW_MARKET_ALERT_STATE_DIR=/custom/path
```

## Symbol Notes

### Crypto

- Accepted forms include aliases such as `BTC`, `XBT`, `bitcoin`, `ETH`, etc.
- Script normalizes crypto to `<BASE>-USD` for primary quoting (for example `BTC-USD`)

### Stocks

- Typical uppercase tickers are expected (`AAPL`, `MSFT`, `NVDA`)

## OpenClaw Conversation Mapping

Natural language request:

> "Set an alert and remind me when BTC is above 50,000 dollars."

Suggested execution sequence:

1. Add rule:

```bash
python3 scripts/market_alert.py add \
  --type crypto --symbol BTC --above 50000 \
  --channel telegram --target @your_chat
```

2. Ensure periodic check:

```bash
python3 scripts/market_alert.py install-cron --minutes 5
```

3. Run an immediate dry-run check and report status:

```bash
python3 scripts/market_alert.py check --dry-run
```

## Troubleshooting

### No notifications received

- Verify `channel`/`target` were set when adding alerts
- Test OpenClaw send path manually:

```bash
openclaw message send --channel telegram --target @your_chat --message "test"
```

- Run check without `--quiet` to inspect delivery output

### Check exits with provider errors

- Re-run with `--json` to inspect failures
- Confirm external APIs are reachable from host
- Keep fallback order unchanged unless you have a known stable in-house source

### Cron not running

- Confirm cron block exists:

```bash
crontab -l
```

- Inspect log:

```bash
tail -n 200 ~/.openclaw/skills-data/crypto-stock-alert/check.log
```

## Development

Quick syntax validation:

```bash
python3 -m py_compile scripts/market_alert.py
```

Inspect CLI options:

```bash
python3 scripts/market_alert.py --help
```

## Disclaimer

This tool is for automation convenience and operational alerts. It is not investment advice.
