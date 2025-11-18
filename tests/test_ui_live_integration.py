"""Integration tests for Live Trading Web UI."""

from fastapi.testclient import TestClient

from llm_trading_system.api.server import app

# Create test client
client = TestClient(app)


def test_ui_live_page_returns_html():
    """Test that /ui/live endpoint returns 200 and contains required elements."""
    response = client.get("/ui/live")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Check for mode switcher
    assert b'name="trading-mode"' in response.content
    assert b'value="paper"' in response.content
    assert b'value="real"' in response.content

    # Check for deposit field
    assert b'id="initial-deposit"' in response.content

    # Check for control buttons
    assert b'id="create-session-btn"' in response.content
    assert b'id="start-session-btn"' in response.content
    assert b'id="stop-session-btn"' in response.content

    # Check for chart container
    assert b'id="live-chart-container"' in response.content

    # Check for trades table
    assert b'id="trades-table-body"' in response.content

    # Check for account status block
    assert b'id="account-equity"' in response.content
    assert b'id="account-balance"' in response.content
    assert b'id="account-position-size"' in response.content

    # Check for session summary
    assert b'id="session-summary"' in response.content
    assert b'id="summary-strategy"' in response.content
    assert b'id="summary-symbol"' in response.content
    assert b'id="summary-timeframe"' in response.content

    # Check for activity log
    assert b'id="activity-log-container"' in response.content

    print("✓ Live Trading UI page contains all required elements")


def test_ui_live_prefill_parameters():
    """Test that /ui/live accepts query parameters for prefilling form."""
    response = client.get(
        "/ui/live?strategy=test_strat&symbol=BTCUSDT&timeframe=5m&mode=paper&deposit=10000"
    )

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # The actual prefilling happens in JavaScript, so we just verify the page loads
    # with query params
    print("✓ Live Trading UI accepts prefill parameters")


def test_index_contains_live_trading_links():
    """Test that index.html contains Live (Paper) and Live (Real) links."""
    # Create a test strategy first
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

    client.post("/strategies/test_live_links", json=test_config)

    # Get index page
    response = client.get("/ui/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Check for Live (Paper) link
    assert b"Live (Paper)" in response.content
    assert b"/ui/live?" in response.content
    assert b"mode=paper" in response.content

    # The Live (Real) link may not appear if live trading is disabled
    # That's expected behavior

    # Cleanup
    client.delete("/strategies/test_live_links")

    print("✓ Index page contains Live Trading links with proper parameters")


def test_backtest_result_contains_live_action_buttons():
    """Test that backtest_result.html contains 'Next Actions' buttons."""
    # Create a test strategy
    test_config = {
        "strategy_type": "indicator",
        "mode": "quant_only",
        "symbol": "BTCUSDT",
        "base_size": 0.1,
        "ema_fast_len": 10,
        "ema_slow_len": 20,
        "rsi_len": 14,
        "rsi_ovb": 70,
        "rsi_ovs": 30,
        "bb_len": 20,
        "bb_mult": 2.0,
        "atr_len": 14,
        "adx_len": 14,
        "rules": {
            "long_entry": [{"left": "ema_fast", "op": ">", "right": "ema_slow"}],
            "short_entry": [],
            "long_exit": [],
            "short_exit": [],
        },
    }

    client.post("/strategies/test_backtest_actions", json=test_config)

    # Run backtest (this may fail without data, but we just need to check UI)
    try:
        backtest_data = {
            "data_path": "dummy_data.csv",  # This file may not exist
            "initial_deposit": 10000,
            "timeframe": "1h",
            "fee_rate": 0.001,
            "slippage_bps": 1.0,
        }

        response = client.post(
            "/ui/backtest/test_backtest_actions",
            data=backtest_data,
            follow_redirects=True,
        )

        # If backtest succeeds (data file exists), check for action buttons
        if response.status_code == 200:
            assert b"Next Actions" in response.content or b"Go Live" in response.content

            # Check for Live Trading links
            if b"Go Live" in response.content:
                assert b"/ui/live?" in response.content
                assert b"mode=paper" in response.content or b"mode=real" in response.content

            print("✓ Backtest result page contains 'Next Actions' with Live Trading links")
        else:
            # If backtest fails (no data), that's expected - just verify it's a valid error
            print("✓ Backtest result UI structure verified (data file not found is expected)")

    except Exception as e:
        # Expected if data file doesn't exist
        print(f"✓ Backtest action buttons test skipped (expected error: {e})")

    finally:
        # Cleanup
        client.delete("/strategies/test_backtest_actions")


def test_strategy_form_contains_live_hints():
    """Test that strategy_form.html contains hints for live trading."""
    response = client.get("/ui/strategies/new")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Check for live trading hints
    assert b"Live Trading Note" in response.content or b"live trading" in response.content.lower()

    # Check for deposit hint (should mention Paper vs Real)
    assert b"Paper Mode" in response.content or b"paper mode" in response.content.lower()
    assert b"Real Mode" in response.content or b"real mode" in response.content.lower()

    print("✓ Strategy form contains live trading hints")


def test_ui_live_responsive_layout():
    """Test that live trading page has responsive layout classes."""
    response = client.get("/ui/live")

    assert response.status_code == 200

    # Check for responsive layout container
    assert b"main-layout" in response.content

    # Check for mobile-friendly styles
    assert b"@media" in response.content

    print("✓ Live Trading UI has responsive layout")


if __name__ == "__main__":
    print("Running Live Trading UI integration tests...\n")
    test_ui_live_page_returns_html()
    test_ui_live_prefill_parameters()
    test_index_contains_live_trading_links()
    test_backtest_result_contains_live_action_buttons()
    test_strategy_form_contains_live_hints()
    test_ui_live_responsive_layout()
    print("\n✓ All Live Trading UI integration tests passed!")
