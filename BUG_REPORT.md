# Strategy & Backtest Calculation Issues

This document summarizes the bugs discovered while reviewing the trading strategy and backtest implementation described in `PROJECT_STRUCTURE.md`.

## 1. Pyramiding limit is never reachable
- **Location**: `llm_trading_system/strategies/indicator_strategy.py`, lines 222-245.
- **Problem**: `IndicatorStrategy._generate_order` refuses to place a new long (or short) order while a position in the same direction is open because the entry condition explicitly checks `current_position <= 0` (long) / `current_position >= 0` (short). Because of this guard the strategy always returns `None` whenever an additional entry would be required, so `_open_positions_count` never exceeds 1.
- **Impact**: The `pyramiding` configuration option is effectively ignored: even if `pyramiding > 1` the strategy can never scale into existing positions. This makes position sizing calculations wrong and prevents any layered entries that TradingView-style scripts rely on.

## 2. `use_martingale` flag is ignored
- **Location**: `llm_trading_system/strategies/configs.py` (definition of `use_martingale`) and `indicator_strategy.py`, lines 250-263.
- **Problem**: `_calculate_position_size` always applies the martingale multiplier via `self.config.martingale_mult ** step` regardless of the `use_martingale` flag. The flag is never referenced anywhere in the code base.
- **Impact**: When a user disables martingale by setting `use_martingale = False`, the strategy still scales the size exponentially (unless the multiplier is manually reset to 1). This leads to unexpected position sizes and invalidates any backtest results that were supposed to be run without martingale.

## 3. TP/SL exits are priced at the bar close instead of the trigger price
- **Location**: `indicator_strategy.py`, lines 278-308, and `llm_trading_system/engine/portfolio.py`, lines 47-106.
- **Problem**: `_check_tp_sl_hit` correctly detects that a stop-loss or take-profit level was touched inside the bar, but once that happens the strategy returns `_close_position()` which produces a generic `side="flat"` order. The portfolio simulator then closes the trade at `bar.close` (plus slippage) inside `_close_position`, completely ignoring the actual TP/SL level that was hit intrabar.
- **Impact**: Backtest PnL is overstated whenever a stop is hit and understated when a target is hit because all exits occur at the bar close rather than the configured level. This breaks the correctness of both trading logic and historical metrics.

## 4. Portfolio simulator cannot resize positions without closing and reopening
- **Location**: `llm_trading_system/engine/portfolio.py`, lines 47-60.
- **Problem**: `process_order` closes any open position before opening a new one whenever the desired target size changes, even if the sign (long/short) stays the same. Adjusting from 1.0 → 0.5 long, or adding to 0.5 → 0.75 long, always results in two full fills (close then open).
- **Impact**: Every size adjustment produces double fees, loses the original entry price, and produces incorrect mark-to-market PnL. This significantly distorts backtests for strategies that change exposure gradually (e.g., when LLM gates scale the size or when pyramiding should add units).
