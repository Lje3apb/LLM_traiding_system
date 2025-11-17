from datetime import datetime, timezone

import pytest

from llm_trading_system.engine.portfolio import AccountState, PortfolioSimulator
from llm_trading_system.strategies.base import Bar, Order


def _bar(close: float) -> Bar:
    ts = datetime.now(tz=timezone.utc)
    return Bar(timestamp=ts, open=close, high=close, low=close, close=close, volume=1000)


def test_portfolio_uses_current_equity_for_resizing() -> None:
    account = AccountState(symbol="BTCUSDT", equity=10_000.0, position_size=0.0, entry_price=None)
    simulator = PortfolioSimulator(
        symbol="BTCUSDT",
        account=account,
        fee_rate=0.0,
        slippage_bps=0.0,
    )

    first_bar = _bar(100.0)
    simulator.process_order(Order(symbol="BTCUSDT", side="long", size=0.5), first_bar)
    simulator.mark_to_market(first_bar)

    pump_bar = _bar(120.0)
    simulator.process_order(Order(symbol="BTCUSDT", side="long", size=0.75), pump_bar)
    simulator.mark_to_market(pump_bar)

    notional_value = abs(simulator._position_units) * pump_bar.close
    actual_fraction = notional_value / simulator.account.equity
    assert actual_fraction == pytest.approx(0.75, rel=1e-6)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
