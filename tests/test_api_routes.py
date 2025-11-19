"""Tests for API routes module."""

import pytest
from fastapi.testclient import TestClient

from llm_trading_system.api.server import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check_returns_ok(self, client):
        """Test that health endpoint returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestStrategiesEndpoints:
    """Tests for /strategies endpoints."""

    def test_list_strategies_returns_items_dict(self, client):
        """Test that list strategies returns dictionary with 'items' key."""
        response = client.get("/strategies")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_get_nonexistent_strategy_returns_404(self, client):
        """Test that getting a nonexistent strategy returns 404."""
        response = client.get("/strategies/nonexistent_strategy_12345")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_save_strategy_requires_strategy_type(self, client):
        """Test that saving a strategy requires strategy_type field."""
        response = client.post(
            "/strategies/test_strategy",
            json={"mode": "backtest"}  # Missing strategy_type
        )
        assert response.status_code == 400
        assert "strategy_type" in response.json()["detail"]

    def test_save_strategy_requires_mode(self, client):
        """Test that saving a strategy requires mode field."""
        response = client.post(
            "/strategies/test_strategy",
            json={"strategy_type": "indicator"}  # Missing mode
        )
        assert response.status_code == 400
        assert "mode" in response.json()["detail"]

    def test_save_and_get_strategy_success(self, client):
        """Test that saving and retrieving a strategy works."""
        strategy_data = {
            "strategy_type": "indicator",
            "mode": "backtest",
            "symbol": "BTCUSDT",
            "timeframe": "1h"
        }

        # Save strategy
        save_response = client.post(
            "/strategies/test_api_strategy",
            json=strategy_data
        )
        assert save_response.status_code == 200
        assert save_response.json()["status"] == "saved"
        assert save_response.json()["name"] == "test_api_strategy"

        # Get strategy
        get_response = client.get("/strategies/test_api_strategy")
        assert get_response.status_code == 200
        retrieved_data = get_response.json()
        assert retrieved_data["strategy_type"] == strategy_data["strategy_type"]
        assert retrieved_data["mode"] == strategy_data["mode"]

        # Cleanup: Delete strategy
        delete_response = client.delete("/strategies/test_api_strategy")
        assert delete_response.status_code == 200

    def test_delete_nonexistent_strategy_returns_404(self, client):
        """Test that deleting a nonexistent strategy returns 404."""
        response = client.delete("/strategies/nonexistent_strategy_99999")
        assert response.status_code == 404


class TestBacktestEndpoint:
    """Tests for /backtest endpoint."""

    def test_backtest_requires_config_field(self, client):
        """Test that backtest requires config field."""
        response = client.post(
            "/backtest",
            json={"data_path": "data/test.csv"}  # Missing config
        )
        assert response.status_code == 400
        assert "config" in response.json()["detail"]

    def test_backtest_requires_data_path_field(self, client):
        """Test that backtest requires data_path field."""
        response = client.post(
            "/backtest",
            json={"config": {"strategy_type": "indicator"}}  # Missing data_path
        )
        assert response.status_code == 400
        assert "data_path" in response.json()["detail"]

    def test_backtest_rejects_path_traversal(self, client):
        """Test that backtest rejects path traversal attempts."""
        response = client.post(
            "/backtest",
            json={
                "config": {"strategy_type": "indicator"},
                "data_path": "../../../etc/passwd"  # Path traversal attempt
            }
        )
        assert response.status_code == 400
        assert "Invalid data_path" in response.json()["detail"]


class TestLiveSessionsEndpoints:
    """Tests for /api/live/sessions endpoints."""

    def test_list_sessions_returns_sessions_dict(self, client):
        """Test that list sessions returns dictionary with 'sessions' key."""
        response = client.get("/api/live/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_get_nonexistent_session_returns_404(self, client):
        """Test that getting a nonexistent session returns 404."""
        response = client.get("/api/live/sessions/nonexistent_session_12345")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
