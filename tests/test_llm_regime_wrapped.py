"""Tests for LLM regime wrapped strategy."""

from datetime import datetime, timezone

import pytest

from llm_trading_system.strategies.base import AccountState, Bar, Order, Strategy
from llm_trading_system.strategies.configs import LLMRegimeConfig
from llm_trading_system.strategies.llm_regime_strategy import LLMRegimeWrappedStrategy


# ============================================================================
# Mock Components
# ============================================================================


class DummyLLMClient:
    """Dummy LLM client for testing without actual LLM calls."""

    def __init__(self, regime: str = "bullish", prob_bull: float = 0.7):
        """Initialize dummy LLM client.

        Args:
            regime: Regime label to return
            prob_bull: Bull probability to return
        """
        self.regime = regime
        self.prob_bull = prob_bull
        self.prob_bear = 1.0 - prob_bull
        self.call_count = 0

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """Return fake LLM response."""
        self.call_count += 1

        # Return JSON response matching expected format
        return f"""```json
{{
    "prob_bull": {self.prob_bull},
    "prob_bear": {self.prob_bear},
    "regime_label": "{self.regime}",
    "confidence_level": "medium",
    "scores": {{
        "global_sentiment": 0.5,
        "btc_sentiment": 0.6,
        "onchain_pressure": 0.5,
        "liquidity_risk": 0.3,
        "news_risk": 0.2,
        "trend_strength": 0.7
    }},
    "reasoning": "Test reasoning"
}}
```"""


class DummyInnerStrategy(Strategy):
    """Dummy inner strategy that generates predictable signals."""

    def __init__(self, symbol: str, signal_pattern: list[str | None]):
        """Initialize dummy inner strategy.

        Args:
            symbol: Trading symbol
            signal_pattern: List of signals to emit (e.g., ["long", None, "short", "flat"])
        """
        super().__init__(symbol)
        self.signal_pattern = signal_pattern
        self.call_index = 0

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Return next signal from pattern."""
        if self.call_index >= len(self.signal_pattern):
            return None

        signal = self.signal_pattern[self.call_index]
        self.call_index += 1

        if signal is None:
            return None

        if signal == "flat":
            return Order(symbol=self.symbol, side="flat", size=0.0)

        size = 0.1  # 10% of equity
        return Order(symbol=self.symbol, side=signal, size=size)

    def reset(self) -> None:
        """Reset signal pattern."""
        self.call_index = 0


# ============================================================================
# Tests
# ============================================================================


def test_llm_regime_config_creation():
    """Test creating LLMRegimeConfig with defaults."""
    config = LLMRegimeConfig()

    assert config.horizon_bars == 48
    assert config.base_size == 0.01
    assert config.k_max == 2.0
    assert config.temperature == 0.1
    assert config.neutral_k == 0.5


def test_llm_regime_config_validation():
    """Test LLMRegimeConfig validation."""
    # Valid config
    config = LLMRegimeConfig(horizon_bars=10, k_max=3.0)
    assert config.horizon_bars == 10
    assert config.k_max == 3.0

    # Invalid horizon_bars
    with pytest.raises(ValueError, match="horizon_bars must be"):
        LLMRegimeConfig(horizon_bars=0)

    # Invalid k_max
    with pytest.raises(ValueError, match="k_max must be"):
        LLMRegimeConfig(k_max=0.5)

    # Invalid neutral_k
    with pytest.raises(ValueError, match="neutral_k must be"):
        LLMRegimeConfig(neutral_k=3.0, k_max=2.0)


def test_llm_regime_config_from_dict():
    """Test creating LLMRegimeConfig from dictionary."""
    data = {
        "horizon_bars": 24,
        "k_max": 3.0,
        "temperature": 0.5,
        "unknown_field": "ignored",
    }

    config = LLMRegimeConfig.from_dict(data)
    assert config.horizon_bars == 24
    assert config.k_max == 3.0
    assert config.temperature == 0.5


def test_wrapped_strategy_initialization():
    """Test initializing LLMRegimeWrappedStrategy."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["long"])
    llm_client = DummyLLMClient()
    regime_config = LLMRegimeConfig(horizon_bars=5)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    assert strategy.symbol == "BTC/USDT"
    assert strategy.inner_strategy == inner_strategy
    assert strategy.llm_client == llm_client
    assert strategy.regime_config == regime_config
    assert strategy._k_long == 0.5  # neutral_k
    assert strategy._k_short == 0.5


