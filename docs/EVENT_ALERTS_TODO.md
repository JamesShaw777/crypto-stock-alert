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

Status: `pending`

- [ ] Add persistent rule store for event rules (separate from threshold alert rules)
- [ ] Add event runtime state store (last condition / last trigger / cooldown state)
- [ ] Add common rule fields:
  - [ ] `event_type`
  - [ ] `asset_type`
  - [ ] `symbol`
  - [ ] `period`
  - [ ] `interval`
  - [ ] `confirm_bars`
  - [ ] `cooldown_minutes`
  - [ ] `dedup_mode`
  - [ ] `channel` / `target`
- [ ] Add lock-safe event check flow (same safety level as existing `check`)
- [ ] Add baseline commands:
  - [ ] `event-add`
  - [ ] `event-list`
  - [ ] `event-rm`
  - [ ] `event-check`

Acceptance Criteria:

- [ ] Create/list/remove/check event rules works without impacting existing alert commands
- [ ] Event rule state survives process restart
- [ ] No duplicate triggers under concurrent checks

## Indicator Event Phases

### Phase 2: MACD Events + MACD Parameter Presets

Status: `pending`

- [ ] Add MACD parameter profiles:
  - [ ] `macd_standard` (12,26,9)
  - [ ] `macd_fast_crypto` (8,21,5)
  - [ ] `macd_slow_trend` (19,39,9)
  - [ ] `macd_user_7_10_30` (7,10,30)
  - [ ] `macd_custom` (user-defined)
- [ ] Add MACD events:
  - [ ] `macd_golden_cross`
  - [ ] `macd_dead_cross`
  - [ ] `macd_golden_cross_above_zero`
  - [ ] `macd_dead_cross_below_zero`
  - [ ] `macd_zero_cross_up`
  - [ ] `macd_zero_cross_down`
  - [ ] `macd_hist_turn_positive`
  - [ ] `macd_hist_turn_negative`
  - [ ] `macd_hist_expand_up_n`
  - [ ] `macd_hist_expand_down_n`

Acceptance Criteria:

- [ ] Events can be backtested on historical candles deterministically
- [ ] Live check outputs include event context and indicator values

### Phase 3: RSI + MA + Bollinger + Volume Events

Status: `pending`

RSI:

- [ ] `rsi_cross_30_up`
- [ ] `rsi_cross_70_down`
- [ ] `rsi_enter_overbought`
- [ ] `rsi_enter_oversold`
- [ ] `rsi_cross_50_up`
- [ ] `rsi_cross_50_down`

Moving Average / Trend:

- [ ] `price_cross_sma20_up`
- [ ] `price_cross_sma20_down`
- [ ] `price_cross_ema20_up`
- [ ] `price_cross_ema20_down`
- [ ] `ema20_cross_ema50_up`
- [ ] `ema20_cross_ema50_down`
- [ ] `ma_bull_alignment`
- [ ] `ma_bear_alignment`

Bollinger:

- [ ] `bb_touch_upper`
- [ ] `bb_touch_lower`
- [ ] `bb_close_outside_upper`
- [ ] `bb_close_outside_lower`
- [ ] `bb_reenter_from_upper`
- [ ] `bb_reenter_from_lower`
- [ ] `bb_squeeze_start`
- [ ] `bb_squeeze_breakout_up`
- [ ] `bb_squeeze_breakout_down`

Volume:

- [ ] `volume_spike_up`
- [ ] `volume_spike_down`
- [ ] `volume_dry_up`
- [ ] `obv_cross_ma_up`
- [ ] `obv_cross_ma_down`

Acceptance Criteria:

- [ ] Each event has deterministic trigger definition and parameter validation
- [ ] Event-check output explains why trigger happened

### Phase 4: Breakout + Fibonacci Events

Status: `pending`

Breakout/Structure:

- [ ] `breakout_n_bar_high`
- [ ] `breakdown_n_bar_low`
- [ ] `donchian_breakout_up`
- [ ] `donchian_breakout_down`
- [ ] `swing_high_break`
- [ ] `swing_low_break`

Fibonacci:

- [ ] `fib_touch_0_382`
- [ ] `fib_touch_0_5`
- [ ] `fib_touch_0_618`
- [ ] `fib_reject_0_618_up`
- [ ] `fib_reject_0_618_down`
- [ ] `fib_break_0_618_up`
- [ ] `fib_break_0_618_down`

Acceptance Criteria:

- [ ] Pivot/level anchors are explicit and reproducible
- [ ] Triggers include level, direction, and confirmation context

### Phase 5: Divergence Events

Status: `pending`

Regular divergence:

- [ ] `rsi_regular_bull_div`
- [ ] `rsi_regular_bear_div`
- [ ] `macd_regular_bull_div`
- [ ] `macd_regular_bear_div`
- [ ] `obv_regular_bull_div`
- [ ] `obv_regular_bear_div`

Hidden divergence:

- [ ] `rsi_hidden_bull_div`
- [ ] `rsi_hidden_bear_div`
- [ ] `macd_hidden_bull_div`
- [ ] `macd_hidden_bear_div`

Divergence engine parameters:

- [ ] `pivot_left`
- [ ] `pivot_right`
- [ ] `min_pivot_gap`
- [ ] `max_pivot_gap`
- [ ] `min_price_delta_pct`
- [ ] `min_indicator_delta`
- [ ] `confirm_bars`
- [ ] `dedup_window_bars`

Acceptance Criteria:

- [ ] Divergence detection is deterministic for same OHLCV input
- [ ] False-positive control parameters are configurable per rule

## Presets and UX

### Phase 6: Preset Bundles

Status: `pending`

- [ ] `preset_stock_trend`
- [ ] `preset_stock_reversal`
- [ ] `preset_crypto_momentum_15m`
- [ ] `preset_crypto_divergence_15m`
- [ ] `preset_fib_pullback`
- [ ] `preset_breakout_follow`

Acceptance Criteria:

- [ ] One command can install a bundle of event rules
- [ ] Bundle install is idempotent

### Phase 7: Delivery and Message Templates

Status: `pending`

- [ ] Add standardized event message templates with parameter details
- [ ] Add chart snapshot attach option for event triggers
- [ ] Add per-event severity tag (`info`/`warning`/`critical`)

Acceptance Criteria:

- [ ] Event notifications are concise and context-complete
- [ ] Optional chart attachment is reliable

## Constraints Already Confirmed

- Stock common periods are restricted to: `1d 5d 1mo 3mo 6mo 1y`
- Crypto minimum interval precision is `15m`

## Current Priority Queue

1. Phase 1 (event rule model + commands)
2. Phase 2 (MACD events + parameter presets including `7,10,30`)
3. Phase 3 (RSI/MA/BB/Volume)
4. Phase 5 (divergence)
5. Phase 4 and 6/7 (breakout/fib bundles + delivery polish)

## Change Log (Implementation Progress)

- 2026-03-02: Created phased TODO and implementation checklist.
