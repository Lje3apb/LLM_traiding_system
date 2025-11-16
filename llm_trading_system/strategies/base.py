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


@dataclass(slots=True)
class AccountState:
    """Represents current account metrics visible to strategies."""

    equity: float
    position_size: float
    entry_price: float | None
    symbol: str


class Strategy(ABC):
    """Abstract base class for trading strategies."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @abstractmethod
    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Return a desired target order or None to keep the current position."""

    def reset(self) -> None:  # pragma: no cover - optional hook
        """Reset internal state before a new backtest run."""


__all__ = ["Bar", "Order", "AccountState", "Strategy"]
