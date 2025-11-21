"""Portfolio and execution simulation utilities."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from llm_trading_system.config.models import RiskConfig
from llm_trading_system.strategies.base import AccountState as StrategyAccountState
from llm_trading_system.strategies.base import Bar, Order

AccountState = StrategyAccountState


@dataclass(slots=True)
class Trade:
    """Represents a completed trade."""

    open_time: datetime
    close_time: datetime | None
    side: Literal["long", "short"]
    entry_price: float
    exit_price: float | None
    size: float
    pnl: float | None = None


@dataclass
class PortfolioSimulator:
    """Executes strategy orders on a single symbol portfolio."""

    symbol: str
    account: AccountState
    fee_rate: float = 0.0005
    slippage_bps: float = 1.0
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    risk_config: RiskConfig | None = None  # Issue #4: Risk management config

    _position_units: float = 0.0
    _position_open_time: datetime | None = None
    _entry_equity: float = 0.0
    _total_entry_fees: float = 0.0
    _is_bankrupt: bool = False
    # Issue #4: Trailing stop tracking
    _highest_equity_in_position: float = 0.0  # Track peak for trailing stop
    # Fix: Track equity BEFORE opening position (before entry fees) for correct trade.pnl calculation
    _equity_before_position: float = 0.0

    def __post_init__(self) -> None:
        """Initialize entry equity tracking after dataclass init."""
        self._entry_equity = self.account.equity
        # Thread safety: Lock protects all state modifications (Issue #3 fix)
        # Prevents race conditions when accessed from multiple threads
        object.__setattr__(self, "_lock", threading.Lock())
        # Issue #4: Initialize risk config with defaults if not provided
        if self.risk_config is None:
            object.__setattr__(self, "risk_config", RiskConfig())

    def process_order(self, order: Order, bar: Bar) -> None:
        """Execute a target order, handling entries and exits.

        Thread-safe: Protected by internal lock.
        """
        with self._lock:  # type: ignore
            self._process_order_unsafe(order, bar)

    def _process_order_unsafe(self, order: Order, bar: Bar) -> None:
        """Internal implementation of process_order (assumes lock is held)."""
        # If bankrupt, ignore all orders except closing existing position
        if self._is_bankrupt:
            if self.account.position_size != 0.0:
                # Allow closing existing position
                target = self._order_to_target(order)
                if target == 0.0:
                    self._close_position(bar)
            return

        target = self._order_to_target(order)
        if abs(target - self.account.position_size) < 1e-9:
            return

        exit_price = order.meta.get("exit_price") if order.meta else None
        current = self.account.position_size
        sizing_equity = self._equity_at_price(bar.close)
        actual_fraction = self._fraction_at_price(bar.close)

        if current == 0.0:
            if target != 0.0:
                self._open_position(target, bar, equity=sizing_equity)
            return

        # Handle position changes
        current = self.account.position_size

        # Case 1: Closing to flat
        if target == 0.0:
            self._close_position(bar, exit_price=exit_price)
            return

        if current * target < 0.0:
            self._close_position(bar, exit_price=exit_price)
            sizing_equity = self._equity_at_price(bar.close)
            actual_fraction = self._fraction_at_price(bar.close)
            self._open_position(target, bar, equity=sizing_equity)
            return

        self._rebase_position(bar.close)
        sizing_equity = self._equity_at_price(bar.close)
        actual_fraction = self._fraction_at_price(bar.close)
        self._adjust_position(
            target,
            bar,
            equity=sizing_equity,
            current_fraction=actual_fraction,
        )

    def mark_to_market(self, bar: Bar) -> float:
        """Update equity based on the latest close price.

        Thread-safe: Protected by internal lock.

        Also checks risk limits (stop loss, take profit, trailing stop).
        If limits are breached, automatically closes the position.
        """
        with self._lock:  # type: ignore
            if self.account.position_size != 0.0 and self.account.entry_price is not None:
                self.account.equity = self._equity_at_price(bar.close)

                # Issue #4: Check risk limits and auto-close if needed
                if self._check_risk_limits_unsafe(bar):
                    # Risk limit breached - close position
                    self._close_position(bar)

            self.equity_curve.append((bar.timestamp, self.account.equity))
            return self.account.equity

    def _check_risk_limits_unsafe(self, bar: Bar) -> bool:
        """Check if any risk limits are breached (assumes lock is held).

        Returns:
            True if position should be closed, False otherwise
        """
        if self.account.position_size == 0.0 or self.account.entry_price is None:
            return False

        if self.risk_config is None:
            return False

        current_price = bar.close
        entry_price = self.account.entry_price

        # Prevent division by zero (should never happen in normal operation)
        if entry_price == 0.0:
            return False

        # Calculate P&L percentage
        pnl_pct = (current_price - entry_price) / entry_price
        if self.account.position_size < 0:  # Short position
            pnl_pct = -pnl_pct

        # Check stop loss
        if self.risk_config.enable_stop_loss:
            if pnl_pct <= -self.risk_config.stop_loss_pct:
                return True  # Stop loss hit

        # Check take profit
        if self.risk_config.enable_take_profit:
            if pnl_pct >= self.risk_config.take_profit_pct:
                return True  # Take profit hit

        # Check trailing stop
        if self.risk_config.enable_trailing_stop and self.account.position_size != 0:
            current_equity = self._equity_at_price(current_price)

            # Update highest equity
            if current_equity > self._highest_equity_in_position:
                self._highest_equity_in_position = current_equity

            # Check if equity dropped from peak by trailing stop percentage
            if self._highest_equity_in_position > 0:
                drawdown_from_peak = (
                    self._highest_equity_in_position - current_equity
                ) / self._highest_equity_in_position

                if drawdown_from_peak >= self.risk_config.trailing_stop_pct:
                    return True  # Trailing stop hit

        # Check time-based exit
        if (
            self.risk_config.enable_time_exit
            and self.risk_config.max_position_hold_minutes > 0
            and self._position_open_time is not None
        ):
            time_held = (bar.timestamp - self._position_open_time).total_seconds() / 60
            if time_held >= self.risk_config.max_position_hold_minutes:
                return True  # Max hold time exceeded

        return False

    def _open_position(self, target: float, bar: Bar, *, equity: float) -> None:
        direction = 1.0 if target > 0 else -1.0
        trade_price = self._apply_slippage(bar.close, is_buy=direction > 0)

        # Prevent division by zero (should never happen with real data)
        if trade_price == 0.0:
            return

        current_equity = equity
        notional = current_equity * abs(target)
        units = (notional / trade_price) * direction
        entry_fee = notional * self.fee_rate

        # Fix: Save equity BEFORE subtracting entry fee for correct trade.pnl calculation
        self._equity_before_position = current_equity

        self.account.equity = current_equity - entry_fee

        # Check for bankruptcy (margin call)
        if self.account.equity <= 0:
            self._is_bankrupt = True
            self.account.equity = 0.0
            self.account.position_size = 0.0
            self.account.entry_price = None
            self._position_units = 0.0
            self._position_open_time = None
            self._total_entry_fees = 0.0
            self._equity_before_position = 0.0
            return

        self._entry_equity = self.account.equity
        self.account.position_size = target
        self.account.entry_price = trade_price
        self._position_units = units
        self._position_open_time = bar.timestamp
        self._total_entry_fees = entry_fee
        # Issue #4: Initialize trailing stop tracking
        self._highest_equity_in_position = self.account.equity

    def _close_position(self, bar: Bar, *, exit_price: float | None = None) -> None:
        if self.account.entry_price is None or self._position_open_time is None:
            return
        direction = 1.0 if self.account.position_size > 0 else -1.0
        trade_exit_price = (
            exit_price
            if exit_price is not None
            else self._apply_slippage(bar.close, is_buy=direction < 0)
        )
        pnl = self._position_units * (trade_exit_price - self.account.entry_price)
        exit_fee = abs(self._position_units) * trade_exit_price * self.fee_rate

        equity_after = self._entry_equity + pnl - exit_fee
        position_fraction = abs(self.account.position_size)

        # Fix: Calculate trade PnL as total equity change from position open to close
        # This correctly includes all fees (entry + partial adjustments + exit)
        # and all PnL from partial position changes (increase/decrease)
        trade_pnl = equity_after - self._equity_before_position

        trade = Trade(
            open_time=self._position_open_time,
            close_time=bar.timestamp,
            side="long" if self.account.position_size > 0 else "short",
            entry_price=self.account.entry_price,
            exit_price=trade_exit_price,
            size=position_fraction,
            pnl=trade_pnl,
        )
        self.trades.append(trade)

        self.account.equity = equity_after
        self.account.position_size = 0.0
        self.account.entry_price = None
        self._position_units = 0.0
        self._position_open_time = None
        self._entry_equity = self.account.equity
        self._total_entry_fees = 0.0
        # Issue #4: Reset trailing stop tracking
        self._highest_equity_in_position = 0.0
        # Fix: Reset equity before position
        self._equity_before_position = 0.0

    def _adjust_position(
        self,
        target: float,
        bar: Bar,
        *,
        equity: float,
        current_fraction: float,
    ) -> None:
        if current_fraction == 0.0:
            self._open_position(target, bar, equity=equity)
            return

        if abs(target) > abs(current_fraction):
            self._increase_position(
                target,
                bar,
                equity=equity,
                current_fraction=current_fraction,
            )
        else:
            self._decrease_position(
                target,
                bar,
                current_fraction=current_fraction,
            )

    def _increase_position(
        self,
        target: float,
        bar: Bar,
        *,
        equity: float,
        current_fraction: float,
    ) -> None:
        delta_fraction = abs(target) - abs(current_fraction)
        if delta_fraction <= 0:
            return

        direction = 1.0 if target > 0 else -1.0
        trade_price = self._apply_slippage(bar.close, is_buy=direction > 0)

        # Prevent division by zero (should never happen with real data)
        if trade_price == 0.0:
            return

        current_equity = equity
        notional = current_equity * delta_fraction
        units_delta = (notional / trade_price) * direction
        fee = notional * self.fee_rate

        self.account.equity = current_equity - fee

        # Check for bankruptcy
        if self.account.equity <= 0:
            self._is_bankrupt = True
            self.account.equity = 0.0
            self.account.position_size = 0.0
            self.account.entry_price = None
            self._position_units = 0.0
            self._position_open_time = None
            self._total_entry_fees = 0.0
            return

        existing_units = self._position_units
        existing_notional = abs(existing_units) * (self.account.entry_price or trade_price)
        new_units = existing_units + units_delta
        new_notional = existing_notional + notional

        # Prevent division by zero (should never happen in normal operation)
        if abs(new_units) == 0.0:
            return

        self._position_units = new_units
        self.account.position_size = target
        self.account.entry_price = new_notional / abs(new_units)
        self._entry_equity = self.account.equity
        self._total_entry_fees += fee

    def _decrease_position(
        self,
        target: float,
        bar: Bar,
        *,
        current_fraction: float,
    ) -> None:
        delta_fraction = abs(current_fraction) - abs(target)
        if delta_fraction <= 0:
            return

        direction = 1.0 if self._position_units > 0 else -1.0
        exit_price = self._apply_slippage(bar.close, is_buy=direction < 0)
        total_units = abs(self._position_units)
        if total_units == 0 or self.account.entry_price is None:
            self.account.position_size = target
            return

        # Prevent division by zero
        if abs(current_fraction) < 1e-9:
            self.account.position_size = target
            return

        units_delta = total_units * (delta_fraction / abs(current_fraction))
        units_delta *= direction
        realized_pnl = units_delta * (exit_price - self.account.entry_price)
        fee = abs(units_delta) * exit_price * self.fee_rate

        self._position_units -= units_delta
        self.account.position_size = target
        self.account.equity = self.account.equity + realized_pnl - fee
        self._entry_equity = self.account.equity

    def _equity_at_price(self, price: float) -> float:
        if self.account.entry_price is None or self.account.position_size == 0.0:
            return self.account.equity
        pnl = self._position_units * (price - self.account.entry_price)
        return self._entry_equity + pnl

    def _fraction_at_price(self, price: float) -> float:
        if self.account.entry_price is None or self.account.position_size == 0.0:
            return 0.0
        equity = self._equity_at_price(price)
        if equity <= 0:
            return 0.0
        notional = abs(self._position_units) * price
        fraction = notional / equity
        return fraction if self._position_units > 0 else -fraction

    def _rebase_position(self, price: float) -> None:
        """Rebase position to current price before adjustments.

        This updates both equity and entry price to reflect current unrealized P&L,
        ensuring that subsequent sizing calculations use the correct equity base
        and future P&L calculations start from this rebased point.
        """
        if self.account.entry_price is None or self.account.position_size == 0.0:
            return
        equity = self._equity_at_price(price)
        self.account.equity = equity
        self._entry_equity = equity
        self.account.entry_price = price  # Update entry price to prevent double-counting P&L

    def get_trades_snapshot(self, limit: int | None = None) -> list[Trade]:
        """Get thread-safe snapshot of trades list.

        Thread-safe: Returns a copy of trades under lock.

        Args:
            limit: Maximum number of recent trades to return (None = all)

        Returns:
            Copy of trades list (most recent last)
        """
        with self._lock:  # type: ignore
            if limit is None:
                return self.trades.copy()
            return self.trades[-limit:].copy() if self.trades else []

    def get_account_snapshot(self) -> AccountState:
        """Get thread-safe snapshot of account state.

        Thread-safe: Returns a copy under lock.

        Returns:
            Copy of current account state
        """
        with self._lock:  # type: ignore
            # AccountState is a dataclass, create a copy
            return AccountState(
                equity=self.account.equity,
                position_size=self.account.position_size,
                entry_price=self.account.entry_price,
                symbol=self.account.symbol,
            )

    def reset_account(self, initial_equity: float) -> None:
        """Reset portfolio state for a fresh paper account.

        This keeps the same PortfolioSimulator instance (so LiveSession and
        LiveTradingEngine references remain valid) while clearing positions,
        trades, and equity history. Primarily used for explicit user-triggered
        resets in paper mode.
        """
        with self._lock:  # type: ignore
            self.account.equity = initial_equity
            self.account.position_size = 0.0
            self.account.entry_price = None

            self._position_units = 0.0
            self._position_open_time = None
            self._entry_equity = initial_equity
            self._total_entry_fees = 0.0
            self._is_bankrupt = False
            self._highest_equity_in_position = 0.0
            self._equity_before_position = initial_equity

            # Clear trade/equity history
            self.trades.clear()
            self.equity_curve.clear()

    def get_position_units(self) -> float:
        """Get thread-safe snapshot of position units.

        Thread-safe: Returns atomic float value under lock.

        Returns:
            Current position units (positive for long, negative for short)
        """
        with self._lock:  # type: ignore
            return self._position_units

    def get_position_snapshot(
        self,
    ) -> tuple[float, float | None, datetime | None]:
        """Get thread-safe snapshot of position state.

        Thread-safe: Returns atomic snapshot under lock.

        Returns:
            Tuple of (position_units, entry_price, position_open_time)
        """
        with self._lock:  # type: ignore
            return (
                self._position_units,
                self.account.entry_price,
                self._position_open_time,
            )

    def get_open_trades_count(self) -> int:
        """Get count of currently open trades.

        Thread-safe: Protected by internal lock.

        Returns:
            1 if position is open, 0 if flat
        """
        with self._lock:  # type: ignore
            return 1 if self.account.position_size != 0.0 else 0

    def get_closed_trades_count(self) -> int:
        """Get count of closed trades.

        Thread-safe: Protected by internal lock.

        Returns:
            Number of completed trades
        """
        with self._lock:  # type: ignore
            return len(self.trades)

    def _apply_slippage(self, price: float, *, is_buy: bool) -> float:
        slip = price * (self.slippage_bps / 10_000)
        return price + slip if is_buy else price - slip

    @staticmethod
    def _order_to_target(order: Order) -> float:
        if order.side == "flat":
            return 0.0
        if order.side == "long":
            return abs(order.size)
        if order.side == "short":
            return -abs(order.size)
        raise ValueError(f"Unknown order side: {order.side}")


__all__ = ["PortfolioSimulator", "AccountState", "Trade"]
