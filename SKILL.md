---
name: crypto-stock-alert
description: 获取 crypto 与股票价格并设置阈值提醒（高于/低于），支持定期自动检查、消息推送和数据源 fallback。Use when the user asks to monitor prices like "BTC 超过 50000 提醒我" or "AAPL 跌破 200 提醒我", or asks to create/list/remove price alerts and schedule periodic checks.
---

# Crypto Stock Alert

Use this skill to monitor cryptocurrency and stock prices, then trigger reminders when thresholds are crossed.

## Core Script

Use:

```bash
python3 {baseDir}/scripts/market_alert.py --help
```

State files:

- `~/.openclaw/skills-data/crypto-stock-alert/alerts.json`
- `~/.openclaw/skills-data/crypto-stock-alert/status.json`
- `~/.openclaw/skills-data/crypto-stock-alert/check.log`

## Data Sources (with fallback)

### Crypto

1. Yahoo Finance chart API
2. CoinGecko simple price API
3. Coinbase spot price API
4. Binance ticker API

### Stock

1. Yahoo Finance chart API
2. Nasdaq quote API
3. Stooq CSV API

If one source fails, automatically try the next source.

## Quick Commands

### 1) Get quote

```bash
python3 {baseDir}/scripts/market_alert.py quote BTC --type crypto
python3 {baseDir}/scripts/market_alert.py quote AAPL --type stock
```

### 2) Add alert

```bash
# BTC > 50000
python3 {baseDir}/scripts/market_alert.py add \
  --type crypto --symbol BTC --above 50000 \
  --channel telegram --target @your_chat

# AAPL < 200
python3 {baseDir}/scripts/market_alert.py add \
  --type stock --symbol AAPL --below 200 \
  --channel telegram --target @your_chat
```

If `--channel/--target` are omitted, alerts are still evaluated but only logged locally.

### 3) List/remove alerts

```bash
python3 {baseDir}/scripts/market_alert.py list
python3 {baseDir}/scripts/market_alert.py rm <alert_id>
```

### 4) Check alerts now

```bash
python3 {baseDir}/scripts/market_alert.py check
# safe test without sending messages
python3 {baseDir}/scripts/market_alert.py check --dry-run
```

### 5) Install periodic check

```bash
# every 5 minutes (default)
python3 {baseDir}/scripts/market_alert.py install-cron --minutes 5

# remove managed cron block
python3 {baseDir}/scripts/market_alert.py uninstall-cron
```

## Natural Language Mapping

When user says:

- "设置一个警告，当比特币价格超过50000美元时提醒我"

Do this sequence:

1. Convert intent to command:
   - `type=crypto`, `symbol=BTC`, `direction=above`, `threshold=50000`
2. If channel/target context is available, include `--channel` and `--target`
3. Add alert using `add`
4. Ensure periodic checking is enabled using `install-cron --minutes 5`
5. Run one immediate dry-run check and report result

## Behavior Notes

- Alert is edge-triggered: notify only when condition changes from false to true.
- If price stays above/below threshold, it does not repeatedly spam every check cycle.
- When condition resets and crosses again later, notify again.
- Concurrent `check` runs are lock-protected to avoid duplicate trigger races.
