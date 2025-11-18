"""Configuration management package for LLM Trading System.

This package provides a unified configuration service that replaces
scattered os.getenv() calls with a centralized AppConfig object.

Usage:
    from llm_trading_system.config import load_config, save_config

    cfg = load_config()
    print(cfg.api.newsapi_key)
    print(cfg.llm.default_model)

    # Modify and save
    cfg.llm.temperature = 0.2
    save_config(cfg)
"""

from llm_trading_system.config.models import (
    ApiConfig,
    AppConfig,
    ExchangeConfig,
    LlmConfig,
    MarketConfig,
    RiskConfig,
    UiDefaultsConfig,
)
from llm_trading_system.config.service import (
    get_config_path,
    load_config,
    reload_config,
    save_config,
)

__all__ = [
    # Models
    "ApiConfig",
    "LlmConfig",
    "MarketConfig",
    "RiskConfig",
    "ExchangeConfig",
    "UiDefaultsConfig",
    "AppConfig",
    # Service functions
    "get_config_path",
    "load_config",
    "save_config",
    "reload_config",
]
