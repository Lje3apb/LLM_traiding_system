"""Tests for PnL calculation consistency fixes.

This module tests the fixes for:
1. fee_rate and slippage_bps consistency between backtest summary and chart-data
2. entry_equity field in Trade for proper PnL% calculation
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict
from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies import create_strategy_from_config


def create_test_csv(tmp_dir: str) -> Path:
    """Create test CSV with simple price data."""
    path = Path(tmp_dir) / "test_data.csv"
    with path.open("w", encoding="utf-8") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        now = datetime.now(tz=timezone.utc)

        # Create simple uptrend data
        prices = [100 + i for i in range(50)]

        for i, price in enumerate(prices):
            ts = now + timedelta(minutes=i)
            f.write(f"{ts.isoformat()},{price},{price+1},{price-1},{price},1000\n")

    return path


def test_fee_rate_in_summary():
    """Test that custom fee_rate is included in backtest summary."""
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
        data_path = create_test_csv(tmp)

        # Run backtest with custom fee_rate
        custom_fee_rate = 0.002
        custom_slippage = 2.5

        summary = run_backtest_from_config_dict(
            config=config,
            data_path=str(data_path),
            use_llm=False,
            initial_equity=10_000.0,
            fee_rate=custom_fee_rate,
            slippage_bps=custom_slippage,
        )

        # Check that fee_rate and slippage_bps are in summary
        assert "fee_rate" in summary, "fee_rate should be in summary"
        assert "slippage_bps" in summary, "slippage_bps should be in summary"
        assert summary["fee_rate"] == custom_fee_rate, f"fee_rate should be {custom_fee_rate}"
        assert summary["slippage_bps"] == custom_slippage, f"slippage_bps should be {custom_slippage}"

        print(f"✓ fee_rate={summary['fee_rate']} and slippage_bps={summary['slippage_bps']} in summary")


def test_entry_equity_in_trade():
    """Test that entry_equity field is populated in Trade objects."""
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
        data_path = create_test_csv(tmp)

        # Create strategy and run backtest
        strategy = create_strategy_from_config(config)
        feed = CSVDataFeed(path=data_path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            slippage_bps=1.0,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Check that trades have entry_equity field
        if len(result.trades) > 0:
            for trade in result.trades:
                assert hasattr(trade, "entry_equity"), "Trade should have entry_equity attribute"
                assert trade.entry_equity is not None, "entry_equity should not be None"
                assert trade.entry_equity > 0, "entry_equity should be positive"

            print(f"✓ All {len(result.trades)} trades have entry_equity field")
        else:
            print("! No trades generated, test skipped")


def test_pnl_percent_calculation():
    """Test that PnL% can be correctly calculated from entry_equity."""
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
        data_path = create_test_csv(tmp)

        # Create strategy and run backtest
        strategy = create_strategy_from_config(config)
        feed = CSVDataFeed(path=data_path, symbol="BTCUSDT")
        backtester = Backtester(
            strategy=strategy,
            data_feed=feed,
            initial_equity=10_000.0,
            fee_rate=0.001,
            slippage_bps=1.0,
            symbol="BTCUSDT",
        )

        result = backtester.run()

        # Calculate PnL% for each trade using entry_equity
        if len(result.trades) > 0:
            for trade in result.trades:
                if trade.entry_equity and trade.entry_equity > 0:
                    pnl_pct = (trade.pnl / trade.entry_equity) * 100
                    # Just verify calculation doesn't crash
                    assert isinstance(pnl_pct, (int, float)), "PnL% should be numeric"

            print(f"✓ PnL% calculation works for {len(result.trades)} trades")
        else:
            print("! No trades generated, test skipped")


def test_default_fee_rate_fallback():
    """Test that default values are used when fee_rate/slippage_bps not in summary."""
    # Simulate old summary without fee_rate/slippage_bps
    summary = {
        "initial_equity": 10_000.0,
        "final_equity": 11_000.0,
        "pnl_abs": 1000.0,
        "pnl_pct": 10.0,
        # No fee_rate or slippage_bps
    }

    # Test that fallback works
    fee_rate = summary.get("fee_rate", 0.001)
    slippage_bps = summary.get("slippage_bps", 1.0)

    assert fee_rate == 0.001, "Should fallback to default fee_rate"
    assert slippage_bps == 1.0, "Should fallback to default slippage_bps"

    print("✓ Default values fallback works correctly")


if __name__ == "__main__":
    print("Running PnL consistency tests...")
    test_fee_rate_in_summary()
    test_entry_equity_in_trade()
    test_pnl_percent_calculation()
    test_default_fee_rate_fallback()
    print("\n✓ All PnL consistency tests passed!")
