"""LLM regime-aware trading strategies.

This module provides strategies that use LLM for market regime analysis
and position sizing decisions, either standalone or as a wrapper around
quantitative strategies.
"""

from __future__ import annotations

import logging
import os
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

            # Validate and extract multipliers safely (CRITICAL-3 fix)
            k_long = result.get("k_long")
            k_short = result.get("k_short")
            llm_output = result.get("llm_output")

            # Validate required keys
            if k_long is None or k_short is None or llm_output is None:
                raise ValueError("Missing required keys in LLM result")

            # Validate multiplier ranges (HIGH-4 fix)
            import math
            if not math.isfinite(k_long) or not (0 <= k_long <= self.regime_config.k_max * 2):
                raise ValueError(f"k_long out of range: {k_long}")
            if not math.isfinite(k_short) or not (0 <= k_short <= self.regime_config.k_max * 2):
                raise ValueError(f"k_short out of range: {k_short}")

            # Update state only if validation passes
            self._k_long = k_long
            self._k_short = k_short
            self._last_llm_output = llm_output

            # Safe access with defaults
            regime_label = llm_output.get("regime_label", "unknown")
            prob_bull = llm_output.get("prob_bull", 0.5)
            prob_bear = llm_output.get("prob_bear", 0.5)

            logger.info(
                f"LLM regime updated: {regime_label} | "
                f"prob_bull={prob_bull:.3f} prob_bear={prob_bear:.3f} | "
                f"k_long={self._k_long:.3f} k_short={self._k_short:.3f}"
            )

        except Exception as e:
            # Only log full stack trace in DEBUG mode to avoid exposing internals
            logger.error(
                f"Failed to update LLM regime: {e}",
                exc_info=(logger.level == logging.DEBUG)
            )
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

        # Validate that Binance data is enabled (HIGH-6 fix)
        if not self.regime_config.use_binance_data:
            logger.error("use_binance_data=False disables market data, which is required for regime analysis")
            raise ValueError("Cannot build snapshot without Binance market data")

        # Optionally disable heavy data sources for live mode
        if not self.regime_config.use_onchain_data:
            # Clear on-chain data to reduce latency
            logger.warning("use_onchain_data=False, regime analysis may be less accurate")
            if "btc_metrics" in snapshot:
                snapshot["btc_metrics"] = {}
            if "onchain" in snapshot:
                snapshot["onchain"] = {}

        # Validate snapshot has required fields (HIGH-6 fix)
        required_fields = ["market", "horizon_hours", "base_asset"]
        for field in required_fields:
            if field not in snapshot or not snapshot[field]:
                raise ValueError(f"Snapshot missing required field: {field}")

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

        # Validate scaled size (CRITICAL-5 fix)
        import math
        if not math.isfinite(scaled_size) or scaled_size < 0:
            logger.error(
                f"Invalid scaled_size={scaled_size} from order.size={order.size} * multiplier={multiplier}"
            )
            return None

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

    This is a standalone LLM-only strategy that directly translates LLM regime
    probabilities into directional target positions without any quantitative signals.

    The strategy periodically queries an LLM to assess market regime and computes
    target position based on:
    - Regime probabilities (prob_bull vs prob_bear)
    - Position sizing multipliers (k_long, k_short)
    - Minimum probability edge threshold (prevents trading in neutral regimes)

    Position Logic:
    - Bullish regime (prob_bull > prob_bear): Long position = base_size * k_long
    - Bearish regime (prob_bear > prob_bull): Short position = base_size * k_short (negative)
    - Neutral regime or weak edge: Flat position = 0

    **Important**: For most use cases, LLMRegimeWrappedStrategy is preferred as it
    combines LLM regime analysis with quantitative signals for more robust trading.
    Use this strategy only when you want pure LLM-driven directional trading.

    Attributes:
        symbol: Trading symbol
        client: LLM client with complete() method (None = disabled/deterministic mode)
        base_size: Base position size as fraction of equity (e.g., 0.01 = 1%)
        k_max: Maximum position multiplier
        horizon_bars: Number of bars between LLM regime updates
        min_prob_edge: Minimum probability edge to trade (default 0.05)
        temperature: LLM sampling temperature (default 0.1)
        use_onchain_data: Whether to include on-chain metrics (default True)
        use_news_data: Whether to include news data (default True)
    """

    def __init__(
        self,
        symbol: str,
        client: Any | None,
        base_size: float = 0.01,
        k_max: float = 2.0,
        horizon_bars: int = 60,
        min_prob_edge: float = 0.05,
        temperature: float = 0.1,
        use_onchain_data: bool = True,
        use_news_data: bool = True,
    ) -> None:
        """Initialize pure LLM regime strategy.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            client: LLM client with complete() method, or None for disabled mode
            base_size: Base position size as fraction of equity (default: 0.01 = 1%)
            k_max: Maximum position multiplier (default: 2.0)
            horizon_bars: Bars between LLM updates (default: 60)
            min_prob_edge: Minimum probability edge to trade (default: 0.05)
            temperature: LLM sampling temperature (default: 0.1)
            use_onchain_data: Include on-chain metrics in regime assessment (default: True)
            use_news_data: Include news data in regime assessment (default: True)

        Raises:
            ValueError: If base_size, k_max, or horizon_bars are invalid
        """
        super().__init__(symbol)

        # Validate parameters
        if base_size <= 0 or base_size > 1:
            raise ValueError(f"base_size must be in (0, 1], got {base_size}")
        if k_max <= 0:
            raise ValueError(f"k_max must be positive, got {k_max}")
        if horizon_bars < 1:
            raise ValueError(f"horizon_bars must be at least 1, got {horizon_bars}")
        if min_prob_edge < 0 or min_prob_edge > 0.5:
            raise ValueError(f"min_prob_edge must be in [0, 0.5], got {min_prob_edge}")

        self.client = client
        self.base_size = base_size
        self.k_max = k_max
        self.horizon_bars = horizon_bars
        self.min_prob_edge = min_prob_edge
        self.temperature = temperature
        self.use_onchain_data = use_onchain_data
        self.use_news_data = use_news_data

        # State tracking
        self._bar_index = -1
        self._last_update_bar: int | None = None
        self._target_position = 0.0
        self._last_llm_output: dict | None = None
        self._k_long: float = 0.5
        self._k_short: float = 0.5

        logger.info(
            f"Initialized LLMRegimeStrategy: "
            f"symbol={self.symbol}, base_size={base_size}, "
            f"k_max={k_max}, horizon_bars={horizon_bars}, "
            f"min_prob_edge={min_prob_edge}, "
            f"llm_enabled={client is not None}"
        )

    def reset(self) -> None:
        """Reset strategy state for backtesting.

        Clears all internal state including bar counters, target position,
        and cached LLM outputs.
        """
        self._bar_index = -1
        self._last_update_bar = None
        self._target_position = 0.0
        self._last_llm_output = None
        self._k_long = 0.5
        self._k_short = 0.5

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Process bar and return target order based on LLM regime.

        This method:
        1. Increments bar counter
        2. Updates LLM regime if needed (every horizon_bars)
        3. Checks if target position differs from current position
        4. Returns order to reach target position

        Args:
            bar: Current OHLCV bar
            account: Current account state

        Returns:
            Order to reach target position, or None if already at target
        """
        self._bar_index += 1

        # Update LLM regime assessment if needed
        if self._should_update_target():
            self._update_target_from_llm(bar, account)

        # Check if we need to adjust position
        if abs(self._target_position - account.position_size) < 1e-9:
            return None

        # Determine order side and size
        side: str
        if self._target_position > 0:
            side = "long"
        elif self._target_position < 0:
            side = "short"
        else:
            side = "flat"

        size = abs(self._target_position)

        logger.debug(
            f"Bar {self._bar_index}: Generating {side} order | "
            f"current_pos={account.position_size:.6f} -> target_pos={self._target_position:.6f}"
        )

        return Order(symbol=self.symbol, side=side, size=size)

    def _should_update_target(self) -> bool:
        """Check if it's time to update target position from LLM.

        Returns:
            True if should update (first bar or horizon_bars elapsed), False otherwise
        """
        if self._last_update_bar is None:
            return True
        return (self._bar_index - self._last_update_bar) >= self.horizon_bars

    def _update_target_from_llm(self, bar: Bar, account: AccountState) -> None:
        """Update target position from LLM regime assessment.

        This method:
        1. Builds market snapshot for LLM evaluation
        2. Calls LLM via evaluate_regime_and_size()
        3. Extracts regime probabilities and position multipliers
        4. Computes target position based on regime:
           - Bullish: target = +base_size * k_long
           - Bearish: target = -base_size * k_short
           - Neutral/weak edge: target = 0 (flat)
        5. Handles errors gracefully (keeps previous target on failure)

        Args:
            bar: Current bar (used for logging context)
            account: Current account state (unused, for future expansion)
        """
        self._last_update_bar = self._bar_index

        # If LLM is disabled (client is None), use deterministic neutral position
        if self.client is None:
            logger.debug(
                f"Bar {self._bar_index}: LLM disabled, setting neutral target position=0"
            )
            self._target_position = 0.0
            return

        try:
            logger.info(
                f"Bar {self._bar_index}: Updating LLM regime assessment "
                f"(last update: {self._last_update_bar})"
            )

            # Build market snapshot
            snapshot = self._build_snapshot()

            # Evaluate regime via LLM
            result = evaluate_regime_and_size(
                snapshot=snapshot,
                client=self.client,
                base_size=self.base_size,
                k_max=self.k_max,
                temperature=self.temperature,
            )

            # Extract results
            llm_output = result.get("llm_output")
            k_long = result.get("k_long")
            k_short = result.get("k_short")
            pos_long = result.get("pos_long")
            pos_short = result.get("pos_short")

            # Validate results
            if llm_output is None or k_long is None or k_short is None:
                raise ValueError("Missing required fields in LLM result")
            if pos_long is None or pos_short is None:
                raise ValueError("Missing position sizes in LLM result")

            # Validate multiplier ranges
            import math
            if not math.isfinite(k_long) or not (0 <= k_long <= self.k_max * 2):
                raise ValueError(f"k_long out of range: {k_long}")
            if not math.isfinite(k_short) or not (0 <= k_short <= self.k_max * 2):
                raise ValueError(f"k_short out of range: {k_short}")

            # Update cached state
            self._last_llm_output = llm_output
            self._k_long = k_long
            self._k_short = k_short

            # Extract regime probabilities
            prob_bull = llm_output.get("prob_bull", 0.5)
            prob_bear = llm_output.get("prob_bear", 0.5)
            regime_label = llm_output.get("regime_label", "unknown")

            # Compute probability edge
            prob_edge = abs(prob_bull - prob_bear)

            # Determine target position based on regime
            if prob_edge < self.min_prob_edge:
                # Weak edge - stay flat
                self._target_position = 0.0
                logger.info(
                    f"LLM regime: {regime_label} | "
                    f"prob_bull={prob_bull:.3f} prob_bear={prob_bear:.3f} | "
                    f"edge={prob_edge:.3f} < min_edge={self.min_prob_edge} | "
                    f"TARGET=FLAT"
                )
            elif prob_bull > prob_bear:
                # Bullish - go long
                self._target_position = pos_long
                logger.info(
                    f"LLM regime: {regime_label} | "
                    f"prob_bull={prob_bull:.3f} prob_bear={prob_bear:.3f} | "
                    f"k_long={k_long:.3f} | "
                    f"TARGET=LONG ({self._target_position:.6f})"
                )
            else:
                # Bearish - go short (negative position)
                self._target_position = -pos_short
                logger.info(
                    f"LLM regime: {regime_label} | "
                    f"prob_bull={prob_bull:.3f} prob_bear={prob_bear:.3f} | "
                    f"k_short={k_short:.3f} | "
                    f"TARGET=SHORT ({self._target_position:.6f})"
                )

            # Validate final target position
            if not math.isfinite(self._target_position):
                raise ValueError(f"Invalid target position: {self._target_position}")

        except Exception as e:
            # Log error and keep previous target position
            logger.error(
                f"Failed to update LLM regime: {e}",
                exc_info=(logger.level == logging.DEBUG)
            )
            logger.warning(
                f"Keeping previous target position: {self._target_position:.6f}"
            )

    def _build_snapshot(self) -> dict:
        """Build market snapshot for LLM regime evaluation.

        Constructs a market snapshot dictionary containing:
        - Market data (OHLCV, funding rates, etc.)
        - On-chain metrics (if enabled)
        - News data (if enabled)
        - Horizon and base asset settings

        Returns:
            Market snapshot dictionary

        Raises:
            ValueError: If snapshot building fails or required fields are missing
        """
        # Extract base asset from symbol (e.g., "BTC/USDT" -> "BTC")
        base_asset = self.symbol.split("/")[0] if "/" in self.symbol else "BTC"

        # Build settings
        settings = Settings(
            base_asset=base_asset,
            horizon_hours=24,  # Fixed 24-hour horizon for regime assessment
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
            cryptopanic_api_key=os.getenv("CRYPTOPANIC_API_KEY") if self.use_news_data else None,
            cryptopanic_base_url=os.getenv(
                "CRYPTOPANIC_BASE_URL", "https://cryptopanic.com/api/developer/v2"
            ),
            newsapi_key=os.getenv("NEWSAPI_KEY") if self.use_news_data else None,
            newsapi_base_url=os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2"),
        )

        # Build snapshot
        snapshot = build_market_snapshot(settings)

        # Optionally disable heavy data sources
        if not self.use_onchain_data:
            logger.debug("use_onchain_data=False, clearing on-chain metrics")
            if "btc_metrics" in snapshot:
                snapshot["btc_metrics"] = {}
            if "onchain" in snapshot:
                snapshot["onchain"] = {}

        # Validate snapshot has required fields
        required_fields = ["market", "horizon_hours", "base_asset"]
        for field in required_fields:
            if field not in snapshot or not snapshot[field]:
                raise ValueError(f"Snapshot missing required field: {field}")

        return snapshot

    @property
    def current_regime(self) -> dict | None:
        """Get current LLM regime output.

        Returns:
            Dictionary with regime info (prob_bull, prob_bear, regime_label, etc.)
            or None if not yet evaluated
        """
        return self._last_llm_output

    @property
    def current_multipliers(self) -> tuple[float, float]:
        """Get current k_long and k_short multipliers.

        Returns:
            Tuple of (k_long, k_short)
        """
        return (self._k_long, self._k_short)

    @property
    def target_position(self) -> float:
        """Get current target position.

        Returns:
            Target position size (positive = long, negative = short, zero = flat)
        """
        return self._target_position


__all__ = ["LLMRegimeWrappedStrategy", "LLMRegimeStrategy"]
