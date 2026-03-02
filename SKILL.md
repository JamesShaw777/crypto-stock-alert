---
name: crypto-stock-alert
description: 获取 crypto 与股票价格、设置阈值告警、定期检查、并生成K线/技术指标图（SMA/EMA/MACD/RSI/BB/Fibonacci）。支持 61 类事件提醒（MACD/RSI/MA/BB/Volume/Breakout/Fib/背离）、preset 一键安装与事件回测。Use when users ask for threshold alerts, indicator/divergence event reminders, preset strategy bundles, historical event backtests, stock/crypto chart generation, or indicator-based quick reports.
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
- `~/.openclaw/skills-data/crypto-stock-alert/event_rules.json`
- `~/.openclaw/skills-data/crypto-stock-alert/event_status.json`
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

## Event Reminder Commands (Phase 1-7 Complete)

Current implemented event types:

- MACD family: cross/zero/hist + MACD divergence
- RSI family: threshold/cross + RSI divergence
- MA family: price-vs-MA crosses + MA alignment
- Bollinger family: touch/outside/re-enter/squeeze
- Volume family: spike/dry-up + OBV MA cross/divergence
- Breakout family: N-bar, Donchian, swing break
- Fibonacci family: touch/reject/break at key retracement levels
- Total event types: `61`

### Add Event Rule

```bash
# MACD golden cross with user profile 7/10/30 on crypto 15m
python3 {baseDir}/scripts/market_alert.py event-add \
  --event-type macd_golden_cross \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --macd-profile user_7_10_30 \
  --confirm-bars 1 \
  --cooldown-minutes 30 \
  --dedup-mode cross_once \
  --channel telegram --target @your_chat

# MACD dead cross on stock daily
python3 {baseDir}/scripts/market_alert.py event-add \
  --event-type macd_dead_cross \
  --type stock --symbol AAPL \
  --period 3mo --interval 1d \
  --macd-profile standard

# MACD histogram expansion up for 4 bars on crypto 15m
python3 {baseDir}/scripts/market_alert.py event-add \
  --event-type macd_hist_expand_up_n \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --macd-profile user_7_10_30 \
  --hist-expand-bars 4

# RSI divergence with explicit pivot params
python3 {baseDir}/scripts/market_alert.py event-add \
  --event-type rsi_regular_bull_div \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --pivot-left 3 --pivot-right 3 \
  --min-pivot-gap 5 --max-pivot-gap 120 \
  --min-price-delta-pct 0.3 --min-indicator-delta 0.1 \
  --dedup-window-bars 20

# Attach snapshot and severity tag
python3 {baseDir}/scripts/market_alert.py event-add \
  --event-type breakout_n_bar_high \
  --type crypto --symbol BTC \
  --period 5d --interval 15m \
  --attach-chart \
  --severity critical
```

### Check / List / Remove Event Rules

```bash
python3 {baseDir}/scripts/market_alert.py event-list
python3 {baseDir}/scripts/market_alert.py event-check --dry-run --show-metrics
python3 {baseDir}/scripts/market_alert.py event-check
python3 {baseDir}/scripts/market_alert.py event-backtest --rule-id <rule_id> --max-bars 400
python3 {baseDir}/scripts/market_alert.py event-rm <rule_id>
```

### Install Event Preset Bundles

```bash
python3 {baseDir}/scripts/market_alert.py event-install-preset \
  --preset preset_crypto_momentum_15m \
  --type crypto --symbol BTC \
  --period 5d --interval 15m
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

When user says:

- "15分钟BTC MACD出现金叉就提醒我，参数用7 10 30"

Action sequence:

1. Add event rule: `event-add --event-type macd_golden_cross --type crypto --symbol BTC --period 5d --interval 15m --macd-profile user_7_10_30`
2. Run immediate dry-run: `event-check --dry-run`
3. If recurring monitoring is needed, schedule `event-check` periodically

When user says:

- "直接给我装一套BTC 15m动量事件"

Action sequence:

1. Install preset bundle: `event-install-preset --preset preset_crypto_momentum_15m --type crypto --symbol BTC --period 5d --interval 15m`
2. Run quick validation: `event-check --dry-run`
3. Optional historical replay: `event-backtest --rule-id <id> --max-bars 400`

## Behavior Notes

- Default mode is `edge`: notify only on false->true crossing.
- Use `--repeat continuous` to notify every check while condition is true.
- Duplicate concurrent `check` runs are lock-protected.
- `event-check` uses separate lock protection to avoid duplicate event triggers.
- `event-check` reuses shared chart cache per symbol/timeframe to reduce duplicated fetches.
- `event-check --show-metrics` prints cache reuse and duration metrics in text mode.
- `event-backtest` provides deterministic historical replay for one saved event rule.
- `event-install-preset` installs event bundles idempotently.
- Event notifications support standardized severity tags and optional chart snapshots.
- Cron environments may have minimal PATH; script auto-resolves `openclaw` binary and supports `OPENCLAW_BIN` override.
- Chart/report requires `matplotlib`; if missing, use venv install.

## Event Reminder Roadmap

For full rollout status and completion checklist of advanced event reminders, track:

- `docs/EVENT_ALERTS_TODO.md`

Update this roadmap and `README.md` after each phase is implemented.
