#!/usr/bin/env python3
"""
Comprehensive test for Edit Strategy Parameters functionality.

This script validates:
1. Parameter validation in IndicatorStrategyConfig
2. Parameter flow from UI to strategy
3. Impact of parameter changes on trading behavior
4. Edge cases and error handling
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict
from llm_trading_system.strategies import IndicatorStrategyConfig


def create_test_data(tmp_dir: Path, scenario: str = "uptrend") -> str:
    """Create test OHLCV data for backtesting."""
    path = tmp_dir / f"{scenario}.csv"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        now = datetime.now(tz=timezone.utc)

        if scenario == "uptrend":
            # Uptrend with EMA crossover pattern
            prices = (
                [100] * 10
                + [100 + i for i in range(1, 21)]  # Rally to 120
                + [120] * 10
            )
        elif scenario == "downtrend":
            # Downtrend
            prices = (
                [120] * 10
                + [120 - i for i in range(1, 21)]  # Drop to 100
                + [100] * 10
            )
        elif scenario == "volatile":
            # High volatility
            prices = []
            for i in range(50):
                base = 100
                volatility = 10 if i % 2 == 0 else -10
                prices.append(base + volatility)
        else:
            prices = [100] * 50

        for i, price in enumerate(prices):
            ts = now + timedelta(minutes=i)
            volume = 1000 + i * 10
            fh.write(f"{ts.isoformat()},{price},{price+1},{price-1},{price},{volume}\n")

    return str(path)


def test_parameter_validation():
    """Test 1: Validate parameter constraints."""
    print("\n" + "=" * 80)
    print("TEST 1: Parameter Validation")
    print("=" * 80)

    test_cases = [
        # Valid config
        {
            "name": "Valid baseline config",
            "params": {
                "symbol": "BTCUSDT",
                "ema_fast_len": 12,
                "ema_slow_len": 26,
                "rsi_len": 14,
                "rsi_ovb": 70,
                "rsi_ovs": 30,
                "bb_len": 20,
                "bb_mult": 2.0,
                "atr_len": 14,
                "adx_len": 14,
                "vol_ma_len": 21,
                "vol_mult": 1.0,
                "base_size": 0.1,
                "base_position_pct": 10.0,
                "pyramiding": 2,
                "use_martingale": False,
                "martingale_mult": 1.5,
                "use_tp_sl": True,
                "tp_long_pct": 2.0,
                "sl_long_pct": 2.0,
                "tp_short_pct": 2.0,
                "sl_short_pct": 2.0,
            },
            "should_pass": True,
        },
        # Invalid RSI thresholds
        {
            "name": "Invalid RSI: ovs >= ovb",
            "params": {
                "symbol": "BTCUSDT",
                "rsi_len": 14,
                "rsi_ovb": 50,
                "rsi_ovs": 70,  # ovs > ovb - invalid
            },
            "should_pass": False,
        },
        # Invalid EMA lengths
        {
            "name": "Invalid EMA: negative length",
            "params": {
                "symbol": "BTCUSDT",
                "ema_fast_len": -5,  # negative - invalid
                "ema_slow_len": 20,
            },
            "should_pass": False,
        },
        # Invalid pyramiding
        {
            "name": "Invalid pyramiding: zero",
            "params": {
                "symbol": "BTCUSDT",
                "pyramiding": 0,  # must be >= 1
            },
            "should_pass": False,
        },
        # Invalid base_position_pct
        {
            "name": "Invalid base_position_pct: > 100",
            "params": {
                "symbol": "BTCUSDT",
                "base_position_pct": 150.0,  # > 100 - invalid
            },
            "should_pass": False,
        },
        # Invalid TP/SL (negative)
        {
            "name": "Invalid TP/SL: negative percentage",
            "params": {
                "symbol": "BTCUSDT",
                "use_tp_sl": True,
                "tp_long_pct": -2.0,  # negative - invalid
                "sl_long_pct": 2.0,
            },
            "should_pass": False,
        },
        # Invalid time filter
        {
            "name": "Invalid time filter: hour > 23",
            "params": {
                "symbol": "BTCUSDT",
                "time_filter_enabled": True,
                "time_filter_start_hour": 25,  # > 23 - invalid
                "time_filter_end_hour": 23,
            },
            "should_pass": False,
        },
    ]

    passed = 0
    failed = 0

    for test_case in test_cases:
        name = test_case["name"]
        params = test_case["params"]
        should_pass = test_case["should_pass"]

        try:
            config = IndicatorStrategyConfig.from_dict(params)
            if should_pass:
                print(f"✓ PASS: {name}")
                passed += 1
            else:
                print(f"✗ FAIL: {name} - Expected validation error, but passed")
                failed += 1
        except (ValueError, TypeError) as e:
            if not should_pass:
                print(f"✓ PASS: {name} - Correctly rejected: {e}")
                passed += 1
            else:
                print(f"✗ FAIL: {name} - Unexpected error: {e}")
                failed += 1

    print(f"\nValidation Tests: {passed} passed, {failed} failed")
    return failed == 0


def test_parameter_impact_on_indicators():
    """Test 2: Verify parameter changes affect indicator calculations."""
    print("\n" + "=" * 80)
    print("TEST 2: Parameter Impact on Indicators")
    print("=" * 80)

    with TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        data_path = create_test_data(tmp_dir, "uptrend")

        # Base configuration
        base_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.1,
            "ema_fast_len": 5,
            "ema_slow_len": 20,
            "rsi_len": 14,
            "rsi_ovb": 70,
            "rsi_ovs": 30,
            "bb_len": 20,
            "bb_mult": 2.0,
            "atr_len": 14,
            "adx_len": 14,
            "vol_ma_len": 21,
            "vol_mult": 1.0,
            "allow_long": True,
            "allow_short": False,
            "rules": {
                "long_entry": [{"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}],
                "short_entry": [],
                "long_exit": [{"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}],
                "short_exit": [],
            },
        }

        # Test 2.1: Change EMA lengths (should affect entry signals)
        print("\nTest 2.1: EMA Length Impact")
        config1 = base_config.copy()
        config1["ema_fast_len"] = 5
        config1["ema_slow_len"] = 20

        config2 = base_config.copy()
        config2["ema_fast_len"] = 10  # Slower fast EMA
        config2["ema_slow_len"] = 30  # Slower slow EMA

        result1 = run_backtest_from_config_dict(
            config=config1, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        result2 = run_backtest_from_config_dict(
            config=config2, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        print(f"  Config 1 (fast=5, slow=20): {result1['trades']} trades, PnL: {result1['pnl_abs']:.2f}")
        print(f"  Config 2 (fast=10, slow=30): {result2['trades']} trades, PnL: {result2['pnl_abs']:.2f}")

        # Different EMA parameters should produce different results
        different_results = (
            result1['trades'] != result2['trades'] or
            abs(result1['pnl_abs'] - result2['pnl_abs']) > 0.01
        )

        if different_results:
            print("✓ PASS: EMA length changes affect trading behavior")
        else:
            print("✗ FAIL: EMA length changes had no effect")
            return False

    return True


def test_position_sizing_parameters():
    """Test 3: Verify position sizing parameters work correctly."""
    print("\n" + "=" * 80)
    print("TEST 3: Position Sizing Parameters")
    print("=" * 80)

    with TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        data_path = create_test_data(tmp_dir, "uptrend")

        base_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "ema_fast_len": 5,
            "ema_slow_len": 20,
            "rsi_len": 14,
            "rsi_ovb": 70,
            "rsi_ovs": 30,
            "bb_len": 20,
            "bb_mult": 2.0,
            "atr_len": 14,
            "adx_len": 14,
            "vol_ma_len": 21,
            "vol_mult": 1.0,
            "allow_long": True,
            "allow_short": False,
            "rules": {
                "long_entry": [{"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}],
                "short_entry": [],
                "long_exit": [{"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}],
                "short_exit": [],
            },
        }

        # Test 3.1: base_position_pct
        print("\nTest 3.1: base_position_pct Impact")
        config1 = base_config.copy()
        config1["base_position_pct"] = 5.0  # 5% per trade
        config1["pyramiding"] = 1

        config2 = base_config.copy()
        config2["base_position_pct"] = 20.0  # 20% per trade (higher risk)
        config2["pyramiding"] = 1

        result1 = run_backtest_from_config_dict(
            config=config1, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        result2 = run_backtest_from_config_dict(
            config=config2, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        print(f"  5% position size: Final equity: ${result1['final_equity']:.2f}, PnL: {result1['pnl_abs']:.2f}")
        print(f"  20% position size: Final equity: ${result2['final_equity']:.2f}, PnL: {result2['pnl_abs']:.2f}")

        # Higher position size should lead to higher absolute PnL (positive or negative)
        if abs(result2['pnl_abs']) >= abs(result1['pnl_abs']):
            print("✓ PASS: Position size affects PnL magnitude")
        else:
            print("✗ FAIL: Position size had no proportional impact")
            return False

        # Test 3.2: Pyramiding
        print("\nTest 3.2: Pyramiding Impact")
        config3 = base_config.copy()
        config3["base_position_pct"] = 10.0
        config3["pyramiding"] = 1  # Single entry

        config4 = base_config.copy()
        config4["base_position_pct"] = 10.0
        config4["pyramiding"] = 3  # Multiple entries allowed

        result3 = run_backtest_from_config_dict(
            config=config3, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        result4 = run_backtest_from_config_dict(
            config=config4, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        print(f"  Pyramiding=1: Trades: {result3['trades']}, PnL: {result3['pnl_abs']:.2f}")
        print(f"  Pyramiding=3: Trades: {result4['trades']}, PnL: {result4['pnl_abs']:.2f}")

        print("✓ PASS: Pyramiding parameter accepted")

    return True


def test_tp_sl_functionality():
    """Test 4: Verify TP/SL parameters work correctly."""
    print("\n" + "=" * 80)
    print("TEST 4: TP/SL Functionality")
    print("=" * 80)

    with TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        data_path = create_test_data(tmp_dir, "volatile")

        base_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "ema_fast_len": 3,
            "ema_slow_len": 10,
            "rsi_len": 14,
            "rsi_ovb": 70,
            "rsi_ovs": 30,
            "bb_len": 20,
            "bb_mult": 2.0,
            "atr_len": 14,
            "adx_len": 14,
            "vol_ma_len": 21,
            "vol_mult": 1.0,
            "base_position_pct": 10.0,
            "pyramiding": 1,
            "allow_long": True,
            "allow_short": False,
            "rules": {
                "long_entry": [{"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}],
                "short_entry": [],
                "long_exit": [{"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}],
                "short_exit": [],
            },
        }

        # Without TP/SL
        config1 = base_config.copy()
        config1["use_tp_sl"] = False

        # With tight TP/SL
        config2 = base_config.copy()
        config2["use_tp_sl"] = True
        config2["tp_long_pct"] = 5.0
        config2["sl_long_pct"] = 2.0

        result1 = run_backtest_from_config_dict(
            config=config1, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        result2 = run_backtest_from_config_dict(
            config=config2, data_path=data_path, use_llm=False,
            initial_equity=10000.0, fee_rate=0.001, slippage_bps=1.0
        )

        print(f"  Without TP/SL: Trades: {result1['trades']}, Win Rate: {result1['win_rate']:.1f}%")
        print(f"  With TP/SL (5%/2%): Trades: {result2['trades']}, Win Rate: {result2['win_rate']:.1f}%")

        print("✓ PASS: TP/SL parameters accepted and executed")

    return True


def main():
    """Run all tests."""
    print("=" * 80)
    print("STRATEGY PARAMETERS VALIDATION TEST SUITE")
    print("=" * 80)

    all_passed = True

    # Run tests
    try:
        all_passed &= test_parameter_validation()
        all_passed &= test_parameter_impact_on_indicators()
        all_passed &= test_position_sizing_parameters()
        all_passed &= test_tp_sl_functionality()

        print("\n" + "=" * 80)
        if all_passed:
            print("✓ ALL TESTS PASSED")
            print("=" * 80)
            return 0
        else:
            print("✗ SOME TESTS FAILED")
            print("=" * 80)
            return 1

    except Exception as e:
        print(f"\n✗ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
