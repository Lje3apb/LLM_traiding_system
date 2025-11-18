"""LLM regime-aware trading strategies.

This module provides strategies that use LLM for market regime analysis
and position sizing decisions, either standalone or as a wrapper around
quantitative strategies.
"""

from __future__ import annotations

import logging
from typing import Any

from llm_trading_system.core.market_snapshot import Settings, build_market_snapshot
from llm_trading_system.core.regime_engine import evaluate_regime_and_size
from llm_trading_system.strategies.base import AccountState, Bar, Order, Strategy
from llm_trading_system.strategies.configs import LLMRegimeConfig

logger = logging.getLogger(__name__)


class LLMRegimeWrappedStrategy(Strategy):
    """Hybrid strategy that wraps a quantitative strategy with LLM regime filtering.

    This strategy periodically queries an LLM to assess market regime (bull/bear/neutral)
    and uses the resulting multipliers (k_long/k_short) to scale position sizes from
    an underlying quantitative strategy.

    The LLM acts as a regime filter and risk manager:
    - In bullish regimes: long positions are amplified, shorts are reduced
    - In bearish regimes: short positions are amplified, longs are reduced
    - In neutral regimes: both directions are scaled down

    Attributes:
        inner_strategy: Underlying quantitative strategy (e.g., IndicatorStrategy)
        llm_client: LLM client for regime evaluation
        regime_config: Configuration for LLM regime analysis
        last_regime: Cached LLM regime output (k_long, k_short, llm_output)
    """

    def __init__(
        self,
        inner_strategy: Strategy,
        llm_client: Any,
        regime_config: LLMRegimeConfig,
    ) -> None:
        """Initialize LLM regime wrapped strategy.

        Args:
            inner_strategy: Quantitative strategy to wrap (e.g., IndicatorStrategy)
            llm_client: LLM client with complete() method
            regime_config: Configuration for LLM regime analysis
        """
        super().__init__(inner_strategy.symbol)
        self.inner_strategy = inner_strategy
        self.llm_client = llm_client
        self.regime_config = regime_config

        # Regime state
        self._bar_index = 0
        self._last_regime_update_bar: int | None = None
        self._k_long: float = regime_config.neutral_k
        self._k_short: float = regime_config.neutral_k
        self._last_llm_output: dict | None = None

        logger.info(
            f"Initialized LLMRegimeWrappedStrategy: "
            f"symbol={self.symbol}, "
            f"horizon_bars={regime_config.horizon_bars}, "
            f"k_max={regime_config.k_max}"
        )

    def reset(self) -> None:
        """Reset strategy state for backtesting."""
        self.inner_strategy.reset()
        self._bar_index = 0
        self._last_regime_update_bar = None
        self._k_long = self.regime_config.neutral_k
        self._k_short = self.regime_config.neutral_k
        self._last_llm_output = None

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Process bar with LLM regime filtering.

        Args:
            bar: Current OHLCV bar
            account: Current account state

        Returns:
            Scaled order or None
        """
        self._bar_index += 1

        # Update LLM regime if needed
        if self._should_update_regime():
            self._update_regime(bar, account)

        # Get signal from inner strategy
        inner_order = self.inner_strategy.on_bar(bar, account)

        # No signal from inner strategy
        if inner_order is None:
            return None

        # Apply regime filtering and scaling
        return self._scale_order(inner_order, account)

    def _should_update_regime(self) -> bool:
        """Check if it's time to update LLM regime assessment."""
        if self._last_regime_update_bar is None:
            return True

        bars_since_update = self._bar_index - self._last_regime_update_bar
        return bars_since_update >= self.regime_config.horizon_bars

    def _update_regime(self, bar: Bar, account: AccountState) -> None:
        """Update regime assessment from LLM.

        Args:
            bar: Current bar (used for context)
            account: Current account state
        """
        logger.info(
            f"Updating LLM regime at bar {self._bar_index} "
            f"(last update: {self._last_regime_update_bar})"
        )

        self._last_regime_update_bar = self._bar_index

        try:
            # Build market snapshot
            snapshot = self._build_snapshot()

            # Evaluate regime via LLM
            result = evaluate_regime_and_size(
                snapshot=snapshot,
                client=self.llm_client,
                base_size=self.regime_config.base_size,
                k_max=self.regime_config.k_max,
                temperature=self.regime_config.temperature,
            )

            # Extract multipliers
            self._k_long = result["k_long"]
            self._k_short = result["k_short"]
            self._last_llm_output = result["llm_output"]

            # Log regime
            regime_label = self._last_llm_output.get("regime_label", "unknown")
            prob_bull = self._last_llm_output.get("prob_bull", 0.5)
            prob_bear = self._last_llm_output.get("prob_bear", 0.5)

            logger.info(
                f"LLM regime updated: {regime_label} | "
                f"prob_bull={prob_bull:.3f} prob_bear={prob_bear:.3f} | "
                f"k_long={self._k_long:.3f} k_short={self._k_short:.3f}"
            )

        except Exception as e:
            logger.error(f"Failed to update LLM regime: {e}", exc_info=True)
            # Keep previous multipliers on error
            logger.warning(
                f"Keeping previous multipliers: k_long={self._k_long:.3f} k_short={self._k_short:.3f}"
            )

    def _build_snapshot(self) -> dict:
        """Build market snapshot for LLM regime evaluation.

        Returns:
            Market snapshot dictionary
        """
        # Build settings from regime config
        import os

        settings = Settings(
            base_asset=self.regime_config.base_asset,
            horizon_hours=self.regime_config.horizon_hours,
            binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
            binance_fapi_url=os.getenv(
                "BINANCE_FAPI_URL", "https://fapi.binance.com"
            ),
            coinmetrics_base_url=os.getenv(
                "COINMETRICS_BASE_URL", "https://community-api.coinmetrics.io/v4"
            ),
            blockchain_com_base_url=os.getenv(
                "BLOCKCHAIN_COM_BASE_URL", "https://api.blockchain.info"
            ),
            cryptopanic_api_key=os.getenv("CRYPTOPANIC_API_KEY") if self.regime_config.use_news_data else None,
            cryptopanic_base_url=os.getenv(
                "CRYPTOPANIC_BASE_URL", "https://cryptopanic.com/api/developer/v2"
            ),
            newsapi_key=os.getenv("NEWSAPI_KEY") if self.regime_config.use_news_data else None,
            newsapi_base_url=os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2"),
        )

        # Build snapshot with toggles from config
        snapshot = build_market_snapshot(settings)

        # Optionally disable heavy data sources for live mode
        if not self.regime_config.use_onchain_data:
            # Clear on-chain data to reduce latency
            if "btc_metrics" in snapshot:
                snapshot["btc_metrics"] = {}
            if "onchain" in snapshot:
                snapshot["onchain"] = {}

        if not self.regime_config.use_binance_data:
            # Clear market data (not recommended, but possible)
            if "market" in snapshot:
                snapshot["market"] = {}

        return snapshot

    def _scale_order(self, order: Order, account: AccountState) -> Order | None:
        """Scale order size based on LLM regime multipliers.

        Args:
            order: Order from inner strategy
            account: Current account state

        Returns:
            Scaled order or None if filtered out
        """
        # Flat orders pass through unchanged
        if order.side == "flat":
            return order

        # Determine which multiplier to use
        if order.side == "long":
            multiplier = self._k_long
        elif order.side == "short":
            multiplier = self._k_short
        else:
            logger.warning(f"Unknown order side: {order.side}, passing through")
            return order

        # Apply minimum probability edge filter if configured
        if self._last_llm_output and self.regime_config.min_prob_edge > 0:
            prob_bull = self._last_llm_output.get("prob_bull", 0.5)
            prob_bear = self._last_llm_output.get("prob_bear", 0.5)
            prob_edge = abs(prob_bull - prob_bear)

            if prob_edge < self.regime_config.min_prob_edge:
                logger.debug(
                    f"Filtering {order.side} order: prob_edge={prob_edge:.3f} "
                    f"< min_prob_edge={self.regime_config.min_prob_edge}"
                )
                return None

        # Scale position size
        scaled_size = order.size * multiplier

        # Filter out very small positions
        if scaled_size < 0.001:
            logger.debug(
                f"Filtering {order.side} order: scaled_size={scaled_size:.4f} too small"
            )
            return None

        # Create scaled order
        logger.debug(
            f"Scaling {order.side} order: {order.size:.4f} -> {scaled_size:.4f} "
            f"(multiplier={multiplier:.3f})"
        )

        return Order(
            symbol=order.symbol,
            side=order.side,
            size=scaled_size,
            meta=order.meta,
        )

    @property
    def current_regime(self) -> dict | None:
        """Get current LLM regime output.

        Returns:
            Dictionary with regime info or None if not yet evaluated
        """
        return self._last_llm_output

    @property
    def current_multipliers(self) -> tuple[float, float]:
        """Get current k_long and k_short multipliers.

        Returns:
            Tuple of (k_long, k_short)
        """
        return (self._k_long, self._k_short)


