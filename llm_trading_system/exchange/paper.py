"""Paper trading exchange client implementation.

This module provides a simulated exchange client for paper trading,
using the existing Portfolio simulator without making network requests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from llm_trading_system.engine.portfolio import AccountState, PortfolioSimulator
from llm_trading_system.exchange.base import (
    AccountInfo,
    ExchangeConfig,
    OrderResult,
    OrderSide,
    OrderType,
    PositionInfo,
)
from llm_trading_system.strategies.base import Bar


class PaperExchangeClient:
    """Paper trading exchange client.

    Simulates exchange operations using the Portfolio simulator,
    allowing the same high-level code to work for both live and paper trading.

    Attributes:
        config: Exchange configuration
        portfolio: Portfolio simulator instance
        current_bar: Most recent bar for price simulation
        order_counter: Counter for generating unique order IDs
    """

    def __init__(
        self,
        config: ExchangeConfig,
        initial_balance: float = 10000.0,
        fee_rate: float = 0.0005,
        slippage_bps: float = 1.0,
    ) -> None:
        """Initialize paper trading client.

        Args:
            config: Exchange configuration
            initial_balance: Starting balance in USDT
            fee_rate: Trading fee rate (0.0005 = 0.05%)
            slippage_bps: Slippage in basis points
        """
        self.config = config
        self.order_counter = 0
        self.current_bar: Bar | None = None

        # Initialize portfolio simulator
        account = AccountState(
            equity=initial_balance,
            position_size=0.0,
            entry_price=None,
            symbol=config.trading_symbol,
        )

        self.portfolio = PortfolioSimulator(
            symbol=config.trading_symbol,
            account=account,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        # Track open limit orders (paper trading simulation)
        self._open_orders: dict[str, dict[str, Any]] = {}

    def update_market_data(self, bar: Bar) -> None:
        """Update the current market data for simulation.

        This should be called before placing orders to ensure
        accurate price simulation.

        Args:
            bar: Latest OHLCV bar
        """
        self.current_bar = bar
        self.portfolio.mark_to_market(bar)

    def get_account_info(self) -> AccountInfo:
        """Retrieve current simulated account information.

        Returns:
            AccountInfo with simulated balances and positions
        """
        positions = self.get_open_positions()
        unrealized_pnl = sum(pos.unrealized_pnl for pos in positions)

        # Available balance is equity minus margin used (Issue #5 - Fixed calculation)
        # position_size is a fraction (e.g., 0.5 = 50% of capital allocated)
        # With leverage, margin used = (position_value / leverage)
        # position_value = |position_units| * current_price
        # Thread-safe access to portfolio state
        account = self.portfolio.get_account_snapshot()
        available = account.equity

        if account.position_size != 0 and self.current_bar:
            # Calculate actual position value in USDT (thread-safe access)
            position_units = abs(self.portfolio.get_position_units())
            current_price = self.current_bar.close
            position_value = position_units * current_price

            # Calculate margin used (accounting for leverage)
            leverage = self.config.leverage if self.config.leverage > 0 else 1
            margin_used = position_value / leverage

            # Available = equity - margin_used
            available = account.equity - margin_used

        return AccountInfo(
            total_balance=account.equity,  # Use thread-safe snapshot
            available_balance=max(0.0, available),
            unrealized_pnl=unrealized_pnl,
            positions=positions,
            timestamp=datetime.now(timezone.utc),
        )

    def get_open_positions(self) -> list[PositionInfo]:
        """Get all simulated open positions.

        Returns:
            List of open positions (0 or 1 for single-position simulator)
        """
        # Thread-safe access to portfolio state
        account = self.portfolio.get_account_snapshot()

        if account.position_size == 0.0:
            return []

        if not self.current_bar or account.entry_price is None:
            return []

        # Calculate unrealized PnL (Issue #4 - Clarified comment)
        # NOTE: _position_units carries the sign (positive for long, negative for short)
        # Therefore, the same formula works for both long and short positions:
        # - Long: positive_units * (current - entry) = profit if current > entry
        # - Short: negative_units * (current - entry) = profit if current < entry (since units are negative)
        current_price = self.current_bar.close

        # Single formula works for both long and short because _position_units carries the sign
        # Thread-safe access to position_units
        position_units = self.portfolio.get_position_units()
        unrealized_pnl = position_units * (current_price - account.entry_price)

        return [
            PositionInfo(
                symbol=self.config.trading_symbol,
                size=account.position_size,
                entry_price=account.entry_price,
                unrealized_pnl=unrealized_pnl,
                leverage=self.config.leverage,
                liquidation_price=None,  # Not calculated in paper trading
            )
        ]

    def get_position(self, symbol: str) -> PositionInfo | None:
        """Get simulated position for a specific symbol.

        Args:
            symbol: Trading symbol

        Returns:
            PositionInfo if position exists, None otherwise
        """
        if symbol != self.config.trading_symbol:
            return None

        positions = self.get_open_positions()
        return positions[0] if positions else None

    def get_open_orders(self, symbol: str) -> list[OrderResult]:
        """Get all simulated open orders for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            List of open limit orders
        """
        if symbol != self.config.trading_symbol:
            return []

        results = []
        for order_id, order_data in self._open_orders.items():
            results.append(
                OrderResult(
                    order_id=order_id,
                    symbol=order_data["symbol"],
                    side=order_data["side"],
                    order_type=order_data["order_type"],
                    price=order_data["price"],
                    quantity=order_data["quantity"],
                    filled_quantity=0.0,
                    status="open",
                    timestamp=order_data["timestamp"],
                    commission=0.0,
                )
            )

        return results

    def get_latest_price(self, symbol: str) -> float:
        """Get the latest simulated price for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Current price from last bar

        Raises:
            ValueError: If no market data available
        """
        if symbol != self.config.trading_symbol:
            raise ValueError(f"Unknown symbol: {symbol}")

        if not self.current_bar:
            raise ValueError("No market data available. Call update_market_data() first.")

        return self.current_bar.close

    def get_latest_bar(self, symbol: str, timeframe: str = "1m") -> Bar:
        """Get the latest OHLCV bar for a symbol.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (ignored in paper trading)

        Returns:
            Most recent bar

        Raises:
            ValueError: If no market data available
        """
        if symbol != self.config.trading_symbol:
            raise ValueError(f"Unknown symbol: {symbol}")

        if not self.current_bar:
            raise ValueError("No market data available. Call update_market_data() first.")

        return self.current_bar

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
        """Place a simulated order.

        Args:
            symbol: Trading symbol
            side: Order side ("buy" or "sell")
            quantity: Order quantity in base currency
            order_type: Type of order ("market" or "limit")
            price: Limit price (required for limit orders)
            reduce_only: Whether this order only reduces position
            leverage: Leverage to use (stored but not enforced in paper trading)

        Returns:
            OrderResult with simulated execution

        Raises:
            ValueError: If parameters are invalid
        """
        if symbol != self.config.trading_symbol:
            raise ValueError(f"Unknown symbol: {symbol}")

        if order_type == "limit" and price is None:
            raise ValueError("Price is required for limit orders")

        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")

        if not self.current_bar:
            raise ValueError("No market data available. Call update_market_data() first.")

        self.order_counter += 1
        order_id = f"paper_{self.order_counter}"
        timestamp = datetime.now(timezone.utc)

        # Handle limit orders (store for potential later execution)
        if order_type == "limit":
            self._open_orders[order_id] = {
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "price": price,
                "quantity": quantity,
                "timestamp": timestamp,
            }

            return OrderResult(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price or 0.0,
                quantity=quantity,
                filled_quantity=0.0,
                status="open",
                timestamp=timestamp,
                commission=0.0,
            )

        # Market order - execute immediately
        execution_price = self.current_bar.close

        # Convert to position fraction for portfolio (thread-safe access)
        account = self.portfolio.get_account_snapshot()
        current_equity = account.equity
        position_value = quantity * execution_price
        target_fraction = position_value / current_equity

        # Determine target position side (thread-safe access)
        current_pos = account.position_size

        # Validate reduce-only orders (Issue #6 - Fixed to reject invalid orders)
        if reduce_only:
            if side == "buy" and current_pos >= 0:
                # Can't reduce a long or flat position with a buy
                raise ValueError(
                    f"Invalid reduce-only order: cannot reduce {('long' if current_pos > 0 else 'flat')} "
                    f"position with a BUY order. Current position: {current_pos}"
                )
            if side == "sell" and current_pos <= 0:
                # Can't reduce a short or flat position with a sell
                raise ValueError(
                    f"Invalid reduce-only order: cannot reduce {('short' if current_pos < 0 else 'flat')} "
                    f"position with a SELL order. Current position: {current_pos}"
                )

        if side == "buy":
            target_side = "long"
        else:  # sell
            target_side = "short"
            target_fraction = -target_fraction

        # Create order for portfolio
        from llm_trading_system.strategies.base import Order

        order = Order(
            symbol=symbol,
            side=target_side,
            size=abs(target_fraction),
        )

        # Execute through portfolio
        self.portfolio.process_order(order, self.current_bar)

        # Calculate commission
        commission = position_value * self.portfolio.fee_rate

        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=execution_price,
            quantity=quantity,
            filled_quantity=quantity,
            status="filled",
            timestamp=timestamp,
            commission=commission,
        )

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a simulated open order.

        Args:
            symbol: Trading symbol
            order_id: Order ID to cancel

        Returns:
            True if cancellation successful

        Raises:
            ValueError: If order not found
        """
        if order_id not in self._open_orders:
            raise ValueError(f"Order {order_id} not found")

        del self._open_orders[order_id]
        return True

    def get_exchange_time(self) -> datetime:
        """Get current simulated exchange time.

        Returns:
            Current UTC time
        """
        return datetime.now(timezone.utc)

    def time_sync(self) -> None:
        """Synchronize time (no-op for paper trading)."""
        pass


__all__ = ["PaperExchangeClient"]
