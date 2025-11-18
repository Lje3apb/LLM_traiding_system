"""Tests for live trading API endpoints."""

import json
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from llm_trading_system.api.server import app
from llm_trading_system.engine.live_service import get_session_manager

# Create test client
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_session_manager():
    """Clean session manager before each test."""
    # Get the manager and clear all sessions
    manager = get_session_manager()
    with manager._lock:
        # Stop any running sessions
        for session in list(manager._sessions.values()):
            if session.status == "running":
                session.engine.stop()
        # Clear all sessions
        manager._sessions.clear()
    yield
    # Cleanup after test
    with manager._lock:
        for session in list(manager._sessions.values()):
            if session.status == "running":
                session.engine.stop()
        manager._sessions.clear()


def test_create_paper_session_success():
    """Test creating a paper trading session successfully."""
    # Mock environment to ensure paper mode
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        # Create a test strategy config
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "allow_short": False,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [{"left": "ema_fast", "op": ">", "right": "ema_slow"}],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        # Create session request
        request_data = {
            "mode": "paper",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "strategy_config": strategy_config,
            "initial_deposit": 50000.0,
            "llm_enabled": False,
        }

        # Send POST request
        response = client.post("/api/live/sessions", json=request_data)

        # Verify response
        assert response.status_code == 200, f"Response: {response.text}"
        data = response.json()

        # Check response structure
        assert "session_id" in data
        assert data["mode"] == "paper"
        assert data["symbol"] == "BTCUSDT"
        assert data["status"] == "created"
        assert data["llm_enabled"] is False

        # Check last_state contains initial deposit
        assert "last_state" in data
        assert data["last_state"]["equity"] == 50000.0
        assert data["last_state"]["balance"] == 50000.0
        assert data["last_state"]["mode"] == "paper"

        print("✓ Paper session created successfully")


def test_create_paper_session_missing_fields():
    """Test creating a session without required fields."""
    # Missing mode
    response = client.post("/api/live/sessions", json={"symbol": "BTCUSDT"})
    assert response.status_code == 400
    assert "mode" in response.json()["detail"].lower()

    # Missing symbol
    response = client.post("/api/live/sessions", json={"mode": "paper"})
    assert response.status_code == 400
    assert "symbol" in response.json()["detail"].lower()

    # Missing strategy_config
    response = client.post(
        "/api/live/sessions", json={"mode": "paper", "symbol": "BTCUSDT"}
    )
    assert response.status_code == 400
    assert "strategy_config" in response.json()["detail"].lower()

    print("✓ Missing field validation works")


def test_create_real_session_without_live_enabled():
    """Test creating a real session when EXCHANGE_LIVE_ENABLED is not set."""
    with mock.patch.dict(
        os.environ,
        {
            "EXCHANGE_TYPE": "paper",  # Ensure we're in paper mode
            "EXCHANGE_LIVE_ENABLED": "false",
        },
    ):
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        request_data = {
            "mode": "real",
            "symbol": "BTCUSDT",
            "strategy_config": strategy_config,
        }

        response = client.post("/api/live/sessions", json=request_data)

        # Should fail with 422 (validation error)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "EXCHANGE_LIVE_ENABLED" in detail or "binance" in detail.lower()

        print("✓ Real trading safety check works (EXCHANGE_LIVE_ENABLED)")


def test_get_session_status():
    """Test getting session status."""
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        # Create a session first
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "ETHUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        create_response = client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "ETHUSDT",
                "strategy_config": strategy_config,
                "initial_deposit": 10000.0,
            },
        )
        assert create_response.status_code == 200
        session_id = create_response.json()["session_id"]

        # Get status
        status_response = client.get(f"/api/live/sessions/{session_id}")
        assert status_response.status_code == 200

        status_data = status_response.json()
        assert status_data["session_id"] == session_id
        assert status_data["mode"] == "paper"
        assert status_data["status"] == "created"

        print("✓ Get session status works")


