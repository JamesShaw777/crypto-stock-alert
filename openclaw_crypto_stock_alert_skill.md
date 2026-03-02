# OpenClaw Skill 落地说明：Crypto + Stock Alert + K线/指标生图

## 目标范围

本 skill 现在支持三大模块：

1. 价格告警模块（quote/add/check/cron）
2. 图表分析模块（chart/report）
3. 事件提醒模块（event-add/event-list/event-rm/event-check/event-backtest/event-install-preset，Phase 1-7）

事件提醒扩展的分阶段计划见：

- `docs/EVENT_ALERTS_TODO.md`

## 已实现能力

### A. 价格告警

- crypto 与股票实时报价
- 阈值告警（above / below）
- 定期检查（cron）
- 触发方式为边沿触发（false -> true）
- 文件锁防并发重复触发

### B. 生图与技术指标

- 生成 PNG 图（candlestick 或 line）
- 技术指标：
  - SMA20/SMA50
  - EMA12/EMA26
  - MACD(12,26,9)
  - RSI14
  - Bollinger Bands(20,2)
  - Volume MA20
  - Fibonacci 回撤
- `report` 命令输出图 + 指标摘要

### C. 事件提醒（Phase 1-7 全量）

- 独立事件规则存储：`event_rules.json`
- 独立事件状态存储：`event_status.json`
- 独立锁防并发：`event_check.lock`
- 当前支持事件（共 61 个）：
  - MACD 家族（含 `golden/dead/zero/hist` + MACD 背离）
  - RSI 家族（含阈值/穿越 + RSI 背离）
  - MA 家族（价格与均线穿越 + 多空排列）
  - Bollinger 家族（触碰/外穿/回归/挤压）
  - Volume/OBV 家族（量能 spike/dry-up + OBV 交叉/背离）
  - Breakout 家族（N-bar/Donchian/swing break）
  - Fibonacci 家族（touch/reject/break）
- `macd_hist_expand_*` 事件支持 `--hist-expand-bars` 参数
- 支持 MACD 参数预设：
  - `standard`
  - `fast_crypto`
  - `slow_trend`
  - `user_7_10_30`
  - `custom`
- 支持 preset 一键安装：
  - `preset_stock_trend`
  - `preset_stock_reversal`
  - `preset_crypto_momentum_15m`
  - `preset_crypto_divergence_15m`
  - `preset_fib_pullback`
  - `preset_breakout_follow`
- 支持 `event-backtest` 历史回放
- 支持事件通知 `severity` 标签与可选快照附件（`--attach-chart`）

## 你确认的约束已落地

### 1) 股票常见周期

股票 `--period` 限制为：

- `1d 5d 1mo 3mo 6mo 1y`

### 2) Crypto 最小精度 15min

crypto `--interval` 最小支持到：

- `15m`（并支持 `30m 60m 90m 1d 1wk`）

## 数据源与 fallback

### Quote

- Crypto: Yahoo -> CoinGecko -> Coinbase -> Binance
- Stock: Yahoo -> Nasdaq -> Stooq

### Chart

- Crypto: Yahoo OHLCV -> Binance klines
- Stock: Yahoo OHLCV -> Stooq history（daily/weekly fallback）

## 核心命令

```bash
# 价格
python3 scripts/market_alert.py quote BTC --type crypto

# 告警
python3 scripts/market_alert.py add --type crypto --symbol BTC --above 50000
python3 scripts/market_alert.py check --dry-run
python3 scripts/market_alert.py install-cron --minutes 5

# 股票K线 + 全指标
.venv/bin/python scripts/market_alert.py chart AAPL --type stock --period 6mo --interval 1d --all-indicators

# Crypto 15m K线 + MACD + 斐波拉契
.venv/bin/python scripts/market_alert.py chart BTC --type crypto --period 5d --interval 15m --macd --fib

# 一键报告
.venv/bin/python scripts/market_alert.py report BTC --type crypto --period 5d --interval 15m

# 事件规则：BTC 15m MACD 金叉（7/10/30）
python3 scripts/market_alert.py event-add --event-type macd_golden_cross --type crypto --symbol BTC --period 5d --interval 15m --macd-profile user_7_10_30

# 事件规则：BTC 15m MACD 柱体连续放大 4 根
python3 scripts/market_alert.py event-add --event-type macd_hist_expand_up_n --type crypto --symbol BTC --period 5d --interval 15m --macd-profile user_7_10_30 --hist-expand-bars 4

# 预设：BTC 15m 动量事件包（一键安装，幂等）
python3 scripts/market_alert.py event-install-preset --preset preset_crypto_momentum_15m --type crypto --symbol BTC --period 5d --interval 15m

# 回放：对某条规则做历史回测
python3 scripts/market_alert.py event-backtest --rule-id <RULE_ID> --max-bars 400

python3 scripts/market_alert.py event-check --dry-run
python3 scripts/market_alert.py event-list
```

## 依赖说明

- 告警模块仅依赖 Python 标准库
- 生图模块需 `matplotlib`，建议使用 venv 安装
