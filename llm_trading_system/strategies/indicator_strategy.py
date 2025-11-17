"""Indicator-based strategy using declarative rules."""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from llm_trading_system.strategies.base import AccountState, Bar, Order, Strategy
from llm_trading_system.strategies.configs import IndicatorStrategyConfig
from llm_trading_system.strategies.indicators import atr, bollinger, ema, rsi, sma
from llm_trading_system.strategies.rules import RuleSet, evaluate_rules


class IndicatorStrategy(Strategy):
    """Generic indicator-based strategy that uses declarative rules.

    This strategy:
    - Maintains OHLCV buffers to compute technical indicators
    - Evaluates entry/exit rules using the rule engine
    - Generates orders based on rule evaluation results
    - Respects allow_long/allow_short configuration
    """

    def __init__(
        self,
        config: IndicatorStrategyConfig,
        rules: RuleSet | dict[str, Any],
    ) -> None:
        """Initialize the indicator strategy.

        Args:
            config: Strategy configuration with indicator parameters
            rules: RuleSet or dict to convert to RuleSet
        """
        super().__init__(config.symbol)
        self.config = config

        # Convert dict to RuleSet if needed
        if isinstance(rules, dict):
            self.rules = RuleSet.from_dict(rules)
        else:
            self.rules = rules

        # OHLCV buffers (we'll keep enough history for the longest indicator)
        max_len = max(
            config.ema_slow_len,
            config.rsi_len + 1,  # RSI needs len+1 for changes
            config.bb_len,
            config.atr_len + 1,  # ATR needs len+1
            config.vol_ma_len,
            config.adx_len * 2,  # ADX needs more history
        )
        self.max_len = max_len

        self.closes: deque[float] = deque(maxlen=max_len)
        self.highs: deque[float] = deque(maxlen=max_len)
        self.lows: deque[float] = deque(maxlen=max_len)
        self.volumes: deque[float] = deque(maxlen=max_len)

        # Current indicator values
        self.current_indicators: dict[str, float | None] = {}

        # Pyramiding and TP/SL state
        self._closed_trades_count: int = 0
        self._open_positions_count: int = 0
        self._current_side: Literal["long", "short", "flat"] = "flat"
        self._entry_price: float | None = None
        self._tp_price: float | None = None
        self._sl_price: float | None = None

    def reset(self) -> None:
        """Reset internal state before a new backtest run."""
        self.closes.clear()
        self.highs.clear()
        self.lows.clear()
        self.volumes.clear()
        self.current_indicators = {}
        self._closed_trades_count = 0
        self._open_positions_count = 0
        self._current_side = "flat"
        self._entry_price = None
        self._tp_price = None
        self._sl_price = None

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Process a new bar and generate trading signals.

        Args:
            bar: Current OHLCV bar
            account: Current account state

        Returns:
            Order to execute or None to maintain current position
        """
        # Update OHLCV buffers
        self.closes.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.volumes.append(bar.volume)

        # Need minimum data to compute indicators
        if len(self.closes) < 2:
            return None

        # Check TP/SL first (before computing indicators for performance)
        # NOTE: TP/SL is checked before entry signals to avoid overtrading.
        # If TP/SL is hit, the position closes and no new entries are evaluated
        # in the same bar. This is intentional risk management behavior.
        if self.config.use_tp_sl:
            exit_price = self._check_tp_sl_hit(bar, account)
            if exit_price is not None:
                return self._close_position(exit_price=exit_price)

        # Save previous indicators before computing new ones
        prev_indicators = self.current_indicators.copy() if self.current_indicators else None

        # Compute indicators (including time filter)
        indicators = self._compute_indicators(bar)

        # Store current indicators
        self.current_indicators = indicators

        # Apply time filter if enabled
        if self.config.time_filter_enabled:
            if not self._is_in_time_window(bar):
                return None

        # Evaluate rules (use saved previous indicators)
        signals = evaluate_rules(self.rules, indicators, prev_indicators)

        # Generate order based on signals
        return self._generate_order(signals, account, bar)

    def _compute_indicators(self, bar: Bar | None = None) -> dict[str, float | None]:
        """Compute all configured indicators.

        Args:
            bar: Current bar (for extracting hour if time filter enabled)

        Returns:
            Dictionary of indicator name -> value
        """
        indicators: dict[str, float | None] = {}

        # Convert deques to lists for indicator functions
        closes_list = list(self.closes)
        highs_list = list(self.highs)
        lows_list = list(self.lows)
        volumes_list = list(self.volumes)

        # EMA fast and slow
        indicators["ema_fast"] = ema(closes_list, self.config.ema_fast_len)
        indicators["ema_slow"] = ema(closes_list, self.config.ema_slow_len)

        # SMA (using same lengths as EMA for convenience)
        indicators["sma_fast"] = sma(closes_list, self.config.ema_fast_len)
        indicators["sma_slow"] = sma(closes_list, self.config.ema_slow_len)

        # RSI
        indicators["rsi"] = rsi(closes_list, self.config.rsi_len)

        # Bollinger Bands
        bb_middle, bb_upper, bb_lower = bollinger(
            closes_list, self.config.bb_len, self.config.bb_mult
        )
        indicators["bb_middle"] = bb_middle
        indicators["bb_basis"] = bb_middle  # Alias for Pine Script compatibility
        indicators["bb_upper"] = bb_upper
        indicators["bb_lower"] = bb_lower
        # TradingView-style aliases
        indicators["upperBB"] = bb_upper
        indicators["upper_bb"] = bb_upper
        indicators["lowerBB"] = bb_lower
        indicators["lower_bb"] = bb_lower

        # ATR
        indicators["atr"] = atr(
            highs_list, lows_list, closes_list, self.config.atr_len
        )

        # Volume MA
        vol_ma_val = sma(volumes_list, self.config.vol_ma_len)
        indicators["vol_ma"] = vol_ma_val

        # Volume MA scaled by multiplier (for volume filter comparisons)
        if vol_ma_val is not None:
            indicators["vol_ma_scaled"] = vol_ma_val * self.config.vol_mult
            indicators["vol_threshold"] = vol_ma_val * self.config.vol_mult  # Alias

        # Current OHLCV values (useful for rules)
        indicators["open"] = bar.open if bar else None
        indicators["high"] = highs_list[-1] if highs_list else None
        indicators["low"] = lows_list[-1] if lows_list else None
        indicators["close"] = closes_list[-1] if closes_list else None
        indicators["volume"] = volumes_list[-1] if volumes_list else None

        # Extract hour from bar timestamp (for time filters)
        if bar:
            indicators["hour"] = float(bar.timestamp.hour)

        return indicators

    def _generate_order(
        self, signals: dict[str, bool], account: AccountState, bar: Bar
    ) -> Order | None:
        """Generate an order based on rule evaluation signals.

        Args:
            signals: Dictionary with long_entry, short_entry, long_exit, short_exit
            account: Current account state
            bar: Current bar

        Returns:
            Order to execute or None
        """
        current_position = account.position_size

        # Check exit signals first
        if current_position > 0 and signals["long_exit"]:
            # Exit long position
            return self._close_position()

        if current_position < 0 and signals["short_exit"]:
            # Exit short position
            return self._close_position()

        # Check entry signals
        if signals["long_entry"] and self.config.allow_long:
            order = self._prepare_entry("long", current_position, bar)
            if order:
                return order

        if signals["short_entry"] and self.config.allow_short:
            order = self._prepare_entry("short", current_position, bar)
            if order:
                return order

        # No signal or already in position
        return None

    def _prepare_entry(
        self, side: Literal["long", "short"], current_position: float, bar: Bar
    ) -> Order | None:
        """Prepare a new or pyramided entry respecting limits."""

        same_direction = (current_position > 0 and side == "long") or (
            current_position < 0 and side == "short"
        )

        # If switching direction, count previous trade as closed
        if not same_direction and current_position != 0:
            self._mark_trade_closed()

        entries_in_position = self._open_positions_count if same_direction else 0
        if entries_in_position >= self.config.pyramiding:
            return None

        incremental_size = self._calculate_position_size()
        if incremental_size <= 0:
            return None

        base_target = abs(current_position) if same_direction else 0.0
        target = min(1.0, base_target + incremental_size)
        if target <= base_target:
            return None

        self._entry_price = bar.close
        self._current_side = side
        if side == "long":
            self._set_tp_sl_for_long()
        else:
            self._set_tp_sl_for_short()

        self._open_positions_count = entries_in_position + 1
        order = Order(symbol=self.symbol, side=side, size=target)
        return order

    def _calculate_position_size(self) -> float:
        """Calculate position size with optional martingale scaling.

        Returns:
            Position size as fraction of equity
        """
        # Martingale step = number of closed positions
        # This ensures the first position uses base size (step=0),
        # and each subsequent position (after close) scales up
        step = min(self._closed_trades_count, self.config.max_martingale_step)

        base_fraction = self._base_position_fraction()
        if self.config.use_martingale:
            size = base_fraction * (self.config.martingale_mult ** step)
        else:
            size = base_fraction
        return min(size, 1.0)  # Cap at 100% equity

    def _base_position_fraction(self) -> float:
        """Resolve configured base size, including percent inputs."""

        if self.config.base_position_pct is not None:
            return max(0.0, min(self.config.base_position_pct / 100.0, 1.0))
        return max(0.0, min(self.config.base_size, 1.0))

    def _set_tp_sl_for_long(self) -> None:
        """Set TP/SL prices for long position."""
        if not self.config.use_tp_sl or self._entry_price is None:
            return
        self._tp_price = self._entry_price * (1 + self.config.tp_long_pct / 100)
        self._sl_price = self._entry_price * (1 - self.config.sl_long_pct / 100)

    def _set_tp_sl_for_short(self) -> None:
        """Set TP/SL prices for short position."""
        if not self.config.use_tp_sl or self._entry_price is None:
            return
        self._tp_price = self._entry_price * (1 - self.config.tp_short_pct / 100)
        self._sl_price = self._entry_price * (1 + self.config.sl_short_pct / 100)

    def _check_tp_sl_hit(self, bar: Bar, account: AccountState) -> float | None:
        """Check if TP or SL is hit on current bar.

        Note: SL is checked first (as in TradingView), then TP.
        In reality, both could trigger within the same bar, but we
        use a simplified model checking high/low of the bar.

        Args:
            bar: Current bar
            account: Current account state

        Returns:
            Exit price if TP or SL is hit, otherwise None
        """
        if account.position_size == 0 or self._entry_price is None:
            return None

        if self._current_side == "long":
            # Check SL first (conservative approach)
            if self._sl_price and bar.low <= self._sl_price:
                return self._sl_price
            if self._tp_price and bar.high >= self._tp_price:
                return self._tp_price
        elif self._current_side == "short":
            # Check SL first (conservative approach)
            if self._sl_price and bar.high >= self._sl_price:
                return self._sl_price
            if self._tp_price and bar.low <= self._tp_price:
                return self._tp_price

        return None

    def _close_position(self, *, exit_price: float | None = None) -> Order:
        """Close current position and reset state.

        Args:
            execution_price: Optional execution price (e.g., TP/SL trigger price)

        Returns:
            Flat order with execution price in meta if provided
        """
        self._mark_trade_closed()
        meta = {"exit_price": exit_price} if exit_price is not None else None
        return Order(symbol=self.symbol, side="flat", size=0.0, meta=meta)

    def _mark_trade_closed(self) -> None:
        """Update counters/state after closing an active trade."""

        self._closed_trades_count += 1
        self._open_positions_count = 0
        self._current_side = "flat"
        self._entry_price = None
        self._tp_price = None
        self._sl_price = None

    def _is_in_time_window(self, bar: Bar) -> bool:
        """Check if current bar is within the configured time window.

        Args:
            bar: Current bar

        Returns:
            True if bar is within time window
        """
        hour = bar.timestamp.hour
        start = self.config.time_filter_start_hour
        end = self.config.time_filter_end_hour

        if start <= end:
            return start <= hour <= end
        else:
            # Handle wrap-around (e.g., 22:00 - 06:00)
            return hour >= start or hour <= end


__all__ = ["IndicatorStrategy"]
