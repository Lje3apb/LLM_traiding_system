"""Portfolio and execution simulation utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

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

    _position_units: float = 0.0
    _position_open_time: datetime | None = None
    _entry_equity: float = 0.0
    _total_entry_fees: float = 0.0

    def __post_init__(self) -> None:
        self._entry_equity = self.account.equity

    def process_order(self, order: Order, bar: Bar) -> None:
        """Execute a target order, handling entries and exits."""

        target = self._order_to_target(order)
        if abs(target - self.account.position_size) < 1e-9:
            return

        exit_price = order.meta.get("exit_price") if order.meta else None
        current = self.account.position_size

        if current == 0.0:
            if target != 0.0:
                self._open_position(target, bar)
            return

        if target == 0.0:
            self._close_position(bar, exit_price=exit_price)
            return

        if current * target < 0.0:
            self._close_position(bar, exit_price=exit_price)
            self._open_position(target, bar)
            return

        self._adjust_position(target, bar)

    def mark_to_market(self, bar: Bar) -> float:
        """Update equity based on the latest close price."""

        if self.account.position_size != 0.0 and self.account.entry_price is not None:
            pnl = self._position_units * (bar.close - self.account.entry_price)
            self.account.equity = self._entry_equity + pnl
        self.equity_curve.append((bar.timestamp, self.account.equity))
        return self.account.equity

    def _open_position(self, target: float, bar: Bar) -> None:
        direction = 1.0 if target > 0 else -1.0
        trade_price = self._apply_slippage(bar.close, is_buy=direction > 0)
        current_equity = self.account.equity
        notional = current_equity * abs(target)
        units = (notional / trade_price) * direction
        entry_fee = notional * self.fee_rate

        self.account.equity = current_equity - entry_fee
        self._entry_equity = self.account.equity
        self.account.position_size = target
        self.account.entry_price = trade_price
        self._position_units = units
        self._position_open_time = bar.timestamp
        self._total_entry_fees = entry_fee

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
        trade = Trade(
            open_time=self._position_open_time,
            close_time=bar.timestamp,
            side="long" if self.account.position_size > 0 else "short",
            entry_price=self.account.entry_price,
            exit_price=trade_exit_price,
            size=position_fraction,
            pnl=pnl - self._total_entry_fees - exit_fee,
        )
        self.trades.append(trade)

        self.account.equity = equity_after
        self.account.position_size = 0.0
        self.account.entry_price = None
        self._position_units = 0.0
        self._position_open_time = None
        self._entry_equity = self.account.equity
        self._total_entry_fees = 0.0

    def _adjust_position(self, target: float, bar: Bar) -> None:
        current = self.account.position_size
        if current == 0.0:
            self._open_position(target, bar)
            return

        if abs(target) > abs(current):
            self._increase_position(target, bar)
        else:
            self._decrease_position(target, bar)

    def _increase_position(self, target: float, bar: Bar) -> None:
        delta_fraction = abs(target) - abs(self.account.position_size)
        if delta_fraction <= 0:
            return

        direction = 1.0 if target > 0 else -1.0
        trade_price = self._apply_slippage(bar.close, is_buy=direction > 0)
        current_equity = self.account.equity
        notional = current_equity * delta_fraction
        units_delta = (notional / trade_price) * direction
        fee = notional * self.fee_rate

        self.account.equity = current_equity - fee
        existing_units = self._position_units
        existing_notional = abs(existing_units) * (self.account.entry_price or trade_price)
        new_units = existing_units + units_delta
        new_notional = existing_notional + notional
        self._position_units = new_units
        self.account.position_size = target
        self.account.entry_price = new_notional / abs(new_units)
        self._entry_equity = self.account.equity
        self._total_entry_fees += fee

    def _decrease_position(self, target: float, bar: Bar) -> None:
        delta_fraction = abs(self.account.position_size) - abs(target)
        if delta_fraction <= 0:
            return

        direction = 1.0 if self._position_units > 0 else -1.0
        exit_price = self._apply_slippage(bar.close, is_buy=direction < 0)
        total_units = abs(self._position_units)
        if total_units == 0:
            self.account.position_size = target
            return
        units_delta = total_units * (delta_fraction / abs(self.account.position_size))
        units_delta *= direction
        realized_pnl = units_delta * (exit_price - self.account.entry_price)
        fee = abs(units_delta) * exit_price * self.fee_rate

        self._position_units -= units_delta
        self.account.position_size = target
        self.account.equity = self.account.equity + realized_pnl - fee
        self._entry_equity = self.account.equity

    def get_open_trades_count(self) -> int:
        """Get count of currently open trades.

        Returns:
            1 if position is open, 0 if flat
        """
        return 1 if self.account.position_size != 0.0 else 0

    def get_closed_trades_count(self) -> int:
        """Get count of closed trades.

        Returns:
            Number of completed trades
        """
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
