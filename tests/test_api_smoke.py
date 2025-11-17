"""Smoke tests for the HTTP JSON API."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from llm_trading_system.api.server import app

# Create test client
client = TestClient(app)


def create_test_data_file() -> Path:
    """Create a temporary CSV file with test data."""
    tmp_dir = Path("/tmp")
    path = tmp_dir / "api_test_data.csv"

    with path.open("w", encoding="utf-8") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        now = datetime.now(tz=timezone.utc)

        # Create simple uptrend data
        prices = (
            [120] * 5
            + [120 - i for i in range(1, 11)]
            + [110] * 5
            + [110 + i * 2 for i in range(1, 16)]
            + [140] * 10
        )

        for i, price in enumerate(prices):
            ts = now + timedelta(minutes=i)
            f.write(f"{ts.isoformat()},{price},{price+1},{price-1},{price},1000\n")

    return path


def test_health_returns_ok():
    """Test that /health endpoint returns ok status."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"

    print("✓ Health check endpoint works")


def test_list_strategies():
    """Test that /strategies endpoint lists configs."""
    response = client.get("/strategies")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)

    print(f"✓ List strategies endpoint works ({len(data['items'])} configs found)")


def test_save_and_load_strategy_config_roundtrip():
    """Test saving and loading a strategy configuration."""
    test_config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "TESTUSDT",
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

    # Save config
    save_response = client.post("/strategies/test_api_config", json=test_config)
    assert save_response.status_code == 200
    save_data = save_response.json()
    assert save_data["status"] == "saved"
    assert save_data["name"] == "test_api_config"

    # Load config
    load_response = client.get("/strategies/test_api_config")
    assert load_response.status_code == 200
    loaded_config = load_response.json()

    # Verify roundtrip
    assert loaded_config["strategy_type"] == test_config["strategy_type"]
    assert loaded_config["mode"] == test_config["mode"]
    assert loaded_config["symbol"] == test_config["symbol"]
    assert loaded_config["ema_fast_len"] == test_config["ema_fast_len"]

    # Cleanup: delete the test config
    delete_response = client.delete("/strategies/test_api_config")
    assert delete_response.status_code == 200

    print("✓ Save and load strategy config roundtrip works")


def test_get_nonexistent_strategy_returns_404():
    """Test that getting a non-existent config returns 404."""
    response = client.get("/strategies/nonexistent_config_12345")

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()

    print("✓ Non-existent config correctly returns 404")


def test_save_invalid_config_returns_400():
    """Test that saving an invalid config returns 400."""
    invalid_config = {
        "symbol": "BTCUSDT",
        # Missing strategy_type and mode
    }

    response = client.post("/strategies/invalid_config", json=invalid_config)

    assert response.status_code == 400
    data = response.json()
    assert "strategy_type" in data["detail"].lower()

    print("✓ Invalid config correctly returns 400")


def test_backtest_endpoint_returns_summary_with_required_fields():
    """Test that /backtest endpoint returns a valid summary."""
    # Create test data
    data_path = create_test_data_file()

    # Prepare minimal config
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

    # Run backtest
    request = {
        "config": config,
        "data_path": str(data_path),
        "use_llm": False,
        "initial_equity": 10_000.0,
        "fee_rate": 0.001,
        "slippage_bps": 1.0,
    }

    response = client.post("/backtest", json=request)

    assert response.status_code == 200
    summary = response.json()

    # Check required fields
    assert "symbol" in summary
    assert "bars" in summary
    assert "trades" in summary
    assert "pnl_pct" in summary
    assert "pnl_abs" in summary
    assert "max_drawdown" in summary
    assert "win_rate" in summary
    assert "final_equity" in summary
    assert "equity_curve" in summary

    # Verify types
    assert isinstance(summary["symbol"], str)
    assert isinstance(summary["bars"], int)
    assert isinstance(summary["trades"], int)
    assert isinstance(summary["pnl_pct"], (int, float))
    assert isinstance(summary["max_drawdown"], (int, float))
    assert isinstance(summary["win_rate"], (int, float))
    assert isinstance(summary["final_equity"], (int, float))
    assert isinstance(summary["equity_curve"], list)

    # Verify reasonable values
    assert summary["bars"] > 0
    assert summary["final_equity"] > 0

    print(f"✓ Backtest endpoint works:")
    print(f"  Symbol: {summary['symbol']}")
    print(f"  Bars: {summary['bars']}")
    print(f"  Trades: {summary['trades']}")
    print(f"  P&L: {summary['pnl_pct']:.2f}%")


def test_backtest_with_missing_data_returns_404():
    """Test that backtest with non-existent data file returns 404."""
    config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "rules": {
            "long_entry": [{"left": "ema_fast", "op": ">", "right": "ema_slow"}],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    request = {
        "config": config,
        "data_path": "/nonexistent/path/data.csv",
    }

    response = client.post("/backtest", json=request)

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()

    print("✓ Backtest with missing data correctly returns 404")


def test_backtest_with_invalid_config_returns_400():
    """Test that backtest with invalid config returns 400."""
    data_path = create_test_data_file()

    # Invalid config (missing rules for indicator strategy)
    invalid_config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
    }

    request = {
        "config": invalid_config,
        "data_path": str(data_path),
    }

    response = client.post("/backtest", json=request)

    assert response.status_code == 400
    data = response.json()
    assert "rules" in data["detail"].lower()

    print("✓ Backtest with invalid config correctly returns 400")


if __name__ == "__main__":
    print("Running API smoke tests...")
    test_health_returns_ok()
    test_list_strategies()
    test_save_and_load_strategy_config_roundtrip()
    test_get_nonexistent_strategy_returns_404()
    test_save_invalid_config_returns_400()
    test_backtest_endpoint_returns_summary_with_required_fields()
    test_backtest_with_missing_data_returns_404()
    test_backtest_with_invalid_config_returns_400()
    print("\n✓ All API smoke tests passed!")