def test_wrapped_strategy_passes_through_none():
    """Test that None signals from inner strategy pass through."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", [None, None])
    llm_client = DummyLLMClient()
    regime_config = LLMRegimeConfig(horizon_bars=100)  # Don't update during test

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # First bar
    order = strategy.on_bar(bar, account)
    assert order is None

    # Second bar
    order = strategy.on_bar(bar, account)
    assert order is None


def test_wrapped_strategy_scales_long_signal():
    """Test that long signals are scaled by k_long."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["long"])
    llm_client = DummyLLMClient(regime="bullish", prob_bull=0.8)
    regime_config = LLMRegimeConfig(horizon_bars=1, use_onchain_data=False, use_news_data=False)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # Process bar - should trigger LLM update and scale order
    order = strategy.on_bar(bar, account)

    assert order is not None
    assert order.side == "long"
    # Size should be scaled: 0.1 (inner) * k_long (> 0.5 in bullish regime)
    assert order.size > 0.05  # At least scaled by neutral_k
    assert llm_client.call_count == 1


def test_wrapped_strategy_scales_short_signal():
    """Test that short signals are scaled by k_short."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["short"])
    llm_client = DummyLLMClient(regime="bearish", prob_bull=0.3)
    regime_config = LLMRegimeConfig(horizon_bars=1, use_onchain_data=False, use_news_data=False)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # Process bar - should trigger LLM update and scale order
    order = strategy.on_bar(bar, account)

    assert order is not None
    assert order.side == "short"
    # Size should be scaled: 0.1 (inner) * k_short (> 0.5 in bearish regime)
    assert order.size > 0.05
    assert llm_client.call_count == 1


def test_wrapped_strategy_passes_flat_orders():
    """Test that flat orders pass through unchanged."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["flat"])
    llm_client = DummyLLMClient()
    regime_config = LLMRegimeConfig(horizon_bars=1, use_onchain_data=False, use_news_data=False)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.1, entry_price=50000.0, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    order = strategy.on_bar(bar, account)

    assert order is not None
    assert order.side == "flat"
    assert order.size == 0.0


def test_wrapped_strategy_llm_update_frequency():
    """Test that LLM is only updated every horizon_bars."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["long", "long", "long", "long", "long"])
    llm_client = DummyLLMClient()
    regime_config = LLMRegimeConfig(horizon_bars=3, use_onchain_data=False, use_news_data=False)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # Bar 1: LLM updated
    strategy.on_bar(bar, account)
    assert llm_client.call_count == 1

    # Bar 2: No LLM update
    strategy.on_bar(bar, account)
    assert llm_client.call_count == 1

    # Bar 3: No LLM update
    strategy.on_bar(bar, account)
    assert llm_client.call_count == 1

    # Bar 4: LLM updated (3 bars since last update)
    strategy.on_bar(bar, account)
    assert llm_client.call_count == 2


def test_wrapped_strategy_filters_weak_signals():
    """Test that signals with weak probability edge are filtered."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["long"])
    # Neutral regime with weak edge
    llm_client = DummyLLMClient(regime="neutral", prob_bull=0.52)
    regime_config = LLMRegimeConfig(
        horizon_bars=1,
        min_prob_edge=0.1,  # Require at least 10% edge
        use_onchain_data=False,
        use_news_data=False,
    )

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # Process bar - signal should be filtered due to weak edge
    order = strategy.on_bar(bar, account)

    # Edge is |0.52 - 0.48| = 0.04 < 0.1, so signal filtered
    assert order is None


def test_wrapped_strategy_reset():
    """Test that reset clears state properly."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["long"])
    llm_client = DummyLLMClient()
    regime_config = LLMRegimeConfig(horizon_bars=1, use_onchain_data=False, use_news_data=False)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # Process bar
    strategy.on_bar(bar, account)
    assert strategy._bar_index == 1
    assert strategy._last_regime_update_bar == 1

    # Reset
    strategy.reset()
    assert strategy._bar_index == 0
    assert strategy._last_regime_update_bar is None
    assert strategy._k_long == regime_config.neutral_k
    assert strategy._k_short == regime_config.neutral_k
    assert inner_strategy.call_index == 0


def test_wrapped_strategy_current_regime_property():
    """Test accessing current regime info."""
    inner_strategy = DummyInnerStrategy("BTC/USDT", ["long"])
    llm_client = DummyLLMClient(regime="bullish", prob_bull=0.7)
    regime_config = LLMRegimeConfig(horizon_bars=1, use_onchain_data=False, use_news_data=False)

    strategy = LLMRegimeWrappedStrategy(
        inner_strategy=inner_strategy,
        llm_client=llm_client,
        regime_config=regime_config,
    )

    # Before first bar
    assert strategy.current_regime is None
    assert strategy.current_multipliers == (0.5, 0.5)

    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # After first bar
    strategy.on_bar(bar, account)

    regime = strategy.current_regime
    assert regime is not None
    assert regime["regime_label"] == "bullish"
    assert regime["prob_bull"] == 0.7

    k_long, k_short = strategy.current_multipliers
    assert k_long > 0.5  # Bullish regime amplifies longs
    assert k_short < k_long  # Shorts are reduced


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
