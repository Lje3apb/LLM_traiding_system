"""Tests for AppConfig integration into UI and system components.

Проверяет, что AppConfig корректно интегрирован в:
- Backtest UI (дефолтные значения)
- Live Trading UI (дефолтные значения + проверка live_trading_enabled)
- CLI (использование настроек LLM)
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import json

from llm_trading_system.api.server import app
from llm_trading_system.config.service import load_config, save_config, get_config_path


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def temp_config_dir(monkeypatch):
    """Create temporary config directory for isolated testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Override config path to use temp directory
        temp_config_path = Path(temp_dir) / "config.json"

        def mock_get_config_path():
            return temp_config_path

        monkeypatch.setattr(
            "llm_trading_system.config.service.get_config_path",
            mock_get_config_path
        )

        # Clear cached config
        import llm_trading_system.config.service as config_service
        config_service._APP_CONFIG = None

        yield temp_dir

        # Clear cache after test
        config_service._APP_CONFIG = None


class TestConfigIntegration:
    """Test suite for AppConfig integration."""

    def test_load_config_returns_app_config(self, temp_config_dir):
        """Проверка, что load_config() возвращает AppConfig с ожидаемыми дефолтами."""
        cfg = load_config()

        # Проверка структуры
        assert cfg.llm is not None
        assert cfg.api is not None
        assert cfg.market is not None
        assert cfg.risk is not None
        assert cfg.exchange is not None
        assert cfg.ui is not None

        # Проверка дефолтных значений
        assert cfg.llm.llm_provider == "ollama"
        assert cfg.llm.default_model == "llama3.2"
        assert cfg.llm.temperature == 0.1
        assert cfg.market.base_asset == "BTCUSDT"
        assert cfg.ui.default_backtest_equity == 1000.0
        assert cfg.ui.default_commission == 0.04
        assert cfg.ui.default_slippage == 0.0
        assert cfg.exchange.live_trading_enabled is False

    def test_save_and_load_config_round_trip(self, temp_config_dir):
        """Проверка, что save_config + load_config round-trip работает."""
        # Load default config
        cfg = load_config()

        # Modify some values
        cfg.llm.default_model = "test-model"
        cfg.ui.default_backtest_equity = 50000.0
        cfg.exchange.live_trading_enabled = True
        cfg.risk.k_max = 3.5

        # Save config
        save_config(cfg)

        # Clear cache and load again
        import llm_trading_system.config.service as config_service
        config_service._APP_CONFIG = None

        # Load and verify
        cfg_loaded = load_config()
        assert cfg_loaded.llm.default_model == "test-model"
        assert cfg_loaded.ui.default_backtest_equity == 50000.0
        assert cfg_loaded.exchange.live_trading_enabled is True
        assert cfg_loaded.risk.k_max == 3.5

    def test_backtest_ui_uses_app_config_defaults(self, client, temp_config_dir):
        """Проверка, что Backtest UI использует AppConfig для дефолтных значений."""
        # Create a test strategy first
        from llm_trading_system.strategies import storage

        test_config = {
            "strategy_type": "indicator",
            "mode": "quant_only",
            "symbol": "BTCUSDT",
            "base_size": 0.01,
            "allow_long": True,
            "allow_short": False,
            "ema_fast_len": 12,
            "ema_slow_len": 26,
            "rsi_len": 14,
            "rsi_ovb": 70,
            "rsi_ovs": 30,
            "bb_len": 20,
            "bb_mult": 2.0,
            "atr_len": 14,
            "adx_len": 14,
            "k_max": 2.0,
        }
        storage.save_config("test_strategy", test_config)

        # Load config and modify defaults
        cfg = load_config()
        cfg.ui.default_backtest_equity = 25000.0
        cfg.ui.default_commission = 0.002
        cfg.ui.default_slippage = 2.5
        cfg.llm.default_model = "custom-model"
        cfg.llm.ollama_base_url = "http://custom:11434"
        save_config(cfg)

        # Clear cache
        import llm_trading_system.config.service as config_service
        config_service._APP_CONFIG = None

        # Request backtest form
        response = client.get("/ui/strategies/test_strategy/backtest")
        assert response.status_code == 200

        content = response.content.decode()

        # Verify that defaults from AppConfig are present in the HTML
        assert 'value="25000.0"' in content  # default_backtest_equity
        assert 'value="0.002"' in content  # default_commission
        assert 'value="2.5"' in content  # default_slippage
        assert 'value="custom-model"' in content  # default_llm_model
        assert 'value="http://custom:11434"' in content  # default_llm_url

    def test_live_trading_ui_uses_app_config(self, client, temp_config_dir):
        """Проверка, что Live Trading UI использует AppConfig для дефолтов."""
        # Load config and modify defaults
        cfg = load_config()
        cfg.ui.default_initial_deposit = 15000.0
        cfg.exchange.default_symbol = "ETHUSDT"
        cfg.exchange.default_timeframe = "15m"
        cfg.exchange.live_trading_enabled = True
        save_config(cfg)

        # Clear cache
        import llm_trading_system.config.service as config_service
        config_service._APP_CONFIG = None

        # Request live trading page
        response = client.get("/ui/live")
        assert response.status_code == 200

        content = response.content.decode()

        # Verify defaults are used
        assert 'value="15000.0"' in content  # default_initial_deposit
        assert 'data-default="15000.0"' in content  # data-default attribute
        assert 'value="ETHUSDT" selected' in content  # default_symbol
        assert 'value="15m" selected' in content  # default_timeframe

    def test_live_trading_ui_respects_live_enabled_flag(self, client, temp_config_dir):
        """Проверка, что Live Trading UI блокирует real mode если live_trading_enabled=false."""
        # Set live_trading_enabled to False
        cfg = load_config()
        cfg.exchange.live_trading_enabled = False
        save_config(cfg)

        # Clear cache
        import llm_trading_system.config.service as config_service
        config_service._APP_CONFIG = None

        # Request live trading page
        response = client.get("/ui/live")
        assert response.status_code == 200

        content = response.content.decode()

        # Verify that real mode radio is disabled
        assert 'value="real" disabled' in content

        # Verify warning message is shown
        assert "Real trading is disabled" in content
        assert "Enable live trading in" in content
        assert 'href="/ui/settings"' in content

    def test_live_trading_ui_allows_real_mode_when_enabled(self, client, temp_config_dir):
        """Проверка, что Live Trading UI разрешает real mode если live_trading_enabled=true."""
        # Set live_trading_enabled to True
        cfg = load_config()
        cfg.exchange.live_trading_enabled = True
        save_config(cfg)

        # Clear cache
        import llm_trading_system.config.service as config_service
        config_service._APP_CONFIG = None

        # Request live trading page
        response = client.get("/ui/live")
        assert response.status_code == 200

        content = response.content.decode()

        # Verify that real mode radio is NOT disabled (no disabled attribute)
        # We check that there's a real mode option without disabled
        assert 'value="real"' in content
        # Make sure there's no disabled on the real radio
        # (The presence of value="real" disabled would indicate it's disabled)
        real_radio_section = content.split('value="real"')[1].split('>')[0]
        assert 'disabled' not in real_radio_section

    def test_settings_page_uses_list_ollama_models(self, client, temp_config_dir):
        """Проверка, что Settings UI использует list_ollama_models для выбора модели."""
        response = client.get("/ui/settings")
        assert response.status_code == 200

        content = response.content.decode()

        # Verify form sections are present
        assert "LLM and Models" in content
        assert "API Keys and External Services" in content
        assert "Risk and Aggressiveness" in content

        # Verify model selector exists
        assert 'name="default_model"' in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
