"""Indicator-based strategy using declarative rules."""

from __future__ import annotations

from collections import deque
from typing import Any

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

    def reset(self) -> None:
        """Reset internal state before a new backtest run."""
        self.closes.clear()
        self.highs.clear()
        self.lows.clear()
        self.volumes.clear()
        self.current_indicators = {}

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

        # Save previous indicators before computing new ones
        prev_indicators = self.current_indicators.copy() if self.current_indicators else None

        # Compute indicators
        indicators = self._compute_indicators()

        # Store current indicators
        self.current_indicators = indicators

        # Evaluate rules (use saved previous indicators)
        signals = evaluate_rules(self.rules, indicators, prev_indicators)

        # Generate order based on signals
        return self._generate_order(signals, account)

    def _compute_indicators(self) -> dict[str, float | None]:
        """Compute all configured indicators.

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
        indicators["bb_upper"] = bb_upper
        indicators["bb_lower"] = bb_lower

        # ATR
        indicators["atr"] = atr(
            highs_list, lows_list, closes_list, self.config.atr_len
        )

        # Volume MA
        indicators["vol_ma"] = sma(volumes_list, self.config.vol_ma_len)

        # Current close price (useful for rules like "close > bb_upper")
        indicators["close"] = closes_list[-1] if closes_list else None
        indicators["volume"] = volumes_list[-1] if volumes_list else None

        return indicators

    def _generate_order(
        self, signals: dict[str, bool], account: AccountState
    ) -> Order | None:
        """Generate an order based on rule evaluation signals.

        Args:
            signals: Dictionary with long_entry, short_entry, long_exit, short_exit
            account: Current account state

        Returns:
            Order to execute or None
        """
        current_position = account.position_size

        # Check exit signals first
        if current_position > 0 and signals["long_exit"]:
            # Exit long position
            return Order(symbol=self.symbol, side="flat", size=0.0)

        if current_position < 0 and signals["short_exit"]:
            # Exit short position
            return Order(symbol=self.symbol, side="flat", size=0.0)

        # Check entry signals
        if signals["long_entry"] and self.config.allow_long:
            # Enter or increase long position
            if current_position <= 0:  # Not currently long
                return Order(
                    symbol=self.symbol, side="long", size=self.config.base_size
                )

        if signals["short_entry"] and self.config.allow_short:
            # Enter or increase short position
            if current_position >= 0:  # Not currently short
                return Order(
                    symbol=self.symbol, side="short", size=self.config.base_size
                )

        # No signal or already in position
        return None


__all__ = ["IndicatorStrategy"]
