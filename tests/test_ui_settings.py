"""Tests for settings UI page."""

import pytest
from fastapi.testclient import TestClient

from llm_trading_system.api.server import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_settings_page_loads(client):
    """Test that settings page loads successfully."""
    response = client.get("/ui/settings")
    assert response.status_code == 200
    assert b"System Settings" in response.content
    assert b"LLM and Models" in response.content


def test_settings_page_contains_form(client):
    """Test that settings page contains the configuration form."""
    response = client.get("/ui/settings")
    assert response.status_code == 200

    content = response.content.decode()

    # Check for form sections
    assert "LLM and Models" in content
    assert "API Keys and External Services" in content
    assert "Market and Regime" in content
    assert "Risk and Aggressiveness" in content
    assert "Exchange and Real Trading" in content
    assert "UI Defaults" in content

    # Check for key form fields
    assert 'name="llm_provider"' in content
    assert 'name="default_model"' in content
    assert 'name="ollama_base_url"' in content
    assert 'name="temperature"' in content
    assert 'name="base_asset"' in content
    assert 'name="k_max"' in content
    assert 'name="exchange_api_key"' in content


def test_settings_page_shows_saved_message(client):
    """Test that settings page shows success message after save."""
    response = client.get("/ui/settings?saved=1")
    assert response.status_code == 200
    assert b"Settings saved successfully" in response.content


def test_settings_page_loads_config(client):
    """Test that settings page loads current configuration."""
    response = client.get("/ui/settings")
    assert response.status_code == 200

    content = response.content.decode()

    # Check that some config values are present (from defaults)
    # These should be in the HTML as value attributes
    assert "BTCUSDT" in content  # default base_asset
    assert "0.1" in content  # default temperature


def test_settings_navigation_link(client):
    """Test that Settings link is present in navigation."""
    response = client.get("/ui/")
    assert response.status_code == 200
    content = response.content.decode()
    assert '/ui/settings">Settings</a>' in content or '/ui/settings">Settings' in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
