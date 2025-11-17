"""Tests for combined strategy with LLM_ONLY, QUANT_ONLY, and HYBRID modes."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies import (
    CombinedStrategy,
    IndicatorStrategyConfig,
    RuleSet,
    StrategyMode,
)


class DummyLLMClient:
    """Mock LLM client that returns fixed regime assessments."""

    def __init__(self, prob_bull: float = 0.7, prob_bear: float = 0.3):
        """Initialize with fixed probabilities."""
        self.prob_bull = prob_bull
        self.prob_bear = prob_bear

    def complete(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.1
    ) -> str:
        """Return a fixed JSON response."""
        response = {
            "prob_bull": self.prob_bull,
            "prob_bear": self.prob_bear,
            "regime_label": "bullish" if self.prob_bull > self.prob_bear else "bearish",
            "confidence_level": "moderate",
            "scores": {
                "global_sentiment": 0.3,
                "btc_sentiment": 0.4,
                "onchain_pressure": 0.2,
                "liquidity_risk": 0.1,
                "news_risk": 0.15,
                "trend_strength": 0.5,
            },
            "reasoning": "Mock LLM response for testing",
        }
        return json.dumps(response)


def create_test_data(tmp_dir: str, trend: str = "up") -> Path:
    """Create test CSV data with specified trend.

    Args:
        tmp_dir: Temporary directory path
        trend: 'up', 'down', or 'flat'

    Returns:
        Path to created CSV file
    """
    path = Path(tmp_dir) / f"{trend}trend.csv"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        now = datetime.now(tz=timezone.utc)

        if trend == "up":
            # Uptrend: decline then rally
            prices = (
                [120] * 5
                + [120 - i for i in range(1, 16)]
                + [105] * 5
                + [105 + i * 2 for i in range(1, 11)]
                + [125] * 10
            )
        elif trend == "down":
            # Downtrend: rally then decline
            prices = (
                [105] * 5
                + [105 + i for i in range(1, 16)]
                + [120] * 5
                + [120 - i * 2 for i in range(1, 11)]
                + [100] * 10
            )
        else:  # flat
            prices = [100] * 40

        for i, price in enumerate(prices):
            ts = now + timedelta(minutes=i)
            fh.write(f"{ts.isoformat()},{price},{price+1},{price-1},{price},1000\n")

    return path


def test_combined_strategy_quant_only():
    """Test QUANT_ONLY mode (no LLM involved)."""
    config = IndicatorStrategyConfig(
        mode=StrategyMode.QUANT_ONLY,
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=20,
        base_size=0.1,
        allow_long=True,
        allow_short=False,
    )

    rules = RuleSet.from_dict(
        {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        }
    )

    strategy = CombinedStrategy(config=config, rules=rules)

    with TemporaryDirectory() as tmp:
        path = create_test_data(tmp, trend="up")
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Should have positive return on uptrend
        assert result.total_return > 0, f"Expected profit, got {result.total_return:.2%}"
        assert result.final_equity > 10_000.0, "Expected final equity > initial"

        print(f"✓ QUANT_ONLY mode test passed:")
        print(f"  Return: {result.total_return:.2%}")
        print(f"  Final equity: ${result.final_equity:.2f}")


def test_combined_strategy_llm_only():
    """Test LLM_ONLY mode (no indicators involved)."""
    # Bullish LLM client
    llm_client = DummyLLMClient(prob_bull=0.8, prob_bear=0.2)

    config = IndicatorStrategyConfig(
        mode=StrategyMode.LLM_ONLY,
        symbol="BTCUSDT",
        base_size=0.1,
        k_max=2.0,
        llm_refresh_interval_bars=10,
        allow_long=True,
        allow_short=False,
    )

    strategy = CombinedStrategy(config=config, llm_client=llm_client)

    with TemporaryDirectory() as tmp:
        path = create_test_data(tmp, trend="up")
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Should have positive return with bullish LLM on uptrend
        assert result.total_return > 0, f"Expected profit, got {result.total_return:.2%}"

        print(f"✓ LLM_ONLY mode test passed:")
        print(f"  Return: {result.total_return:.2%}")
        print(f"  Final equity: ${result.final_equity:.2f}")


def test_combined_strategy_hybrid():
    """Test HYBRID mode (indicators + LLM filtering)."""
    # Bullish LLM client
    llm_client = DummyLLMClient(prob_bull=0.8, prob_bear=0.2)

    config = IndicatorStrategyConfig(
        mode=StrategyMode.HYBRID,
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=20,
        base_size=0.1,
        k_max=2.0,
        llm_refresh_interval_bars=10,
        llm_min_prob_edge=0.05,
        allow_long=True,
        allow_short=False,
    )

    rules = RuleSet.from_dict(
        {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        }
    )

    strategy = CombinedStrategy(config=config, rules=rules, llm_client=llm_client)

    with TemporaryDirectory() as tmp:
        path = create_test_data(tmp, trend="up")
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Should have positive return with bullish LLM on uptrend
        assert result.total_return > 0, f"Expected profit, got {result.total_return:.2%}"

        print(f"✓ HYBRID mode test passed:")
        print(f"  Return: {result.total_return:.2%}")
        print(f"  Final equity: ${result.final_equity:.2f}")


def test_hybrid_vs_quant_difference():
    """Test that HYBRID mode behaves differently from QUANT_ONLY."""
    rules = RuleSet.from_dict(
        {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        }
    )

    # QUANT_ONLY config
    quant_config = IndicatorStrategyConfig(
        mode=StrategyMode.QUANT_ONLY,
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=20,
        base_size=0.1,
        allow_long=True,
        allow_short=False,
    )

    # HYBRID config with strong bullish LLM (should amplify returns)
    hybrid_config = IndicatorStrategyConfig(
        mode=StrategyMode.HYBRID,
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=20,
        base_size=0.1,
        k_max=2.0,
        llm_refresh_interval_bars=10,
        llm_min_prob_edge=0.05,
        allow_long=True,
        allow_short=False,
    )

    llm_client = DummyLLMClient(prob_bull=0.9, prob_bear=0.1)

    quant_strategy = CombinedStrategy(config=quant_config, rules=rules)
    hybrid_strategy = CombinedStrategy(
        config=hybrid_config, rules=rules, llm_client=llm_client
    )

    with TemporaryDirectory() as tmp:
        path = create_test_data(tmp, trend="up")

        # Run QUANT_ONLY
        feed_quant = CSVDataFeed(path=path, symbol="BTCUSDT")
        result_quant = Backtester(
            strategy=quant_strategy,
            data_feed=feed_quant,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        ).run()

        # Run HYBRID
        feed_hybrid = CSVDataFeed(path=path, symbol="BTCUSDT")
        result_hybrid = Backtester(
            strategy=hybrid_strategy,
            data_feed=feed_hybrid,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        ).run()

        # HYBRID with bullish LLM should amplify returns (k_long > 1)
        # Due to LLM multiplier and gating
        assert result_hybrid.total_return != result_quant.total_return, (
            "HYBRID and QUANT_ONLY should produce different returns"
        )

        print(f"✓ HYBRID vs QUANT difference test passed:")
        print(f"  QUANT return: {result_quant.total_return:.2%}")
        print(f"  HYBRID return: {result_hybrid.total_return:.2%}")
        print(f"  Difference: {abs(result_hybrid.total_return - result_quant.total_return):.2%}")


def test_hybrid_bearish_llm_filter():
    """Test that HYBRID mode filters out long signals with bearish LLM."""
    # Bearish LLM client (should gate out long signals)
    llm_client = DummyLLMClient(prob_bull=0.2, prob_bear=0.8)

    config = IndicatorStrategyConfig(
        mode=StrategyMode.HYBRID,
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=20,
        base_size=0.1,
        k_max=2.0,
        llm_refresh_interval_bars=10,
        llm_min_prob_edge=0.05,
        allow_long=True,
        allow_short=False,
    )

    rules = RuleSet.from_dict(
        {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        }
    )

    strategy = CombinedStrategy(config=config, rules=rules, llm_client=llm_client)

    with TemporaryDirectory() as tmp:
        path = create_test_data(tmp, trend="up")
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # With bearish LLM, long_gate should be 0, blocking long entries
        # Return should be close to 0 (no trades or minimal trading)
        assert abs(result.total_return) < 0.02, (
            f"Expected near-zero return with bearish LLM filter, got {result.total_return:.2%}"
        )

        print(f"✓ HYBRID bearish filter test passed:")
        print(f"  Return: {result.total_return:.2%} (expected ~0%)")
        print(f"  Final equity: ${result.final_equity:.2f}")


if __name__ == "__main__":
    print("Running combined strategy tests...")
    test_combined_strategy_quant_only()
    test_combined_strategy_llm_only()
    test_combined_strategy_hybrid()
    test_hybrid_vs_quant_difference()
    test_hybrid_bearish_llm_filter()
    print("\n✓ All combined strategy tests passed!")
