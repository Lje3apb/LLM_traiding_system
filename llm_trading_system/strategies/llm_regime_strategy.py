"""LLM regime-aware strategy stub ready for integration with the core."""

from __future__ import annotations

from typing import Any, Literal

from llm_trading_system.core.regime_engine import evaluate_regime_and_size
from llm_trading_system.strategies.base import AccountState, Bar, Order, Strategy


class LLMRegimeStrategy(Strategy):
    """Strategy scaffold that can periodically query the LLM regime engine."""

    def __init__(
        self,
        symbol: str,
        client: Any,
        base_size: float = 0.01,
        k_max: float = 2.0,
        horizon_bars: int = 60,
    ) -> None:
        super().__init__(symbol)
        self.client = client
        self.base_size = base_size
        self.k_max = k_max
        self.horizon_bars = horizon_bars
        self._bar_index = -1
        self._last_update_bar: int | None = None
        self._target_position = 0.0

    def reset(self) -> None:
        self._bar_index = -1
        self._last_update_bar = None
        self._target_position = 0.0

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        self._bar_index += 1
        if self._should_update_target():
            self._update_target_from_llm(bar, account)

        if abs(self._target_position - account.position_size) < 1e-9:
            return None

        side: Literal["long", "short", "flat"]
        if self._target_position > 0:
            side = "long"
        elif self._target_position < 0:
            side = "short"
        else:
            side = "flat"

        return Order(symbol=self.symbol, side=side, size=abs(self._target_position))

    def _should_update_target(self) -> bool:
        if self._last_update_bar is None:
            return True
        return (self._bar_index - self._last_update_bar) >= self.horizon_bars

    def _update_target_from_llm(self, bar: Bar, account: AccountState) -> None:
        self._last_update_bar = self._bar_index
        # TODO: build historical snapshots per bar and call
        # evaluate_regime_and_size(snapshot, self.client, self.base_size, self.k_max)
        # to derive target positioning once snapshot feeds are available.
        _ = evaluate_regime_and_size  # suppress unused import until integration
        self._target_position = self.base_size


__all__ = ["LLMRegimeStrategy"]
