"""Tests for LLMRegimeStrategy (pure LLM strategy)."""

from datetime import datetime, timezone

import pytest

from llm_trading_system.strategies.base import AccountState, Bar, Order
from llm_trading_system.strategies.llm_regime_strategy import LLMRegimeStrategy


# ============================================================================
# Mock Components
# ============================================================================


class DummyLLMClient:
    """Dummy LLM client for testing without actual LLM calls."""

    def __init__(
        self,
        regime: str = "bullish",
        prob_bull: float = 0.7,
        trend_strength: float = 0.6,
        liquidity_risk: float = 0.2,
        news_risk: float = 0.1,
    ):
        """Initialize dummy LLM client with configurable regime.

        Args:
            regime: Regime label to return
            prob_bull: Bull probability (prob_bear will be 1 - prob_bull)
            trend_strength: Trend strength score (0-1)
            liquidity_risk: Liquidity risk score (0-1)
            news_risk: News risk score (0-1)
        """
        self.regime = regime
        self.prob_bull = prob_bull
        self.prob_bear = 1.0 - prob_bull
        self.trend_strength = trend_strength
        self.liquidity_risk = liquidity_risk
        self.news_risk = news_risk
        self.call_count = 0

    def complete(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.1
    ) -> str:
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
        "liquidity_risk": {self.liquidity_risk},
        "news_risk": {self.news_risk},
        "trend_strength": {self.trend_strength}
    }},
    "reasoning": "Test reasoning"
}}
```"""


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_bar():
    """Create a sample bar for testing."""
    return Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )


@pytest.fixture
def sample_account():
    """Create a sample account state for testing."""
    return AccountState(
        equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"
    )


# ============================================================================
# Initialization and Configuration Tests
# ============================================================================


def test_llm_regime_strategy_initialization():
    """Test initializing LLMRegimeStrategy with default parameters."""
    client = DummyLLMClient()
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.02,
        k_max=3.0,
        horizon_bars=50,
    )

    assert strategy.symbol == "BTC/USDT"
    assert strategy.client == client
    assert strategy.base_size == 0.02
    assert strategy.k_max == 3.0
    assert strategy.horizon_bars == 50
    assert strategy.min_prob_edge == 0.05
    assert strategy.temperature == 0.1
    assert strategy.use_onchain_data is True
    assert strategy.use_news_data is True
    assert strategy._target_position == 0.0


def test_llm_regime_strategy_initialization_with_custom_params():
    """Test initializing LLMRegimeStrategy with custom parameters."""
    client = DummyLLMClient()
    strategy = LLMRegimeStrategy(
        symbol="ETH/USDT",
        client=client,
        base_size=0.015,
        k_max=2.5,
        horizon_bars=30,
        min_prob_edge=0.1,
        temperature=0.2,
        use_onchain_data=False,
        use_news_data=False,
    )

    assert strategy.symbol == "ETH/USDT"
    assert strategy.base_size == 0.015
    assert strategy.k_max == 2.5
    assert strategy.horizon_bars == 30
    assert strategy.min_prob_edge == 0.1
    assert strategy.temperature == 0.2
    assert strategy.use_onchain_data is False
    assert strategy.use_news_data is False


def test_llm_regime_strategy_validation_base_size():
    """Test validation of base_size parameter."""
    client = DummyLLMClient()

    # Invalid: base_size <= 0
    with pytest.raises(ValueError, match="base_size must be in"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, base_size=0.0)

    # Invalid: base_size > 1
    with pytest.raises(ValueError, match="base_size must be in"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, base_size=1.5)

    # Valid edge cases
    LLMRegimeStrategy(symbol="BTC/USDT", client=client, base_size=0.001)
    LLMRegimeStrategy(symbol="BTC/USDT", client=client, base_size=1.0)


def test_llm_regime_strategy_validation_k_max():
    """Test validation of k_max parameter."""
    client = DummyLLMClient()

    # Invalid: k_max <= 0
    with pytest.raises(ValueError, match="k_max must be positive"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, k_max=0.0)

    with pytest.raises(ValueError, match="k_max must be positive"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, k_max=-1.0)

    # Valid
    LLMRegimeStrategy(symbol="BTC/USDT", client=client, k_max=0.5)


def test_llm_regime_strategy_validation_horizon_bars():
    """Test validation of horizon_bars parameter."""
    client = DummyLLMClient()

    # Invalid: horizon_bars < 1
    with pytest.raises(ValueError, match="horizon_bars must be at least"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, horizon_bars=0)

    # Valid
    LLMRegimeStrategy(symbol="BTC/USDT", client=client, horizon_bars=1)


def test_llm_regime_strategy_validation_min_prob_edge():
    """Test validation of min_prob_edge parameter."""
    client = DummyLLMClient()

    # Invalid: min_prob_edge < 0
    with pytest.raises(ValueError, match="min_prob_edge must be in"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, min_prob_edge=-0.1)

    # Invalid: min_prob_edge > 0.5
    with pytest.raises(ValueError, match="min_prob_edge must be in"):
        LLMRegimeStrategy(symbol="BTC/USDT", client=client, min_prob_edge=0.6)

    # Valid edge cases
    LLMRegimeStrategy(symbol="BTC/USDT", client=client, min_prob_edge=0.0)
    LLMRegimeStrategy(symbol="BTC/USDT", client=client, min_prob_edge=0.5)


def test_llm_regime_strategy_none_client():
    """Test initializing with None client (LLM disabled mode)."""
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=None,
        base_size=0.01,
    )

    assert strategy.client is None
    assert strategy._target_position == 0.0


# ============================================================================
# State Management Tests
# ============================================================================


def test_llm_regime_strategy_reset():
    """Test reset() clears all internal state."""
    client = DummyLLMClient()
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Process a bar to update state
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )
    account = AccountState(
        equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"
    )

    strategy.on_bar(bar, account)

    # Verify state is populated
    assert strategy._bar_index >= 0
    assert strategy._last_update_bar is not None
    assert strategy._last_llm_output is not None

    # Reset
    strategy.reset()

    # Verify state is cleared
    assert strategy._bar_index == -1
    assert strategy._last_update_bar is None
    assert strategy._target_position == 0.0
    assert strategy._last_llm_output is None
    assert strategy._k_long == 0.5
    assert strategy._k_short == 0.5


# ============================================================================
# Core Logic Tests
# ============================================================================


def test_llm_regime_strategy_bullish_goes_long(sample_bar, sample_account):
    """Test that bullish regime results in long position."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.75)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        k_max=2.0,
        horizon_bars=1,
        min_prob_edge=0.1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Process bar - should trigger LLM update and go long
    order = strategy.on_bar(sample_bar, sample_account)

    assert order is not None
    assert order.side == "long"
    assert order.size > 0
    # Size should be base_size * k_long where k_long > 0.5 (bullish)
    assert order.size > 0.005  # At least half of base_size
    assert client.call_count == 1
    assert strategy._target_position > 0


def test_llm_regime_strategy_bearish_goes_short(sample_bar, sample_account):
    """Test that bearish regime results in short position."""
    client = DummyLLMClient(regime="bearish", prob_bull=0.25)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        k_max=2.0,
        horizon_bars=1,
        min_prob_edge=0.1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Process bar - should trigger LLM update and go short
    order = strategy.on_bar(sample_bar, sample_account)

    assert order is not None
    assert order.side == "short"
    assert order.size > 0
    assert client.call_count == 1
    assert strategy._target_position < 0


def test_llm_regime_strategy_neutral_stays_flat(sample_bar, sample_account):
    """Test that neutral regime with weak edge stays flat."""
    client = DummyLLMClient(regime="neutral", prob_bull=0.52)  # Weak edge
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        k_max=2.0,
        horizon_bars=1,
        min_prob_edge=0.1,  # Require 10% edge
        use_onchain_data=False,
        use_news_data=False,
    )

    # Process bar - should trigger LLM update and stay flat
    order = strategy.on_bar(sample_bar, sample_account)

    # Edge is |0.52 - 0.48| = 0.04 < 0.1, so should be flat
    assert order is None or order.side == "flat"
    assert client.call_count == 1
    assert strategy._target_position == 0.0


def test_llm_regime_strategy_disabled_client_stays_flat(sample_bar, sample_account):
    """Test that strategy with None client (disabled) stays flat."""
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=None,  # LLM disabled
        base_size=0.01,
        horizon_bars=1,
    )

    # Process bar - should not call LLM and stay flat
    order = strategy.on_bar(sample_bar, sample_account)

    assert order is None or order.side == "flat"
    assert strategy._target_position == 0.0


def test_llm_regime_strategy_update_frequency(sample_bar, sample_account):
    """Test that LLM is only updated every horizon_bars."""
    client = DummyLLMClient()
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        horizon_bars=3,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Bar 1: Should update LLM
    strategy.on_bar(sample_bar, sample_account)
    assert client.call_count == 1

    # Bar 2: No update
    strategy.on_bar(sample_bar, sample_account)
    assert client.call_count == 1

    # Bar 3: No update
    strategy.on_bar(sample_bar, sample_account)
    assert client.call_count == 1

    # Bar 4: Should update (3 bars since last update)
    strategy.on_bar(sample_bar, sample_account)
    assert client.call_count == 2


def test_llm_regime_strategy_no_order_if_at_target(sample_bar):
    """Test that no order is generated if already at target position."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.7)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # First bar: Get initial target
    account = AccountState(
        equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"
    )
    order1 = strategy.on_bar(sample_bar, account)
    assert order1 is not None
    target_size = order1.size

    # Second bar: Already at target position
    account_at_target = AccountState(
        equity=10000.0,
        position_size=target_size,
        entry_price=50000.0,
        symbol="BTC/USDT",
    )
    strategy._bar_index += 99  # Advance to next update
    order2 = strategy.on_bar(sample_bar, account_at_target)

    # Should get None since we're already at target
    assert order2 is None


# ============================================================================
# Property Tests
# ============================================================================


def test_llm_regime_strategy_current_regime_property(sample_bar, sample_account):
    """Test accessing current regime info via property."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.7)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Before first bar
    assert strategy.current_regime is None

    # After first bar
    strategy.on_bar(sample_bar, sample_account)

    regime = strategy.current_regime
    assert regime is not None
    assert regime["regime_label"] == "bullish"
    assert regime["prob_bull"] == 0.7
    assert regime["prob_bear"] == 0.3


def test_llm_regime_strategy_current_multipliers_property(sample_bar, sample_account):
    """Test accessing current multipliers via property."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.7)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Before first bar (default neutral)
    k_long, k_short = strategy.current_multipliers
    assert k_long == 0.5
    assert k_short == 0.5

    # After first bar (bullish regime)
    strategy.on_bar(sample_bar, sample_account)

    k_long, k_short = strategy.current_multipliers
    assert k_long > 0.5  # Bullish regime amplifies longs
    assert k_short < k_long  # Shorts are reduced


def test_llm_regime_strategy_target_position_property(sample_bar, sample_account):
    """Test accessing target position via property."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.7)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Before first bar
    assert strategy.target_position == 0.0

    # After first bar (bullish)
    strategy.on_bar(sample_bar, sample_account)
    assert strategy.target_position > 0  # Long position


# ============================================================================
# Edge Case Tests
# ============================================================================


def test_llm_regime_strategy_extreme_bullish(sample_bar, sample_account):
    """Test extreme bullish regime (prob_bull = 0.95)."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.95)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        k_max=2.0,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    order = strategy.on_bar(sample_bar, sample_account)

    assert order is not None
    assert order.side == "long"
    # Should have maximum long multiplier
    k_long, k_short = strategy.current_multipliers
    assert k_long > 1.0  # Strong bullish bias
    assert k_short < 0.5  # Shorts heavily reduced


def test_llm_regime_strategy_extreme_bearish(sample_bar, sample_account):
    """Test extreme bearish regime (prob_bull = 0.05)."""
    client = DummyLLMClient(regime="bearish", prob_bull=0.05)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        k_max=2.0,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    order = strategy.on_bar(sample_bar, sample_account)

    assert order is not None
    assert order.side == "short"
    # Should have maximum short multiplier
    k_long, k_short = strategy.current_multipliers
    assert k_short > 1.0  # Strong bearish bias
    assert k_long < 0.5  # Longs heavily reduced


def test_llm_regime_strategy_high_risk_throttles_position(sample_bar, sample_account):
    """Test that high risk environment throttles position sizes."""
    client = DummyLLMClient(
        regime="bullish",
        prob_bull=0.7,
        liquidity_risk=0.7,  # High liquidity risk
        news_risk=0.6,  # High news risk
    )
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        k_max=2.0,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    order = strategy.on_bar(sample_bar, sample_account)

    # Should still go long, but with reduced size due to risk
    if order is not None:  # May be None if risk is extreme
        assert order.side == "long"
        # Position should be throttled
        k_long, k_short = strategy.current_multipliers
        assert k_long < 1.5  # Reduced from max due to risk


def test_llm_regime_strategy_position_transition_long_to_short(sample_bar):
    """Test transitioning from long to short position."""
    client = DummyLLMClient(regime="bullish", prob_bull=0.7)
    strategy = LLMRegimeStrategy(
        symbol="BTC/USDT",
        client=client,
        base_size=0.01,
        horizon_bars=1,
        use_onchain_data=False,
        use_news_data=False,
    )

    # Bar 1: Go long
    account = AccountState(
        equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"
    )
    order1 = strategy.on_bar(sample_bar, account)
    assert order1 is not None
    assert order1.side == "long"

    # Change regime to bearish
    client.regime = "bearish"
    client.prob_bull = 0.3
    client.prob_bear = 0.7

    # Bar 2: Should transition to short
    account_long = AccountState(
        equity=10000.0,
        position_size=order1.size,
        entry_price=50000.0,
        symbol="BTC/USDT",
    )
    order2 = strategy.on_bar(sample_bar, account_long)
    assert order2 is not None
    assert order2.side == "short"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
