"""Simple historical backtester for strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from llm_trading_system.engine.data_feed import CSVDataFeed, HistoricalDataFeed
from llm_trading_system.engine.portfolio import AccountState, PortfolioSimulator, Trade
from llm_trading_system.strategies.base import Bar, Strategy


@dataclass(slots=True)
class BacktestResult:
    """Aggregate backtest metrics."""

    equity_curve: list[tuple[datetime, float]]
    trades: list[Trade]
    final_equity: float
    total_return: float
    max_drawdown: float


class Backtester:
    """Executes a strategy over a historical data feed."""

    def __init__(
        self,
        strategy: Strategy,
        data_feed: HistoricalDataFeed,
        initial_equity: float = 10_000.0,
        fee_rate: float = 0.0005,
        slippage_bps: float = 1.0,
        symbol: str = "BTCUSDT",
    ) -> None:
        self.strategy = strategy
        self.data_feed = data_feed
        self.initial_equity = initial_equity
        self.portfolio = PortfolioSimulator(
            symbol=symbol,
            account=AccountState(
                equity=initial_equity,
                position_size=0.0,
                entry_price=None,
                symbol=symbol,
            ),
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

    def run(self) -> BacktestResult:
        """Run the backtest and return aggregate statistics."""

        self.strategy.reset()
        for bar in self.data_feed.iter():
            order = self.strategy.on_bar(bar, self.portfolio.account)
            if order is not None:
                self.portfolio.process_order(order, bar)
            self.portfolio.mark_to_market(bar)

        equity_curve = self.portfolio.equity_curve
        final_equity = equity_curve[-1][1] if equity_curve else self.initial_equity
        total_return = (final_equity / self.initial_equity) - 1.0
        max_drawdown = compute_max_drawdown(equity_curve)
        return BacktestResult(
            equity_curve=equity_curve,
            trades=self.portfolio.trades,
            final_equity=final_equity,
            total_return=total_return,
            max_drawdown=max_drawdown,
        )


def compute_max_drawdown(curve: list[tuple[datetime, float]]) -> float:
    peak = float("-inf")
    max_dd = 0.0
    for _, equity in curve:
        if equity > peak:
            peak = equity
        drawdown = (equity - peak) / peak if peak > 0 else 0.0
        if drawdown < max_dd:
            max_dd = drawdown
    return abs(max_dd)


if __name__ == "__main__":
    from datetime import timedelta, timezone
    from pathlib import Path
    from tempfile import TemporaryDirectory

    class FlatStrategy(Strategy):
        def __init__(self, symbol: str) -> None:
            super().__init__(symbol)

        def on_bar(self, bar: Bar, account: AccountState):
            return None

    strategy = FlatStrategy(symbol="BTCUSDT")
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "bars.csv"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("timestamp,open,high,low,close,volume\n")
            now = datetime.now(tz=timezone.utc)
            for i in range(10):
                ts = now + timedelta(minutes=i)
                price = 100 + i
                fh.write(f"{ts.isoformat()},{price},{price},{price},{price},1000\n")
        feed = CSVDataFeed(path=path, symbol="BTCUSDT")
        result = Backtester(strategy=strategy, data_feed=feed).run()
        print(
            f"Flat strategy final equity: {result.final_equity:.2f}, "
            f"return: {result.total_return:.2%}, drawdown: {result.max_drawdown:.2%}"
        )
