"""Exchange configuration and client factory.

This module provides utilities for reading exchange configuration from
AppConfig with optional environment variable overrides.
"""

from __future__ import annotations

import os
from typing import Literal

from llm_trading_system.exchange.base import ExchangeClient, ExchangeConfig


def _parse_bool(value: str | None, default: bool) -> bool:
    """Parse boolean from string."""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def get_exchange_config_from_env() -> ExchangeConfig:
    """Load exchange configuration from AppConfig with environment variable overrides.

    Priority (highest to lowest):
        1. Environment variables (BINANCE_* for specific overrides)
        2. AppConfig (config.json - set via Settings UI)
        3. Hard-coded defaults (fallback)

    Environment Variables (all optional - override AppConfig):
        EXCHANGE_TYPE: Exchange type ("binance" or "paper")
        BINANCE_API_KEY: Binance API key
        BINANCE_API_SECRET: Binance API secret
        BINANCE_BASE_URL: Binance API base URL
        BINANCE_TESTNET: Use testnet mode
        BINANCE_TRADING_SYMBOL: Symbol to trade
        BINANCE_LEVERAGE: Leverage for futures trading
        BINANCE_MIN_NOTIONAL: Minimum notional value in USDT
        BINANCE_TIMEOUT: API timeout in seconds
        BINANCE_ENABLE_RATE_LIMIT: Enable rate limiting

    Returns:
        ExchangeConfig populated from AppConfig + env overrides

    Example:
        >>> # Without env vars, uses AppConfig from Settings UI
        >>> config = get_exchange_config_from_env()
        >>> print(config.trading_symbol)  # From config.json
        BTCUSDT

        >>> # With env var override
        >>> os.environ["BINANCE_TESTNET"] = "false"
        >>> config = get_exchange_config_from_env()
        >>> print(config.testnet)  # From env var
        False
    """
    from llm_trading_system.config import load_config

    # Load AppConfig as baseline
    cfg = load_config()

    # Build config with env overrides (env vars take precedence over AppConfig)
    return ExchangeConfig(
        api_key=os.getenv("BINANCE_API_KEY") or cfg.exchange.api_key,
        api_secret=os.getenv("BINANCE_API_SECRET") or cfg.exchange.api_secret,
        base_url=os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com"),  # Hard-coded default
        testnet=(
            _parse_bool(os.getenv("BINANCE_TESTNET"), cfg.exchange.use_testnet)
            if "BINANCE_TESTNET" in os.environ
            else cfg.exchange.use_testnet
        ),
        trading_symbol=os.getenv("BINANCE_TRADING_SYMBOL") or cfg.exchange.default_symbol,
        leverage=int(os.getenv("BINANCE_LEVERAGE", "1")),  # Not in AppConfig yet
        min_notional=float(os.getenv("BINANCE_MIN_NOTIONAL", "10.0")),  # Not in AppConfig yet
        timeout=int(os.getenv("BINANCE_TIMEOUT", "30")),  # Not in AppConfig yet
        enable_rate_limit=_parse_bool(
            os.getenv("BINANCE_ENABLE_RATE_LIMIT"), True  # Default to True
        ),
    )


def get_exchange_type_from_env() -> Literal["binance", "paper"]:
    """Get the exchange type from environment or AppConfig.

    Priority:
        1. EXCHANGE_TYPE environment variable (if set)
        2. AppConfig cfg.exchange.exchange_type
        3. Default: "paper"

    Environment Variables (optional):
        EXCHANGE_TYPE: "binance" for live trading, "paper" for simulation

    Returns:
        Exchange type string

    Example:
        >>> import os
        >>> os.environ["EXCHANGE_TYPE"] = "binance"
        >>> get_exchange_type_from_env()
        'binance'

        >>> # Without env var, uses AppConfig
        >>> del os.environ["EXCHANGE_TYPE"]
        >>> get_exchange_type_from_env()  # Uses config.json
        'paper'
    """
    from llm_trading_system.config import load_config

    # Check env var first (for backward compatibility and overrides)
    if "EXCHANGE_TYPE" in os.environ:
        exchange_type = os.getenv("EXCHANGE_TYPE", "paper").lower()
    else:
        # Use AppConfig
        cfg = load_config()
        exchange_type = cfg.exchange.exchange_type.lower()

    if exchange_type not in ("binance", "paper"):
        raise ValueError(
            f"Invalid exchange_type: {exchange_type}. Must be 'binance' or 'paper'."
        )

    return exchange_type  # type: ignore


def get_exchange_client_from_env(
    *,
    initial_balance: float = 10000.0,
    fee_rate: float = 0.0005,
    slippage_bps: float = 1.0,
) -> ExchangeClient:
    """Create exchange client from environment configuration.

    This is the main factory function for creating exchange clients.
    It reads EXCHANGE_TYPE and other configuration from environment
    variables and returns the appropriate client implementation.

    Environment Variables:
        EXCHANGE_TYPE: "binance" for live trading, "paper" for simulation
        PAPER_INITIAL_BALANCE: Initial balance for paper trading (default: 10000.0)
        PAPER_FEE_RATE: Fee rate for paper trading (default: 0.0005)
        PAPER_SLIPPAGE_BPS: Slippage in bps for paper trading (default: 1.0)
        (Plus all BINANCE_* variables from get_exchange_config_from_env)

    Args:
        initial_balance: Initial balance for paper trading (can be overridden by env)
        fee_rate: Fee rate for paper trading (can be overridden by env)
        slippage_bps: Slippage for paper trading (can be overridden by env)

    Returns:
        ExchangeClient instance (BinanceFuturesClient or PaperExchangeClient)

    Raises:
        ValueError: If EXCHANGE_TYPE is invalid or required config is missing
        ImportError: If required dependencies are not installed

    Example:
        >>> import os
        >>> os.environ["EXCHANGE_TYPE"] = "paper"
        >>> client = get_exchange_client_from_env()
        >>> isinstance(client, PaperExchangeClient)
        True
    """
    config = get_exchange_config_from_env()
    exchange_type = get_exchange_type_from_env()

    if exchange_type == "paper":
        # Get paper trading parameters from environment
        initial_balance = float(
            os.getenv("PAPER_INITIAL_BALANCE", str(initial_balance))
        )
        fee_rate = float(os.getenv("PAPER_FEE_RATE", str(fee_rate)))
        slippage_bps = float(os.getenv("PAPER_SLIPPAGE_BPS", str(slippage_bps)))

        from llm_trading_system.exchange.paper import PaperExchangeClient

        return PaperExchangeClient(
            config=config,
            initial_balance=initial_balance,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

    elif exchange_type == "binance":
        # Validate required credentials for live trading
        if not config.api_key or not config.api_secret:
            raise ValueError(
                "BINANCE_API_KEY and BINANCE_API_SECRET are required for live trading. "
                "Set EXCHANGE_TYPE=paper for simulation mode."
            )

        from llm_trading_system.exchange.binance import BinanceFuturesClient

        return BinanceFuturesClient(config=config)

    else:
        # This should never happen due to validation in get_exchange_type_from_env
        raise ValueError(f"Unsupported exchange type: {exchange_type}")


__all__ = [
    "get_exchange_config_from_env",
    "get_exchange_type_from_env",
    "get_exchange_client_from_env",
]