def test_get_nonexistent_session():
    """Test getting status of a non-existent session."""
    response = client.get("/api/live/sessions/fake-session-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    print("✓ Non-existent session returns 404")


def test_list_sessions():
    """Test listing all sessions."""
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        # Create two sessions
        client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "BTCUSDT",
                "strategy_config": strategy_config,
            },
        )
        client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "ETHUSDT",
                "strategy_config": strategy_config,
            },
        )

        # List sessions
        response = client.get("/api/live/sessions")
        assert response.status_code == 200

        data = response.json()
        assert "sessions" in data
        assert len(data["sessions"]) == 2

        print("✓ List sessions works")


def test_get_account_snapshot_paper():
    """Test getting account snapshot for paper trading."""
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        # Create session with specific initial deposit
        initial_deposit = 25000.0
        create_response = client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "BTCUSDT",
                "strategy_config": strategy_config,
                "initial_deposit": initial_deposit,
            },
        )
        session_id = create_response.json()["session_id"]

        # Get account snapshot
        account_response = client.get(f"/api/live/sessions/{session_id}/account")
        assert account_response.status_code == 200

        account_data = account_response.json()
        assert account_data["mode"] == "paper"
        assert account_data["equity"] == initial_deposit
        assert account_data["balance"] == initial_deposit
        # Position should be None for new session
        assert account_data["position"] is None

        print("✓ Account snapshot for paper trading works")


def test_get_trades_empty():
    """Test getting trades from a new session (should be empty)."""
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        create_response = client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "BTCUSDT",
                "strategy_config": strategy_config,
            },
        )
        session_id = create_response.json()["session_id"]

        # Get trades
        trades_response = client.get(f"/api/live/sessions/{session_id}/trades")
        assert trades_response.status_code == 200

        trades_data = trades_response.json()
        assert "trades" in trades_data
        assert len(trades_data["trades"]) == 0

        print("✓ Get trades (empty) works")


def test_get_bars_empty():
    """Test getting bars from a new session (should be empty)."""
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        create_response = client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "BTCUSDT",
                "strategy_config": strategy_config,
            },
        )
        session_id = create_response.json()["session_id"]

        # Get bars
        bars_response = client.get(f"/api/live/sessions/{session_id}/bars")
        assert bars_response.status_code == 200

        bars_data = bars_response.json()
        assert "bars" in bars_data
        assert len(bars_data["bars"]) == 0

        print("✓ Get bars (empty) works")


def test_websocket_connection():
    """Test WebSocket connection (smoke test)."""
    with mock.patch.dict(os.environ, {"EXCHANGE_TYPE": "paper"}):
        strategy_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "ema_fast_len": 10,
            "ema_slow_len": 30,
            "rsi_len": 14,
            "rules": {
                "long_entry": [],
                "short_entry": [],
                "long_exit": [],
                "short_exit": [],
            },
        }

        # Create session
        create_response = client.post(
            "/api/live/sessions",
            json={
                "mode": "paper",
                "symbol": "BTCUSDT",
                "strategy_config": strategy_config,
            },
        )
        session_id = create_response.json()["session_id"]

        # Test WebSocket connection
        with client.websocket_connect(f"/ws/live/{session_id}") as websocket:
            # Should receive initial state_update
            data = websocket.receive_json()
            assert data["type"] == "state_update"
            assert "payload" in data
            assert data["payload"]["session_id"] == session_id

            # Send ping
            websocket.send_text("ping")

            # Should receive pong or state_update
            data = websocket.receive_json()
            assert data["type"] in ("pong", "state_update")

        print("✓ WebSocket connection works")


def test_websocket_nonexistent_session():
    """Test WebSocket connection to non-existent session."""
    with client.websocket_connect("/ws/live/fake-session-id") as websocket:
        # Should receive error message
        data = websocket.receive_json()
        assert data["type"] == "error"
        assert "not found" in data["message"].lower()

    print("✓ WebSocket non-existent session error works")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
