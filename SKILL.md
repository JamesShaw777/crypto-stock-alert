---
name: crypto-stock-alert
description: 获取 crypto 与股票价格、设置阈值告警、定期检查、并生成K线/技术指标图（SMA/EMA/MACD/RSI/BB/Fibonacci）。Use when users ask for price alerts like "BTC above 50000", stock/crypto chart generation, or indicator-based quick reports.
---

# Crypto Stock Alert

Monitor crypto/stocks, trigger alerts, and generate chart images with technical indicators.

## Core Script

```bash
python3 {baseDir}/scripts/market_alert.py --help
```

State files:

- `~/.openclaw/skills-data/crypto-stock-alert/alerts.json`
- `~/.openclaw/skills-data/crypto-stock-alert/status.json`
- `~/.openclaw/skills-data/crypto-stock-alert/check.log`
- `~/.openclaw/skills-data/crypto-stock-alert/charts/`

## Price + Alert Commands

### Quote

```bash
python3 {baseDir}/scripts/market_alert.py quote BTC --type crypto
python3 {baseDir}/scripts/market_alert.py quote AAPL --type stock
```

### Add Alert

```bash
# BTC > 50000
python3 {baseDir}/scripts/market_alert.py add \
  --type crypto --symbol BTC --above 50000 \
  --channel telegram --target @your_chat

# AAPL < 200
python3 {baseDir}/scripts/market_alert.py add \
  --type stock --symbol AAPL --below 200 \
  --channel telegram --target @your_chat

# BTC > 50000 and notify every check while above threshold
python3 {baseDir}/scripts/market_alert.py add \
  --type crypto --symbol BTC --above 50000 \
  --channel telegram --target @your_chat \
  --repeat continuous
```

### Check / List / Remove

```bash
python3 {baseDir}/scripts/market_alert.py check --dry-run
python3 {baseDir}/scripts/market_alert.py check
python3 {baseDir}/scripts/market_alert.py list
python3 {baseDir}/scripts/market_alert.py rm <alert_id>
```

### Periodic Check

```bash
python3 {baseDir}/scripts/market_alert.py install-cron --minutes 5
python3 {baseDir}/scripts/market_alert.py uninstall-cron
```

## Chart Generation

Use `chart` for image output and optional indicator overlays.

```bash
python3 {baseDir}/scripts/market_alert.py chart AAPL --type stock --period 6mo --interval 1d --all-indicators
python3 {baseDir}/scripts/market_alert.py chart BTC --type crypto --period 5d --interval 15m --all-indicators
```

### Stock constraints

- `--period` must be one of: `1d 5d 1mo 3mo 6mo 1y`
- Common intervals: `15m 30m 60m 90m 1d 1wk`

### Crypto constraints

- Interval options: `15m 30m 60m 90m 1d 1wk`
- Minimum granularity is **15m**

### Indicator flags

- `--sma` : SMA20/SMA50
- `--ema` : EMA12/EMA26
- `--macd`: MACD(12,26,9)
- `--rsi` : RSI14
- `--bb`  : Bollinger Bands(20,2)
- `--vol-ma`: Volume MA20
- `--fib` : Fibonacci retracement
- `--all-indicators` : enable all indicators

## Quick Report

`report` generates chart + full indicator summary.

```bash
python3 {baseDir}/scripts/market_alert.py report BTC --type crypto --period 5d --interval 15m
```

## Data Source Fallback

### Quote

- Crypto: Yahoo -> CoinGecko -> Coinbase -> Binance
- Stock: Yahoo -> Nasdaq -> Stooq

### Chart

- Crypto: Yahoo OHLCV -> Binance klines
- Stock: Yahoo OHLCV -> Stooq history (daily/weekly fallback)

## Natural Language Mapping

When user says:

- "设置一个警告，当比特币价格超过50000美元时提醒我"

Action sequence:

1. Add alert (`type=crypto symbol=BTC above=50000`)
2. Ensure periodic check (`install-cron --minutes 5`)
3. Run immediate check (`check --dry-run`)

When user says:

- "给我比特币15分钟K线，带MACD和斐波拉契"

Action sequence:

1. Build chart command: `chart BTC --type crypto --period 5d --interval 15m --macd --fib`
2. Run and return `CHART_PATH`
3. If requested, send image via channel/target

## Behavior Notes

- Default mode is `edge`: notify only on false->true crossing.
- Use `--repeat continuous` to notify every check while condition is true.
- Duplicate concurrent `check` runs are lock-protected.
- Cron environments may have minimal PATH; script auto-resolves `openclaw` binary and supports `OPENCLAW_BIN` override.
- Chart/report requires `matplotlib`; if missing, use venv install.
