# Event Alerts TODO (Phased Implementation)

This document tracks the rollout of event-based reminders for the `crypto-stock-alert` skill.

## Scope

Implement reliable, configurable event reminders beyond simple price-threshold alerts, including:

- MACD / RSI / MA / Bollinger / Volume / Breakout / Fibonacci events
- Divergence detection (RSI/MACD/OBV)
- Preset parameter profiles and preset event bundles
- Stateful dedup, cooldown, and confirmation logic

## Implementation Rules

1. Implement in small phases and keep backward compatibility for existing commands.
2. Update docs after each phase:
   - `README.md`
   - `SKILL.md`
   - this TODO file status checkboxes
3. Every phase requires:
   - command-level validation
   - dry-run verification output
   - rollback-safe storage changes

## Event Engine Foundation

### Phase 1: Rule Model + Runtime Framework

Status: `completed`

- [x] Add persistent rule store for event rules (separate from threshold alert rules)
- [x] Add event runtime state store (last condition / last trigger / cooldown state)
- [x] Add common rule fields:
  - [x] `event_type`
  - [x] `asset_type`
  - [x] `symbol`
  - [x] `period`
  - [x] `interval`
  - [x] `confirm_bars`
  - [x] `cooldown_minutes`
  - [x] `dedup_mode`
  - [x] `channel` / `target`
- [x] Add lock-safe event check flow (same safety level as existing `check`)
- [x] Add baseline commands:
  - [x] `event-add`
  - [x] `event-list`
  - [x] `event-rm`
  - [x] `event-check`

Acceptance Criteria:

- [x] Create/list/remove/check event rules works without impacting existing alert commands
- [x] Event rule state survives process restart
- [x] No duplicate triggers under concurrent checks

## Indicator Event Phases

### Phase 2: MACD Events + MACD Parameter Presets

Status: `completed`

- [x] Add MACD parameter profiles:
  - [x] `macd_standard` (12,26,9)
  - [x] `macd_fast_crypto` (8,21,5)
  - [x] `macd_slow_trend` (19,39,9)
  - [x] `macd_user_7_10_30` (7,10,30)
  - [x] `macd_custom` (user-defined)
- [x] Add MACD events:
  - [x] `macd_golden_cross`
  - [x] `macd_dead_cross`
  - [x] `macd_golden_cross_above_zero`
  - [x] `macd_dead_cross_below_zero`
  - [x] `macd_zero_cross_up`
  - [x] `macd_zero_cross_down`
  - [x] `macd_hist_turn_positive`
  - [x] `macd_hist_turn_negative`
  - [x] `macd_hist_expand_up_n`
  - [x] `macd_hist_expand_down_n`

Acceptance Criteria:

- [x] Events can be backtested on historical candles deterministically
- [x] Live check outputs include event context and indicator values

### Phase 3: RSI + MA + Bollinger + Volume Events

Status: `completed`

RSI:

- [x] `rsi_cross_30_up`
- [x] `rsi_cross_70_down`
- [x] `rsi_enter_overbought`
- [x] `rsi_enter_oversold`
- [x] `rsi_cross_50_up`
- [x] `rsi_cross_50_down`

Moving Average / Trend:

- [x] `price_cross_sma20_up`
- [x] `price_cross_sma20_down`
- [x] `price_cross_ema20_up`
- [x] `price_cross_ema20_down`
- [x] `ema20_cross_ema50_up`
- [x] `ema20_cross_ema50_down`
- [x] `ma_bull_alignment`
- [x] `ma_bear_alignment`

Bollinger:

- [x] `bb_touch_upper`
- [x] `bb_touch_lower`
- [x] `bb_close_outside_upper`
- [x] `bb_close_outside_lower`
- [x] `bb_reenter_from_upper`
- [x] `bb_reenter_from_lower`
- [x] `bb_squeeze_start`
- [x] `bb_squeeze_breakout_up`
- [x] `bb_squeeze_breakout_down`

Volume:

- [x] `volume_spike_up`
- [x] `volume_spike_down`
- [x] `volume_dry_up`
- [x] `obv_cross_ma_up`
- [x] `obv_cross_ma_down`

Acceptance Criteria:

- [x] Each event has deterministic trigger definition and parameter validation
- [x] Event-check output explains why trigger happened

