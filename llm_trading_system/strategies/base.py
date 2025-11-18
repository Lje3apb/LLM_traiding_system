"""Base strategy primitives for the LLM trading system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(slots=True)
class Bar:
    """Single OHLCV bar used by strategies and the backtester."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class Order:
    """Desired target exposure expressed as a fraction of account equity."""

    symbol: str
    side: Literal["long", "short", "flat"]
    size: float
    meta: dict[str, Any] | None = None

    def __post_init__(self):
        """Validate order parameters (MEDIUM-4 fix)."""
        import math

        if not self.symbol or not isinstance(self.symbol, str):
            raise ValueError(f"Order.symbol must be non-empty string, got {self.symbol}")

        if not math.isfinite(self.size):
            raise ValueError(f"Order.size must be finite, got {self.size}")

        if self.size < 0:
            raise ValueError(f"Order.size must be non-negative, got {self.size}")

        # For flat orders, size should be 0
        if self.side == "flat" and self.size != 0:
            raise ValueError(f"Flat orders must have size=0, got {self.size}")

        # Optional: Warn on very large sizes
        if self.size > 1.0:
            import logging
            logging.getLogger(__name__).warning(f"Order.size {self.size} exceeds 100% of equity")


@dataclass(slots=True)
class AccountState:
    """Represents current account metrics visible to strategies.

    Fields:
        equity: Current account equity in base currency
        position_size: Current position size as fraction of equity
                      (positive=long, negative=short, 0=flat)
        entry_price: Entry price of current position, or None if position_size == 0
        symbol: Trading symbol
    """

    equity: float
    position_size: float
    entry_price: float | None
    symbol: str

    def __post_init__(self):
        """Validate account state (MEDIUM-5 fix)."""
        import logging

        # entry_price should be None when position_size == 0
        if self.position_size == 0 and self.entry_price is not None:
            logging.getLogger(__name__).warning(
                f"AccountState has entry_price={self.entry_price} but position_size=0"
            )

        # entry_price should NOT be None when position_size != 0
        if self.position_size != 0 and self.entry_price is None:
            raise ValueError(
                f"AccountState has position_size={self.position_size} but entry_price=None"
            )


class Strategy(ABC):
    """Abstract base class for trading strategies."""

    def __init__(self, symbol: str) -> None:
        """Initialize strategy.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
        """
        self.symbol = symbol

    @abstractmethod
    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Return a desired target order or None to keep the current position."""

    def reset(self) -> None:  # pragma: no cover - optional hook
        """Reset internal state before a new backtest run."""


__all__ = ["Bar", "Order", "AccountState", "Strategy"]
