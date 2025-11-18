"""Exchange configuration and client factory.

This module provides utilities for reading exchange configuration from
environment variables and creating appropriate exchange clients.
"""

from __future__ import annotations

import os
from typing import Literal

from llm_trading_system.exchange.base import ExchangeClient, ExchangeConfig


def get_exchange_config_from_env() -> ExchangeConfig:
    """Load exchange configuration from environment variables.

    Environment Variables:
        EXCHANGE_TYPE: Exchange type ("binance" or "paper")
        BINANCE_API_KEY: Binance API key (required for live trading)
        BINANCE_API_SECRET: Binance API secret (required for live trading)
        BINANCE_BASE_URL: Binance API base URL (default: https://fapi.binance.com)
        BINANCE_TESTNET: Use testnet mode (default: true)
        BINANCE_TRADING_SYMBOL: Symbol to trade (default: BTC/USDT)
        BINANCE_LEVERAGE: Leverage for futures trading (default: 1)
        BINANCE_MIN_NOTIONAL: Minimum notional value in USDT (default: 10.0)
        BINANCE_TIMEOUT: API timeout in seconds (default: 30)
        BINANCE_ENABLE_RATE_LIMIT: Enable rate limiting (default: true)

    Returns:
        ExchangeConfig populated from environment

    Example:
        >>> import os
        >>> os.environ["EXCHANGE_TYPE"] = "paper"
        >>> config = get_exchange_config_from_env()
        >>> print(config.trading_symbol)
        BTC/USDT
    """
    return ExchangeConfig(
        api_key=os.getenv("BINANCE_API_KEY", ""),
        api_secret=os.getenv("BINANCE_API_SECRET", ""),
        base_url=os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com"),
        testnet=os.getenv("BINANCE_TESTNET", "true").lower() in ("true", "1", "yes"),
        trading_symbol=os.getenv("BINANCE_TRADING_SYMBOL", "BTC/USDT"),
        leverage=int(os.getenv("BINANCE_LEVERAGE", "1")),
        min_notional=float(os.getenv("BINANCE_MIN_NOTIONAL", "10.0")),
        timeout=int(os.getenv("BINANCE_TIMEOUT", "30")),
        enable_rate_limit=os.getenv("BINANCE_ENABLE_RATE_LIMIT", "true").lower()
        in ("true", "1", "yes"),
    )


def get_exchange_type_from_env() -> Literal["binance", "paper"]:
    """Get the exchange type from environment.

    Environment Variables:
        EXCHANGE_TYPE: "binance" for live trading, "paper" for simulation (default: paper)

    Returns:
        Exchange type string

    Example:
        >>> import os
        >>> os.environ["EXCHANGE_TYPE"] = "binance"
        >>> get_exchange_type_from_env()
        'binance'
    """
    exchange_type = os.getenv("EXCHANGE_TYPE", "paper").lower()

    if exchange_type not in ("binance", "paper"):
        raise ValueError(
            f"Invalid EXCHANGE_TYPE: {exchange_type}. Must be 'binance' or 'paper'."
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
