"""Combined strategy supporting LLM_ONLY, QUANT_ONLY, and HYBRID modes."""

from __future__ import annotations

from typing import Any, Callable

from llm_trading_system.strategies.base import AccountState, Bar, Order, Strategy
from llm_trading_system.strategies.configs import IndicatorStrategyConfig
from llm_trading_system.strategies.indicator_strategy import IndicatorStrategy
from llm_trading_system.strategies.modes import StrategyMode
from llm_trading_system.strategies.rules import RuleSet


class CombinedStrategy(Strategy):
    """Strategy that combines indicator-based and LLM-based approaches.

    Supports three modes:
    - QUANT_ONLY: Pure indicator-based strategy (no LLM)
    - LLM_ONLY: Pure LLM regime-based strategy (no indicators)
    - HYBRID: Indicators for entry signals, LLM for position sizing and filtering
    """

    def __init__(
        self,
        config: IndicatorStrategyConfig,
        rules: RuleSet | dict[str, Any] | None = None,
        llm_client: Any | None = None,
        snapshot_builder: Callable[[], dict] | None = None,
    ) -> None:
        """Initialize the combined strategy.

        Args:
            config: Strategy configuration
            rules: Trading rules for indicator-based logic (required for QUANT/HYBRID)
            llm_client: LLM client for regime evaluation (required for LLM/HYBRID)
            snapshot_builder: Callable that builds market snapshot for LLM
        """
        super().__init__(config.symbol)
        self.config = config
        self.llm_client = llm_client
        self.snapshot_builder = snapshot_builder

        # Initialize indicator strategy for QUANT_ONLY and HYBRID modes
        self.indicator_strategy: IndicatorStrategy | None = None
        if config.mode in (StrategyMode.QUANT_ONLY, StrategyMode.HYBRID):
            if rules is None:
                raise ValueError(
                    f"rules are required for mode {config.mode.value}"
                )
            self.indicator_strategy = IndicatorStrategy(config=config, rules=rules)

        # Validate LLM requirements
        if config.mode in (StrategyMode.LLM_ONLY, StrategyMode.HYBRID):
            if llm_client is None:
                raise ValueError(
                    f"llm_client is required for mode {config.mode.value}"
                )

        # State for HYBRID and LLM_ONLY modes
        self.current_bar_index = -1
        self.last_llm_result: dict[str, Any] | None = None
        self.last_llm_bar_index: int | None = None
        self.k_long: float = 1.0
        self.k_short: float = 1.0
        self.long_gate: float = 1.0
        self.short_gate: float = 1.0
        self.risk_factor: float = 1.0

    def reset(self) -> None:
        """Reset internal state before a new backtest run."""
        self.current_bar_index = -1
        self.last_llm_result = None
        self.last_llm_bar_index = None
        self.k_long = 1.0
        self.k_short = 1.0
        self.long_gate = 1.0
        self.short_gate = 1.0
        self.risk_factor = 1.0

        if self.indicator_strategy is not None:
            self.indicator_strategy.reset()

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Process a new bar and generate trading signals based on mode.

        Args:
            bar: Current OHLCV bar
            account: Current account state

        Returns:
            Order to execute or None
        """
        self.current_bar_index += 1

        if self.config.mode == StrategyMode.QUANT_ONLY:
            return self._on_bar_quant_only(bar, account)
        elif self.config.mode == StrategyMode.LLM_ONLY:
            return self._on_bar_llm_only(bar, account)
        elif self.config.mode == StrategyMode.HYBRID:
            return self._on_bar_hybrid(bar, account)
        else:
            raise ValueError(f"Unknown mode: {self.config.mode}")

    def _on_bar_quant_only(self, bar: Bar, account: AccountState) -> Order | None:
        """Handle QUANT_ONLY mode: pure indicator strategy."""
        if self.indicator_strategy is None:
            return None
        return self.indicator_strategy.on_bar(bar, account)

    def _on_bar_llm_only(self, bar: Bar, account: AccountState) -> Order | None:
        """Handle LLM_ONLY mode: pure LLM regime strategy."""
        # Refresh LLM regime periodically
        should_refresh = (
            self.last_llm_result is None
            or (
                self.last_llm_bar_index is not None
                and (self.current_bar_index - self.last_llm_bar_index)
                >= self.config.llm_refresh_interval_bars
            )
        )

        if should_refresh:
            self._refresh_llm_regime()

        if self.last_llm_result is None:
            return None

        # Extract LLM position recommendations
        prob_bull = self.last_llm_result.get("prob_bull", 0.5)
        prob_bear = self.last_llm_result.get("prob_bear", 0.5)

        # Determine position based on LLM probabilities and multipliers
        # Use a simple directional approach based on dominant probability
        if prob_bull > prob_bear + self.config.llm_min_prob_edge:
            # Bullish regime - go long
            if self.config.allow_long:
                target_size = self.config.base_size * self.k_long * self.risk_factor
                if account.position_size != target_size:
                    return Order(symbol=self.symbol, side="long", size=target_size)
        elif prob_bear > prob_bull + self.config.llm_min_prob_edge:
            # Bearish regime - go short
            if self.config.allow_short:
                target_size = self.config.base_size * self.k_short * self.risk_factor
                if account.position_size != -target_size:
                    return Order(symbol=self.symbol, side="short", size=target_size)
        else:
            # Neutral regime - close position
            if account.position_size != 0.0:
                return Order(symbol=self.symbol, side="flat", size=0.0)

        return None

    def _on_bar_hybrid(self, bar: Bar, account: AccountState) -> Order | None:
        """Handle HYBRID mode: indicators + LLM filtering and sizing."""
        if self.indicator_strategy is None:
            return None

        # Get indicator-based raw signal
        indicator_order = self.indicator_strategy.on_bar(bar, account)

        # Determine raw target from indicator strategy
        raw_target = 0.0
        if indicator_order is not None:
            if indicator_order.side == "long":
                raw_target = indicator_order.size
            elif indicator_order.side == "short":
                raw_target = -indicator_order.size
            elif indicator_order.side == "flat":
                raw_target = 0.0

        # Refresh LLM regime if needed
        should_refresh = (
            self.last_llm_result is None
            or (
                self.last_llm_bar_index is not None
                and (self.current_bar_index - self.last_llm_bar_index)
                >= self.config.llm_refresh_interval_bars
            )
        )

        if should_refresh:
            self._refresh_llm_regime()

        # Apply LLM filtering and sizing
        final_target = self._apply_llm_filter(raw_target)

        # Generate order if target changed
        if abs(final_target - account.position_size) < 1e-9:
            return None

        if final_target > 0:
            return Order(symbol=self.symbol, side="long", size=abs(final_target))
        elif final_target < 0:
            return Order(symbol=self.symbol, side="short", size=abs(final_target))
        else:
            return Order(symbol=self.symbol, side="flat", size=0.0)

    def _refresh_llm_regime(self) -> None:
        """Refresh LLM regime evaluation and update multipliers/gates."""
        if self.llm_client is None:
            return

        # Build snapshot (use builder if provided, otherwise use dummy)
        if self.snapshot_builder is not None:
            snapshot = self.snapshot_builder()
        else:
            # Create minimal snapshot for testing
            snapshot = {
                "base_asset": self.config.symbol.replace("USDT", ""),
                "horizon_hours": self.config.llm_horizon_hours or 24,
                "market": {},
                "onchain": {},
                "news": {},
            }

        # Call regime engine
        try:
            from llm_trading_system.core.regime_engine import evaluate_regime_and_size

            result = evaluate_regime_and_size(
                snapshot=snapshot,
                client=self.llm_client,
                base_size=self.config.base_size,
                k_max=self.config.k_max,
                temperature=0.1,
            )

            self.last_llm_result = result["llm_output"]
            self.last_llm_bar_index = self.current_bar_index
            self.k_long = result["k_long"]
            self.k_short = result["k_short"]

            # Compute gates and risk factor
            self._update_gates_and_risk()

        except Exception as e:
            # If LLM call fails, use conservative defaults
            import logging

            logging.warning(f"LLM regime refresh failed: {e}")
            self.k_long = 1.0
            self.k_short = 1.0
            self.long_gate = 0.5
            self.short_gate = 0.5
            self.risk_factor = 0.5

    def _update_gates_and_risk(self) -> None:
        """Update gating and risk factors based on LLM output."""
        if self.last_llm_result is None:
            self.long_gate = 1.0
            self.short_gate = 1.0
            self.risk_factor = 1.0
            return

        prob_bull = self.last_llm_result.get("prob_bull", 0.5)
        prob_bear = self.last_llm_result.get("prob_bear", 0.5)
        scores = self.last_llm_result.get("scores", {})

        # Compute long gate (0-1) based on bullish probability
        if prob_bull > 0.5 + self.config.llm_min_prob_edge:
            self.long_gate = min(1.0, (prob_bull - 0.5) * 2.0)
        else:
            self.long_gate = 0.0

        # Compute short gate (0-1) based on bearish probability
        if prob_bear > 0.5 + self.config.llm_min_prob_edge:
            self.short_gate = min(1.0, (prob_bear - 0.5) * 2.0)
        else:
            self.short_gate = 0.0

        # Compute risk factor (0-1) based on risk scores
        news_risk = scores.get("news_risk", 0.0)
        liquidity_risk = scores.get("liquidity_risk", 0.0)

        # Higher risk = lower risk factor
        # Risk scores are typically [-1, 1], map to risk factor
        avg_risk = (abs(news_risk) + abs(liquidity_risk)) / 2.0
        self.risk_factor = max(0.2, 1.0 - avg_risk * 0.8)

    def _apply_llm_filter(self, raw_target: float) -> float:
        """Apply LLM-based filtering and sizing to raw indicator target.

        Args:
            raw_target: Raw position target from indicator strategy

        Returns:
            Final position target after LLM filtering
        """
        if raw_target == 0.0:
            return 0.0

        if raw_target > 0:
            # Long position: apply k_long, long_gate, and risk_factor
            final_target = raw_target * self.k_long * self.long_gate * self.risk_factor
        else:
            # Short position: apply k_short, short_gate, and risk_factor
            final_target = raw_target * self.k_short * self.short_gate * self.risk_factor

        return final_target


__all__ = ["CombinedStrategy"]
