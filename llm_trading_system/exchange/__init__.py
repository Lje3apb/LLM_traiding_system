"""Exchange integration infrastructure layer.

This module provides abstractions and implementations for connecting to
cryptocurrency exchanges, supporting both live trading and paper trading modes.
"""

from llm_trading_system.exchange.base import (
    AccountInfo,
    ExchangeClient,
    ExchangeConfig,
    OrderResult,
    OrderSide,
    OrderType,
    PositionInfo,
)
from llm_trading_system.exchange.config import get_exchange_client_from_env

__all__ = [
    "ExchangeConfig",
    "ExchangeClient",
    "OrderResult",
    "OrderType",
    "OrderSide",
    "AccountInfo",
    "PositionInfo",
    "get_exchange_client_from_env",
]
