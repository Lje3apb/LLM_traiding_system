"""Configuration service for loading and saving AppConfig."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from llm_trading_system.config.models import (
    ApiConfig,
    AppConfig,
    ExchangeConfig,
    LlmConfig,
    MarketConfig,
    RiskConfig,
    UiDefaultsConfig,
)

# Global cache for config (loaded once per process)
_APP_CONFIG: AppConfig | None = None

logger = logging.getLogger(__name__)


def get_config_path() -> Path:
    """Get path to the configuration file.

    Returns:
        Path to ~/.llm_trading/config.json

    Creates the directory if it doesn't exist.
    """
    config_dir = Path.home() / ".llm_trading"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def _load_from_env() -> AppConfig:
    """Load configuration from environment variables.

    This is used when config.json doesn't exist yet.
    Environment variables override the default values.

    Returns:
        AppConfig populated from environment variables
    """
    # API configuration
    api_config = ApiConfig(
        newsapi_key=os.getenv("NEWSAPI_KEY"),
        newsapi_base_url=os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2"),
        cryptopanic_api_key=os.getenv("CRYPTOPANIC_API_KEY"),
        cryptopanic_base_url=os.getenv("CRYPTOPANIC_BASE_URL", "https://cryptopanic.com/api/v1"),
        coinmetrics_base_url=os.getenv(
            "COINMETRICS_BASE_URL",
            "https://community-api.coinmetrics.io/v4"
        ),
        blockchain_com_base_url=os.getenv(
            "BLOCKCHAIN_COM_BASE_URL",
            "https://api.blockchain.info"
        ),
        binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
        binance_fapi_url=os.getenv("BINANCE_FAPI_URL", "https://fapi.binance.com"),
    )

    # LLM configuration
    llm_config = LlmConfig(
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        default_model=os.getenv("DEFAULT_OLLAMA_MODEL", "llama3.2"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        openai_api_base=os.getenv("OPENAI_API_BASE"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
    )

    # Market configuration
    market_config = MarketConfig(
        base_asset=os.getenv("BASE_ASSET", "BTCUSDT"),
        horizon_hours=int(os.getenv("HORIZON_HOURS", "4")),
        use_news=os.getenv("USE_NEWS", "true").lower() in ("true", "1", "yes"),
        use_onchain=os.getenv("USE_ONCHAIN", "true").lower() in ("true", "1", "yes"),
        use_funding=os.getenv("USE_FUNDING", "true").lower() in ("true", "1", "yes"),
    )

    # Risk configuration
    risk_config = RiskConfig(
        base_long_size=float(os.getenv("BASE_LONG_SIZE", "0.01")),
        base_short_size=float(os.getenv("BASE_SHORT_SIZE", "0.01")),
        k_max=float(os.getenv("K_MAX", "2.0")),
        edge_gain=float(os.getenv("EDGE_GAIN", "2.5")),
        edge_gamma=float(os.getenv("EDGE_GAMMA", "0.7")),
        base_k=float(os.getenv("BASE_K", "0.5")),
    )

    # Exchange configuration
    exchange_config = ExchangeConfig(
        exchange_name=os.getenv("EXCHANGE_NAME", "binance"),
        api_key=os.getenv("EXCHANGE_API_KEY"),
        api_secret=os.getenv("EXCHANGE_API_SECRET"),
        use_testnet=os.getenv("EXCHANGE_USE_TESTNET", "true").lower() in ("true", "1", "yes"),
        live_trading_enabled=os.getenv("EXCHANGE_LIVE_ENABLED", "false").lower() in ("true", "1", "yes"),
        default_symbol=os.getenv("DEFAULT_SYMBOL", "BTCUSDT"),
        default_timeframe=os.getenv("DEFAULT_TIMEFRAME", "5m"),
    )

    # UI defaults configuration
    ui_config = UiDefaultsConfig(
        default_initial_deposit=float(os.getenv("DEFAULT_INITIAL_DEPOSIT", "1000.0")),
        default_backtest_equity=float(os.getenv("DEFAULT_BACKTEST_EQUITY", "1000.0")),
        default_commission=float(os.getenv("DEFAULT_COMMISSION", "0.04")),
        default_slippage=float(os.getenv("DEFAULT_SLIPPAGE", "0.0")),
    )

    return AppConfig(
        api=api_config,
        llm=llm_config,
        market=market_config,
        risk=risk_config,
        exchange=exchange_config,
        ui=ui_config,
    )


def load_config() -> AppConfig:
    """Load application configuration.

    Loading priority:
    1. If already cached in memory, return cached instance
    2. If config.json exists, load from file
    3. Otherwise, create from environment variables and save to file

    Returns:
        AppConfig instance

    Raises:
        ValueError: If config file is invalid JSON
        pydantic.ValidationError: If config data doesn't match schema
    """
    global _APP_CONFIG

    # Return cached config if available
    if _APP_CONFIG is not None:
        return _APP_CONFIG

    config_path = get_config_path()

    # Load from file if it exists
    if config_path.exists():
        try:
            logger.info("Loading configuration from %s", config_path)
            with open(config_path, encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
            _APP_CONFIG = AppConfig(**data)
            logger.info("Configuration loaded successfully")
            return _APP_CONFIG
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse config file %s: %s", config_path, exc)
            raise ValueError(f"Invalid configuration file: {exc}") from exc

    # Create new config from environment variables
    logger.info("No config file found, creating from environment variables")
    _APP_CONFIG = _load_from_env()

    # Save to file for future use
    save_config(_APP_CONFIG)
    logger.info("Configuration saved to %s", config_path)

    return _APP_CONFIG


def save_config(app_config: AppConfig) -> None:
    """Save configuration to file.

    Args:
        app_config: AppConfig instance to save

    Raises:
        IOError: If file cannot be written
    """
    global _APP_CONFIG

    config_path = get_config_path()

    # Convert to dict for JSON serialization
    data = app_config.model_dump(mode="json")

    # Write to file with pretty formatting
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Update cache
    _APP_CONFIG = app_config

    logger.info("Configuration saved to %s", config_path)


def reload_config() -> AppConfig:
    """Reload configuration from file, clearing the cache.

    Useful for development or when config.json is modified externally.

    Returns:
        AppConfig instance loaded from file

    Raises:
        ValueError: If config file doesn't exist or is invalid
    """
    global _APP_CONFIG

    config_path = get_config_path()

    if not config_path.exists():
        raise ValueError(f"Configuration file not found: {config_path}")

    # Clear cache
    _APP_CONFIG = None

    # Load fresh from file
    return load_config()
