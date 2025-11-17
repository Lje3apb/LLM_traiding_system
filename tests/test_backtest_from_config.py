"""Tests for strategy factory and config-based backtesting."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies import create_strategy_from_config
from llm_trading_system.strategies.modes import StrategyMode


class DummyLLMClient:
    """Mock LLM client for testing."""

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """Return a fixed JSON response."""
        response = {
            "prob_bull": 0.7,
            "prob_bear": 0.3,
            "regime_label": "bullish",
            "confidence_level": "moderate",
            "scores": {
                "global_sentiment": 0.3,
                "btc_sentiment": 0.4,
                "onchain_pressure": 0.2,
                "liquidity_risk": 0.1,
                "news_risk": 0.15,
                "trend_strength": 0.5,
            },
            "reasoning": "Mock response",
        }
        return json.dumps(response)


def create_test_csv(tmp_dir: str, trend: str = "up") -> Path:
    """Create test CSV with price data."""
    path = Path(tmp_dir) / "test_data.csv"
    with path.open("w", encoding="utf-8") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        now = datetime.now(tz=timezone.utc)

        if trend == "up":
            # Create data with EMA crossover pattern
            prices = (
                [120] * 5
                + [120 - i for i in range(1, 11)]  # Decline to 110
                + [110] * 5  # Flat
                + [110 + i * 2 for i in range(1, 16)]  # Rally to 140
                + [140] * 10  # Flat
            )
        elif trend == "down":
            prices = [150 - i for i in range(50)]
        else:  # flat
            prices = [100] * 50

        for i, price in enumerate(prices):
            ts = now + timedelta(minutes=i)
            f.write(f"{ts.isoformat()},{price},{price+1},{price-1},{price},1000\n")

    return path


def test_create_indicator_strategy_from_config():
    """Test creating an indicator strategy from configuration dict."""
    config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "ema_fast_len": 5,
        "ema_slow_len": 20,
        "base_size": 0.1,
        "rules": {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    strategy = create_strategy_from_config(config)

    assert strategy is not None
    assert strategy.symbol == "BTCUSDT"

    print("✓ Indicator strategy created from config")


def test_create_combined_strategy_from_config():
    """Test creating a combined strategy from configuration dict."""
    config = {
        "strategy_type": "combined",
        "mode": "quant_only",
        "symbol": "ETHUSDT",
        "ema_fast_len": 10,
        "ema_slow_len": 30,
        "base_size": 0.05,
        "rules": {
            "long_entry": [{"left": "ema_fast", "op": ">", "right": "ema_slow"}],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    strategy = create_strategy_from_config(config)

    assert strategy is not None
    assert strategy.symbol == "ETHUSDT"

    print("✓ Combined strategy created from config (QUANT_ONLY)")


def test_create_combined_hybrid_strategy():
    """Test creating a HYBRID combined strategy."""
    config = {
        "strategy_type": "combined",
        "mode": "hybrid",
        "symbol": "BTCUSDT",
        "ema_fast_len": 5,
        "ema_slow_len": 20,
        "base_size": 0.1,
        "k_max": 2.0,
        "llm_refresh_interval_bars": 10,
        "rules": {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    llm_client = DummyLLMClient()
    strategy = create_strategy_from_config(config, llm_client=llm_client)

    assert strategy is not None
    assert strategy.config.mode == StrategyMode.HYBRID

    print("✓ Combined HYBRID strategy created from config")


def test_backtest_from_config_uptrend():
    """Test running a backtest from config on uptrend data."""
    config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "ema_fast_len": 5,
        "ema_slow_len": 10,
        "base_size": 0.1,
        "allow_long": True,
        "allow_short": False,
        "rules": {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    with TemporaryDirectory() as tmp:
        # Create uptrend data
        data_path = create_test_csv(tmp, trend="up")

        # Create strategy
        strategy = create_strategy_from_config(config)

        # Run backtest
        feed = CSVDataFeed(path=data_path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Should have positive return on uptrend
        assert result.total_return > 0, f"Expected profit on uptrend, got {result.total_return:.2%}"
        assert result.final_equity > 10_000.0

        print(f"✓ Backtest from config on uptrend: {result.total_return:.2%} return")


def test_backtest_hybrid_mode():
    """Test running a HYBRID backtest from config."""
    config = {
        "strategy_type": "combined",
        "mode": "hybrid",
        "symbol": "BTCUSDT",
        "ema_fast_len": 5,
        "ema_slow_len": 10,
        "base_size": 0.1,
        "k_max": 1.5,
        "llm_refresh_interval_bars": 15,
        "llm_min_prob_edge": 0.05,
        "allow_long": True,
        "allow_short": False,
        "rules": {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    llm_client = DummyLLMClient()

    with TemporaryDirectory() as tmp:
        # Create uptrend data
        data_path = create_test_csv(tmp, trend="up")

        # Create strategy
        strategy = create_strategy_from_config(config, llm_client=llm_client)

        # Run backtest
        feed = CSVDataFeed(path=data_path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Should complete without errors
        assert result.final_equity != 10_000.0, "Expected some trading activity"

        print(f"✓ HYBRID backtest from config: {result.total_return:.2%} return")


def test_config_serialization_roundtrip():
    """Test that config can be serialized to JSON and back."""
    config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "ema_fast_len": 50,
        "ema_slow_len": 200,
        "rsi_len": 14,
        "base_size": 0.02,
        "allow_long": True,
        "allow_short": False,
        "rules": {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"},
                {"left": "rsi", "op": "<", "right": 30},
            ],
            "short_entry": [],
            "long_exit": [{"left": "rsi", "op": ">", "right": 70}],
            "short_exit": [],
        },
    }

    with TemporaryDirectory() as tmp:
        # Write config to JSON
        config_path = Path(tmp) / "strategy.json"
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        # Read config back
        with config_path.open("r", encoding="utf-8") as f:
            loaded_config = json.load(f)

        # Create strategy from loaded config
        strategy = create_strategy_from_config(loaded_config)

        assert strategy is not None
        assert strategy.symbol == "BTCUSDT"

        print("✓ Config serialization roundtrip successful")


def test_invalid_config_raises_error():
    """Test that invalid configs raise appropriate errors."""
    # Missing rules for indicator strategy
    config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
    }

    try:
        create_strategy_from_config(config)
        assert False, "Should have raised ValueError for missing rules"
    except ValueError as e:
        assert "rules" in str(e).lower()

    print("✓ Invalid config correctly raises ValueError")


def test_llm_required_error():
    """Test that HYBRID mode without LLM client raises error."""
    config = {
        "strategy_type": "combined",
        "mode": "hybrid",
        "symbol": "BTCUSDT",
        "rules": {
            "long_entry": [{"left": "ema_fast", "op": ">", "right": "ema_slow"}],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    try:
        create_strategy_from_config(config, llm_client=None)
        assert False, "Should have raised ValueError for missing LLM client"
    except ValueError as e:
        assert "llm_client" in str(e).lower()

    print("✓ HYBRID mode without LLM client correctly raises ValueError")


if __name__ == "__main__":
    print("Running backtest from config tests...")
    test_create_indicator_strategy_from_config()
    test_create_combined_strategy_from_config()
    test_create_combined_hybrid_strategy()
    test_backtest_from_config_uptrend()
    test_backtest_hybrid_mode()
    test_config_serialization_roundtrip()
    test_invalid_config_raises_error()
    test_llm_required_error()
    print("\n✓ All backtest from config tests passed!")