### Phase 4: Breakout + Fibonacci Events

Status: `completed`

Breakout/Structure:

- [x] `breakout_n_bar_high`
- [x] `breakdown_n_bar_low`
- [x] `donchian_breakout_up`
- [x] `donchian_breakout_down`
- [x] `swing_high_break`
- [x] `swing_low_break`

Fibonacci:

- [x] `fib_touch_0_382`
- [x] `fib_touch_0_5`
- [x] `fib_touch_0_618`
- [x] `fib_reject_0_618_up`
- [x] `fib_reject_0_618_down`
- [x] `fib_break_0_618_up`
- [x] `fib_break_0_618_down`

Acceptance Criteria:

- [x] Pivot/level anchors are explicit and reproducible
- [x] Triggers include level, direction, and confirmation context

### Phase 5: Divergence Events

Status: `completed`

Regular divergence:

- [x] `rsi_regular_bull_div`
- [x] `rsi_regular_bear_div`
- [x] `macd_regular_bull_div`
- [x] `macd_regular_bear_div`
- [x] `obv_regular_bull_div`
- [x] `obv_regular_bear_div`

Hidden divergence:

- [x] `rsi_hidden_bull_div`
- [x] `rsi_hidden_bear_div`
- [x] `macd_hidden_bull_div`
- [x] `macd_hidden_bear_div`

Divergence engine parameters:

- [x] `pivot_left`
- [x] `pivot_right`
- [x] `min_pivot_gap`
- [x] `max_pivot_gap`
- [x] `min_price_delta_pct`
- [x] `min_indicator_delta`
- [x] `confirm_bars`
- [x] `dedup_window_bars`

Acceptance Criteria:

- [x] Divergence detection is deterministic for same OHLCV input
- [x] False-positive control parameters are configurable per rule

## Presets and UX

### Phase 6: Preset Bundles

Status: `completed`

- [x] `preset_stock_trend`
- [x] `preset_stock_reversal`
- [x] `preset_crypto_momentum_15m`
- [x] `preset_crypto_divergence_15m`
- [x] `preset_fib_pullback`
- [x] `preset_breakout_follow`

Acceptance Criteria:

- [x] One command can install a bundle of event rules
- [x] Bundle install is idempotent

### Phase 7: Delivery and Message Templates

Status: `completed`

- [x] Add standardized event message templates with parameter details
- [x] Add chart snapshot attach option for event triggers
- [x] Add per-event severity tag (`info`/`warning`/`critical`)

Acceptance Criteria:

- [x] Event notifications are concise and context-complete
- [x] Optional chart attachment is reliable

## Constraints Already Confirmed

- Stock common periods are restricted to: `1d 5d 1mo 3mo 6mo 1y`
- Crypto minimum interval precision is `15m`

## Current Priority Queue

1. Regression coverage expansion (unit/integration tests for each event family)
2. Runtime optimization (shared candle cache across rules in one `event-check` pass)
3. Optional rule import/export helpers
4. Optional visualization for backtest trigger timeline

## Change Log (Implementation Progress)

- 2026-03-02: Created phased TODO and implementation checklist.
- 2026-03-02: Completed Phase 1 event-rule foundation (`event-add/list/rm/check`, dedicated stores, lock-safe runtime).
- 2026-03-02: Started Phase 2 with MACD profiles + `macd_golden_cross` and `macd_dead_cross`.
- 2026-03-02: Completed remaining Phase 2 MACD events (`above/below zero`, `zero cross`, `hist turn`, `hist expand`).
- 2026-03-02: Added `--hist-expand-bars` and richer MACD event messages with indicator context.
- 2026-03-02: Completed Phase 3 event families (`RSI`, `MA`, `Bollinger`, `Volume/OBV`).
- 2026-03-02: Completed Phase 4 event families (`Breakout`, `Fibonacci`).
- 2026-03-02: Completed Phase 5 divergence families (regular + hidden; RSI/MACD/OBV support).
- 2026-03-02: Completed Phase 6 via `event-install-preset` (idempotent preset bundle installs).
- 2026-03-02: Completed Phase 7 via standardized severity-tagged messages and optional snapshot attachments (`--attach-chart`).
- 2026-03-02: Added deterministic rule replay command `event-backtest`.