class LLMRegimeStrategy(Strategy):
    """Pure LLM strategy that trades based solely on regime assessment.

    This is the original standalone LLM strategy that directly translates
    LLM regime probabilities into target positions.

    For most use cases, LLMRegimeWrappedStrategy is preferred as it combines
    LLM regime analysis with quantitative signals.
    """

    def __init__(
        self,
        symbol: str,
        client: Any,
        base_size: float = 0.01,
        k_max: float = 2.0,
        horizon_bars: int = 60,
    ) -> None:
        """Initialize pure LLM regime strategy.

        Args:
            symbol: Trading symbol
            client: LLM client
            base_size: Base position size
            k_max: Maximum position multiplier
            horizon_bars: Bars between LLM updates
        """
        super().__init__(symbol)
        self.client = client
        self.base_size = base_size
        self.k_max = k_max
        self.horizon_bars = horizon_bars
        self._bar_index = -1
        self._last_update_bar: int | None = None
        self._target_position = 0.0

    def reset(self) -> None:
        """Reset strategy state."""
        self._bar_index = -1
        self._last_update_bar = None
        self._target_position = 0.0

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Process bar and return target order.

        Args:
            bar: Current OHLCV bar
            account: Current account state

        Returns:
            Target order or None
        """
        self._bar_index += 1
        if self._should_update_target():
            self._update_target_from_llm(bar, account)

        if abs(self._target_position - account.position_size) < 1e-9:
            return None

        side: str
        if self._target_position > 0:
            side = "long"
        elif self._target_position < 0:
            side = "short"
        else:
            side = "flat"

        return Order(symbol=self.symbol, side=side, size=abs(self._target_position))

    def _should_update_target(self) -> bool:
        """Check if should update target position."""
        if self._last_update_bar is None:
            return True
        return (self._bar_index - self._last_update_bar) >= self.horizon_bars

    def _update_target_from_llm(self, bar: Bar, account: AccountState) -> None:
        """Update target position from LLM.

        Args:
            bar: Current bar
            account: Current account state
        """
        self._last_update_bar = self._bar_index
        # TODO: Implement full LLM evaluation
        # For now, keep simple implementation
        self._target_position = self.base_size


__all__ = ["LLMRegimeWrappedStrategy", "LLMRegimeStrategy"]
