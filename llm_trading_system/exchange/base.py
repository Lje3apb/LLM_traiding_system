"""Base exchange abstractions and protocols.

This module defines the core interfaces and data structures for exchange
integration, enabling both live and paper trading implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from llm_trading_system.strategies.base import Bar

# Type aliases for clarity
OrderType = Literal["market", "limit"]
OrderSide = Literal["buy", "sell"]


@dataclass(slots=True)
class ExchangeConfig:
    """Configuration for exchange connection.

    Attributes:
        api_key: Exchange API key (required for live trading)
        api_secret: Exchange API secret (required for live trading)
        base_url: Base URL for the exchange API
        testnet: Whether to use testnet/sandbox mode
        trading_symbol: Symbol to trade (e.g., "BTC/USDT")
        leverage: Leverage to use for futures trading
        min_notional: Minimum notional value for orders (USDT)
        timeout: API request timeout in seconds
        enable_rate_limit: Whether to enable rate limiting
    """

    api_key: str = ""
    api_secret: str = ""
    base_url: str = "https://fapi.binance.com"
    testnet: bool = True
    trading_symbol: str = "BTC/USDT"
    leverage: int = 1
    min_notional: float = 10.0
    timeout: int = 30
    enable_rate_limit: bool = True


@dataclass(slots=True)
class OrderResult:
    """Result of placing an order.

    Attributes:
        order_id: Exchange-assigned order ID
        symbol: Trading symbol
        side: Order side (buy/sell)
        order_type: Order type (market/limit)
        price: Execution price (for market orders) or limit price
        quantity: Order quantity in base currency
        filled_quantity: Actually filled quantity
        status: Order status (e.g., "filled", "open", "cancelled")
        timestamp: Order creation timestamp
        commission: Trading fee paid
    """

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: float
    quantity: float
    filled_quantity: float
    status: str
    timestamp: datetime
    commission: float = 0.0


@dataclass(slots=True)
class PositionInfo:
    """Information about an open position.

    Attributes:
        symbol: Trading symbol
        size: Position size (positive for long, negative for short)
        entry_price: Average entry price
        unrealized_pnl: Unrealized profit/loss
        leverage: Position leverage
        liquidation_price: Estimated liquidation price (if applicable)
    """

    symbol: str
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: int = 1
    liquidation_price: float | None = None


@dataclass(slots=True)
class AccountInfo:
    """Account information including balances and positions.

    Attributes:
        total_balance: Total account balance (USDT)
        available_balance: Available balance for trading (USDT)
        unrealized_pnl: Total unrealized profit/loss
        positions: List of open positions
        timestamp: Information retrieval timestamp
    """

    total_balance: float
    available_balance: float
    unrealized_pnl: float
    positions: list[PositionInfo]
    timestamp: datetime


class ExchangeClient(Protocol):
    """Protocol defining the interface for exchange clients.

    This protocol allows for interchangeable implementations supporting
    both live trading and paper trading modes.
    """

    def get_account_info(self) -> AccountInfo:
        """Retrieve current account information.

        Returns:
            AccountInfo object with balances and positions

        Raises:
            Exception: If API request fails
        """
        ...

    def get_open_positions(self) -> list[PositionInfo]:
        """Get all open positions.

        Returns:
            List of open positions

        Raises:
            Exception: If API request fails
        """
        ...

    def get_position(self, symbol: str) -> PositionInfo | None:
        """Get position for a specific symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")

        Returns:
            PositionInfo if position exists, None otherwise

        Raises:
            Exception: If API request fails
        """
        ...

    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        """Get all open orders for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")

        Returns:
            List of open orders

        Raises:
            Exception: If API request fails
        """
        ...

    def get_latest_price(self, symbol: str) -> float:
        """Get the latest price for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")

        Returns:
            Current price

        Raises:
            Exception: If API request fails
        """
        ...

    def get_latest_bar(self, symbol: str, timeframe: str = "1m") -> Bar:
        """Get the latest OHLCV bar for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            timeframe: Timeframe for the bar (e.g., "1m", "5m", "1h")

        Returns:
            Bar object compatible with strategies

        Raises:
            Exception: If API request fails
        """
        ...

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = "market",
        price: float | None = None,
        reduce_only: bool = False,
        leverage: int | None = None,
    ) -> OrderResult:
        """Place an order on the exchange.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            side: Order side ("buy" or "sell")
            quantity: Order quantity in base currency
            order_type: Type of order ("market" or "limit")
            price: Limit price (required for limit orders)
            reduce_only: Whether this order only reduces position
            leverage: Leverage to use (futures only)

        Returns:
            OrderResult with execution details

        Raises:
            ValueError: If parameters are invalid
            Exception: If order placement fails
        """
        ...

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            order_id: Exchange-assigned order ID

        Returns:
            True if cancellation successful

        Raises:
            Exception: If cancellation fails
        """
        ...

    def get_exchange_time(self) -> datetime:
        """Get current exchange server time.

        Returns:
            Current server time

        Raises:
            Exception: If API request fails
        """
        ...

    def time_sync(self) -> None:
        """Synchronize local time with exchange server.

        This may be necessary for exchanges with strict timestamp validation.

        Raises:
            Exception: If synchronization fails
        """
        ...


__all__ = [
    "ExchangeConfig",
    "OrderResult",
    "PositionInfo",
    "AccountInfo",
    "ExchangeClient",
    "OrderType",
    "OrderSide",
]
