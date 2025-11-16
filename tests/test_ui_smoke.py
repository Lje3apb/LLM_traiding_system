"""Smoke tests for the Web UI."""

from fastapi.testclient import TestClient

from llm_trading_system.api.server import app

# Create test client
client = TestClient(app)


def test_ui_index_returns_html():
    """Test that /ui/ endpoint returns HTML."""
    response = client.get("/ui/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"LLM Trading System" in response.content

    print("✓ UI index page works")


def test_ui_new_strategy_returns_html():
    """Test that /ui/strategies/new endpoint returns HTML form."""
    response = client.get("/ui/strategies/new")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"Create New Strategy" in response.content
    assert b"<form" in response.content

    print("✓ UI new strategy form works")


def test_ui_save_strategy_creates_config():
    """Test that saving a strategy via UI works."""
    form_data = {
        "name": "test_ui_strategy",
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "TESTUSDT",
        "base_size": 0.1,
        "allow_long": True,
        "allow_short": False,
        "ema_fast_len": 10,
        "ema_slow_len": 30,
        "rsi_len": 14,
        "rsi_ovb": 70,
        "rsi_ovs": 30,
        "bb_len": 20,
        "bb_std": 2.0,
        "atr_len": 14,
        "adx_len": 14,
        "k_max": 2.0,
        "llm_horizon_hours": 24,
        "llm_min_prob_edge": 0.55,
        "llm_min_trend_strength": 0.6,
        "llm_refresh_interval_bars": 60,
        "rules_long_entry": '[{"left": "ema_fast", "op": ">", "right": "ema_slow"}]',
        "rules_short_entry": "[]",
        "rules_long_exit": "[]",
        "rules_short_exit": "[]",
    }

    response = client.post("/ui/strategies/new/save", data=form_data, follow_redirects=False)

    # Should redirect to edit page
    assert response.status_code == 303
    assert "/ui/strategies/test_ui_strategy/edit" in response.headers["location"]

    # Verify config was created
    verify_response = client.get("/strategies/test_ui_strategy")
    assert verify_response.status_code == 200

    # Cleanup
    client.delete("/strategies/test_ui_strategy")

    print("✓ UI save strategy works")


def test_ui_edit_strategy_returns_populated_form():
    """Test that editing a strategy shows populated form."""
    # Create a test config first
    test_config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "ema_fast_len": 12,
        "ema_slow_len": 26,
        "base_size": 0.1,
        "rules": {
            "long_entry": [{"left": "ema_fast", "op": ">", "right": "ema_slow"}],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    client.post("/strategies/test_ui_edit", json=test_config)

    # Get edit page
    response = client.get("/ui/strategies/test_ui_edit/edit")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"Edit Strategy: test_ui_edit" in response.content
    assert b"BTCUSDT" in response.content

    # Cleanup
    client.delete("/strategies/test_ui_edit")

    print("✓ UI edit strategy form works")


def test_ui_delete_strategy_removes_config():
    """Test that deleting a strategy via UI works."""
    # Create a test config
    test_config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "rules": {
            "long_entry": [],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    client.post("/strategies/test_ui_delete", json=test_config)

    # Delete via UI
    response = client.post("/ui/strategies/test_ui_delete/delete", follow_redirects=False)

    # Should redirect to index
    assert response.status_code == 303
    assert "/ui/" in response.headers["location"]

    # Verify config was deleted
    verify_response = client.get("/strategies/test_ui_delete")
    assert verify_response.status_code == 404

    print("✓ UI delete strategy works")


def test_ui_backtest_form_returns_html():
    """Test that backtest form page works."""
    # Create a test config
    test_config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "rules": {
            "long_entry": [],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    client.post("/strategies/test_ui_backtest_form", json=test_config)

    # Get backtest form
    response = client.get("/ui/strategies/test_ui_backtest_form/backtest")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"Run Backtest" in response.content
    assert b"data_path" in response.content

    # Cleanup
    client.delete("/strategies/test_ui_backtest_form")

    print("✓ UI backtest form works")


if __name__ == "__main__":
    print("Running UI smoke tests...")
    test_ui_index_returns_html()
    test_ui_new_strategy_returns_html()
    test_ui_save_strategy_creates_config()
    test_ui_edit_strategy_returns_populated_form()
    test_ui_delete_strategy_removes_config()
    test_ui_backtest_form_returns_html()
    print("\n✓ All UI smoke tests passed!")
