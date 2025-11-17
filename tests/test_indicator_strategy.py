"""Tests for indicator-based strategy."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies import (
    IndicatorStrategy,
    IndicatorStrategyConfig,
    RuleSet,
)


def test_indicator_strategy_ema_crossover_uptrend():
    """Test EMA crossover strategy on uptrend data."""

    # Create configuration
    config = IndicatorStrategyConfig(
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=20,
        base_size=0.1,
        allow_long=True,
        allow_short=False,
    )

    # Create EMA crossover rules (long entry when fast crosses above slow)
    rules = RuleSet.from_dict(
        {
            "long_entry": [
                {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
            ],
            "short_entry": [],
            "long_exit": [
                {"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}
            ],
            "short_exit": [],
        }
    )

    # Create strategy
    strategy = IndicatorStrategy(config=config, rules=rules)

    # Create test data with uptrend (price increases over time)
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "uptrend.csv"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("timestamp,open,high,low,close,volume\n")
            now = datetime.now(tz=timezone.utc)

            # Create data that will trigger EMA crossover:
            # Start high and decline (fast below slow), then sharp rally (crossover)
            prices = (
                [120] * 5  # Start at 120
                + [120 - i for i in range(1, 16)]  # Decline to 105
                + [105] * 5  # Flat at 105 (fast EMA below slow EMA)
                + [105 + i * 2 for i in range(1, 11)]  # Sharp rally to 125 (triggers crossover)
                + [125] * 10  # Flat at 125
            )

            for i, price in enumerate(prices):
                ts = now + timedelta(minutes=i)
                fh.write(f"{ts.isoformat()},{price},{price+1},{price-1},{price},1000\n")

        # Run backtest
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            slippage_bps=1.0,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Assertions
        # Should have positive return on uptrend with long-only strategy
        # Note: Trade objects are only created when position is closed,
        # so we check equity change instead
        assert result.total_return > 0, f"Expected positive return, got {result.total_return:.2%}"

        # Final equity should be higher than initial
        assert result.final_equity > 10_000.0, "Expected profit on uptrend"

        print(f"✓ EMA crossover uptrend test passed:")
        print(f"  Completed trades: {len(result.trades)}")
        print(f"  Return: {result.total_return:.2%}")
        print(f"  Final equity: ${result.final_equity:.2f}")


def test_indicator_strategy_rsi_oversold():
    """Test RSI oversold strategy."""

    # Create configuration
    config = IndicatorStrategyConfig(
        symbol="BTCUSDT",
        rsi_len=14,
        rsi_ovs=30,
        base_size=0.1,
        allow_long=True,
        allow_short=False,
    )

    # Create RSI oversold rules (buy when RSI < 30)
    rules = RuleSet.from_dict(
        {
            "long_entry": [{"left": "rsi", "op": "<", "right": 30}],
            "short_entry": [],
            "long_exit": [{"left": "rsi", "op": ">", "right": 70}],
            "short_exit": [],
        }
    )

    # Create strategy
    strategy = IndicatorStrategy(config=config, rules=rules)

    # Create test data with volatile price action
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "volatile.csv"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("timestamp,open,high,low,close,volume\n")
            now = datetime.now(tz=timezone.utc)

            # Create volatile data: sharp drop then recovery
            prices = (
                [100] * 5  # Start flat
                + [100 - i * 2 for i in range(1, 11)]  # Drop to 80
                + [80 + i for i in range(1, 21)]  # Recover to 100
            )

            for i, price in enumerate(prices):
                ts = now + timedelta(minutes=i)
                fh.write(f"{ts.isoformat()},{price},{price+0.5},{price-0.5},{price},1000\n")

        # Run backtest
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Assertions
        # With entry and exit rules, should generate at least one completed trade
        # (entry on RSI < 30, exit on RSI > 70)
        assert len(result.trades) > 0, "Expected at least one completed trade on RSI signals"

        # Should be profitable buying at oversold and selling at overbought
        assert result.final_equity >= 10_000.0 * 0.95, "Expected near-breakeven or profit"

        print(f"✓ RSI oversold test passed:")
        print(f"  Completed trades: {len(result.trades)}")
        print(f"  Return: {result.total_return:.2%}")
        print(f"  Final equity: ${result.final_equity:.2f}")


def test_indicator_strategy_no_signals():
    """Test strategy with no matching signals."""

    # Create configuration
    config = IndicatorStrategyConfig(
        symbol="BTCUSDT",
        ema_fast_len=5,
        ema_slow_len=10,
        base_size=0.1,
    )

    # Create impossible rules (RSI > 100 is impossible)
    rules = RuleSet.from_dict(
        {
            "long_entry": [{"left": "rsi", "op": ">", "right": 100}],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        }
    )

    # Create strategy
    strategy = IndicatorStrategy(config=config, rules=rules)

    # Create simple flat data
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "flat.csv"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("timestamp,open,high,low,close,volume\n")
            now = datetime.now(tz=timezone.utc)

            for i in range(50):
                ts = now + timedelta(minutes=i)
                price = 100
                fh.write(f"{ts.isoformat()},{price},{price},{price},{price},1000\n")

        # Run backtest
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy, data_feed=feed, initial_equity=10_000.0, symbol="BTCUSDT"
        )

        result = backtester.run()

        # Assertions
        # Should have no trades (no signals generated)
        assert len(result.trades) == 0, "Expected no trades with impossible rules"

        # Final equity should equal initial (no trading, no fees)
        assert result.final_equity == 10_000.0, "Expected no change in equity"

        print(f"✓ No signals test passed:")
        print(f"  Trades: {len(result.trades)}")
        print(f"  Final equity: ${result.final_equity:.2f}")


if __name__ == "__main__":
    print("Running indicator strategy tests...")
    test_indicator_strategy_ema_crossover_uptrend()
    test_indicator_strategy_rsi_oversold()
    test_indicator_strategy_no_signals()
    print("\n✓ All tests passed!")
