"""Binance Futures exchange client implementation.

This module provides live trading integration with Binance Futures using the ccxt library.
Supports both testnet and mainnet, with configurable leverage and order types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    import ccxt
except ImportError:
    raise ImportError(
        "ccxt library is required for Binance integration. "
        "Install it with: pip install ccxt"
    )

from llm_trading_system.exchange.base import (
    AccountInfo,
    ExchangeConfig,
    OrderResult,
    OrderSide,
    OrderType,
    PositionInfo,
)
from llm_trading_system.strategies.base import Bar


class BinanceFuturesClient:
    """Binance Futures exchange client.

    Provides live trading functionality for Binance Futures (USDT-M),
    supporting market and limit orders with configurable leverage.

    Attributes:
        config: Exchange configuration
        exchange: CCXT exchange instance
    """

    def __init__(self, config: ExchangeConfig) -> None:
        """Initialize Binance Futures client.

        Args:
            config: Exchange configuration with API credentials

        Raises:
            ValueError: If required configuration is missing
        """
        self.config = config

        # Initialize CCXT Binance futures exchange
        exchange_options: dict[str, Any] = {
            "apiKey": config.api_key,
            "secret": config.api_secret,
            "enableRateLimit": config.enable_rate_limit,
            "timeout": config.timeout * 1000,  # ccxt uses milliseconds
            "options": {
                "defaultType": "future",  # Use USDT-M futures
            },
        }

        # Configure testnet if enabled
        if config.testnet:
            exchange_options["options"]["defaultType"] = "future"
            self.exchange = ccxt.binance(exchange_options)
            self.exchange.set_sandbox_mode(True)
        else:
            self.exchange = ccxt.binance(exchange_options)

        # Load markets to initialize exchange
        try:
            self.exchange.load_markets()
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Binance: {e}")

        # Set leverage if specified
        if config.leverage > 1:
            try:
                self.exchange.set_leverage(config.leverage, config.trading_symbol)
            except Exception as e:
                # Some exchanges don't support setting leverage via API
                print(f"Warning: Could not set leverage: {e}")

    def get_account_info(self) -> AccountInfo:
        """Retrieve current account information.

        Returns:
            AccountInfo with balances and positions

        Raises:
            Exception: If API request fails
        """
        try:
            balance = self.exchange.fetch_balance()
            positions = self.get_open_positions()

            # USDT balance for futures
            usdt_balance = balance.get("USDT", {})
            total = usdt_balance.get("total", 0.0)
            free = usdt_balance.get("free", 0.0)

            # Calculate total unrealized PnL from positions
            unrealized_pnl = sum(pos.unrealized_pnl for pos in positions)

            return AccountInfo(
                total_balance=total,
                available_balance=free,
                unrealized_pnl=unrealized_pnl,
                positions=positions,
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            raise RuntimeError(f"Failed to fetch account info: {e}")

    def get_open_positions(self) -> list[PositionInfo]:
        """Get all open positions.

        Returns:
            List of open positions

        Raises:
            Exception: If API request fails
        """
        try:
            positions_data = self.exchange.fetch_positions()
            positions = []

            for pos in positions_data:
                # Skip closed positions
                contracts = pos.get("contracts", 0.0)
                if contracts == 0.0:
                    continue

                symbol = pos.get("symbol", "")
                side = pos.get("side", "")
                size = contracts if side == "long" else -contracts

                positions.append(
                    PositionInfo(
                        symbol=symbol,
                        size=size,
                        entry_price=pos.get("entryPrice", 0.0),
                        unrealized_pnl=pos.get("unrealizedPnl", 0.0),
                        leverage=pos.get("leverage", 1),
                        liquidation_price=pos.get("liquidationPrice"),
                    )
                )

            return positions
        except Exception as e:
            raise RuntimeError(f"Failed to fetch positions: {e}")

    def get_position(self, symbol: str) -> PositionInfo | None:
        """Get position for a specific symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")

        Returns:
            PositionInfo if position exists, None otherwise

        Raises:
            Exception: If API request fails
        """
        positions = self.get_open_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None

    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        """Get all open orders for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")

        Returns:
            List of open orders

        Raises:
            Exception: If API request fails
        """
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            result = []

            for order in orders:
                result.append(
                    OrderResult(
                        order_id=str(order["id"]),
                        symbol=order["symbol"],
                        side="buy" if order["side"] == "buy" else "sell",
                        order_type="limit" if order["type"] == "limit" else "market",
                        price=order.get("price", 0.0),
                        quantity=order.get("amount", 0.0),
                        filled_quantity=order.get("filled", 0.0),
                        status=order.get("status", "unknown"),
                        timestamp=datetime.fromtimestamp(
                            order["timestamp"] / 1000, tz=timezone.utc
                        ),
                        commission=order.get("fee", {}).get("cost", 0.0),
                    )
                )

            return result
        except Exception as e:
            raise RuntimeError(f"Failed to fetch open orders: {e}")

    def get_latest_price(self, symbol: str) -> float:
        """Get the latest price for a symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")

        Returns:
            Current price

        Raises:
            Exception: If API request fails
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker["last"]
        except Exception as e:
            raise RuntimeError(f"Failed to fetch price for {symbol}: {e}")

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
        try:
            # Fetch last 2 candles to ensure we get a complete one
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=2)

            if not ohlcv:
                raise ValueError(f"No OHLCV data available for {symbol}")

            # Use the most recent complete candle
            candle = ohlcv[-1]

            return Bar(
                timestamp=datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc),
                open=candle[1],
                high=candle[2],
                low=candle[3],
                close=candle[4],
                volume=candle[5],
            )
        except Exception as e:
            raise RuntimeError(f"Failed to fetch bar for {symbol}: {e}")

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
        """Place an order on Binance Futures.

        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            side: Order side ("buy" or "sell")
            quantity: Order quantity in base currency
            order_type: Type of order ("market" or "limit")
            price: Limit price (required for limit orders)
            reduce_only: Whether this order only reduces position
            leverage: Leverage to use (if different from config)

        Returns:
            OrderResult with execution details

        Raises:
            ValueError: If parameters are invalid
            Exception: If order placement fails
        """
        # Validate inputs
        if order_type == "limit" and price is None:
            raise ValueError("Price is required for limit orders")

        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")

        # Set leverage if specified
        if leverage is not None and leverage != self.config.leverage:
            try:
                self.exchange.set_leverage(leverage, symbol)
            except Exception as e:
                print(f"Warning: Could not set leverage to {leverage}: {e}")

        try:
            # Prepare order parameters
            params: dict[str, Any] = {}
            if reduce_only:
                params["reduceOnly"] = True

            # Place order
            if order_type == "market":
                order = self.exchange.create_market_order(
                    symbol, side, quantity, params
                )
            else:  # limit order
                order = self.exchange.create_limit_order(
                    symbol, side, quantity, price, params
                )

            # Parse response
            return OrderResult(
                order_id=str(order["id"]),
                symbol=order["symbol"],
                side="buy" if order["side"] == "buy" else "sell",
                order_type=order_type,
                price=order.get("price", order.get("average", price or 0.0)),
                quantity=order.get("amount", quantity),
                filled_quantity=order.get("filled", 0.0),
                status=order.get("status", "unknown"),
                timestamp=datetime.fromtimestamp(
                    order["timestamp"] / 1000, tz=timezone.utc
                ),
                commission=order.get("fee", {}).get("cost", 0.0),
            )
        except Exception as e:
            raise RuntimeError(f"Failed to place {order_type} {side} order: {e}")

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
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to cancel order {order_id}: {e}")

    def get_exchange_time(self) -> datetime:
        """Get current Binance server time.

        Returns:
            Current server time

        Raises:
            Exception: If API request fails
        """
        try:
            timestamp = self.exchange.fetch_time()
            return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch exchange time: {e}")

    def time_sync(self) -> None:
        """Synchronize local time with Binance server.

        Binance requires accurate timestamps for signed requests.
        CCXT handles this automatically, but this method can be called
        to force a time sync if needed.

        Raises:
            Exception: If synchronization fails
        """
        try:
            # CCXT handles time sync automatically via load_time_difference
            self.exchange.load_time_difference()
        except Exception as e:
            print(f"Warning: Time sync failed: {e}")


__all__ = ["BinanceFuturesClient"]
