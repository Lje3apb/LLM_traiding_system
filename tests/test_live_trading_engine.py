"""Tests for live trading engine."""

from datetime import datetime, timezone

import pytest

from llm_trading_system.engine.live_trading import (
    BarAggregator,
    LiveTradingEngine,
    parse_timeframe,
)
from llm_trading_system.engine.portfolio import AccountState, PortfolioSimulator
from llm_trading_system.strategies.base import Bar, Order, Strategy


# ============================================================================
# Dummy Exchange Client for Testing
# ============================================================================


class DummyExchangeClient:
    """Dummy exchange client that returns fake prices without network calls.

    This is used for testing the LiveTradingEngine without requiring
    a real exchange connection.
    """

    def __init__(self, symbol: str = "BTC/USDT", initial_price: float = 50000.0):
        self.symbol = symbol
        self.current_price = initial_price
        self.price_sequence: list[float] = []
        self.price_index = 0
        self.orders_executed: list[dict] = []

    def set_price_sequence(self, prices: list[float]) -> None:
        """Set a sequence of prices to return."""
        self.price_sequence = prices
        self.price_index = 0

    def get_latest_price(self, symbol: str) -> float:
        """Get latest fake price."""
        if symbol != self.symbol:
            raise ValueError(f"Unknown symbol: {symbol}")

        # If we have a price sequence, use it
        if self.price_sequence and self.price_index < len(self.price_sequence):
            price = self.price_sequence[self.price_index]
            self.price_index += 1
            self.current_price = price
            return price

        return self.current_price

    def get_latest_bar(self, symbol: str, timeframe: str = "1m") -> Bar:
        """Get latest fake bar."""
        price = self.get_latest_price(symbol)
        return Bar(
            timestamp=datetime.now(timezone.utc),
            open=price,
            high=price * 1.001,
            low=price * 0.999,
            close=price,
            volume=100.0,
        )

    def get_account_info(self):
        """Dummy account info."""
        from llm_trading_system.exchange.base import AccountInfo

        return AccountInfo(
            total_balance=10000.0,
            available_balance=10000.0,
            unrealized_pnl=0.0,
            positions=[],
            timestamp=datetime.now(timezone.utc),
        )

    def get_open_positions(self):
        """Dummy positions."""
        return []

    def get_position(self, symbol: str):
        """Dummy position."""
        return None

    def get_open_orders(self, symbol: str):
        """Dummy orders."""
        return []

    def place_order(self, symbol: str, side: str, quantity: float, **kwargs):
        """Dummy order placement."""
        from llm_trading_system.exchange.base import OrderResult

        self.orders_executed.append(
            {"symbol": symbol, "side": side, "quantity": quantity, "kwargs": kwargs}
        )

        return OrderResult(
            order_id="dummy_" + str(len(self.orders_executed)),
            symbol=symbol,
            side=side,
            order_type="market",
            price=self.current_price,
            quantity=quantity,
            filled_quantity=quantity,
            status="filled",
            timestamp=datetime.now(timezone.utc),
            commission=0.0,
        )

    def cancel_order(self, symbol: str, order_id: str):
        """Dummy order cancellation."""
        return True

    def get_exchange_time(self):
        """Dummy exchange time."""
        return datetime.now(timezone.utc)

    def time_sync(self):
        """Dummy time sync."""
        pass

    def update_market_data(self, bar: Bar):
        """Update market data (for compatibility with paper client)."""
        self.current_price = bar.close


# ============================================================================
# Dummy Strategy for Testing
# ============================================================================


class DummyStrategy(Strategy):
    """Dummy strategy that opens a long position on first bar."""

    def __init__(self, symbol: str):
        super().__init__(symbol)
        self.bars_seen = 0
        self.orders_placed = 0

    def on_bar(self, bar: Bar, account: AccountState) -> Order | None:
        """Open long on first bar, close on second."""
        self.bars_seen += 1

        # First bar: open long if flat
        if self.bars_seen == 1 and account.position_size == 0:
            self.orders_placed += 1
            return Order(symbol=self.symbol, side="long", size=0.5)

        # Second bar: close position
        if self.bars_seen == 2 and account.position_size != 0:
            self.orders_placed += 1
            return Order(symbol=self.symbol, side="flat", size=0.0)

        return None


# ============================================================================
# Tests
# ============================================================================


def test_parse_timeframe():
    """Test timeframe parsing."""
    assert parse_timeframe("1m") == 60
    assert parse_timeframe("5m") == 300
    assert parse_timeframe("15m") == 900
    assert parse_timeframe("1h") == 3600
    assert parse_timeframe("4h") == 14400
    assert parse_timeframe("1d") == 86400

    # Case insensitive
    assert parse_timeframe("1M") == 60
    assert parse_timeframe("1H") == 3600

    # Invalid format
    with pytest.raises(ValueError):
        parse_timeframe("invalid")

    with pytest.raises(ValueError):
        parse_timeframe("5x")


def test_bar_aggregator_creation():
    """Test creating BarAggregator."""
    agg = BarAggregator.from_timeframe("5m")
    assert agg.timeframe == "5m"
    assert agg.interval_seconds == 300
    assert agg.current_bar is None
    assert agg.last_bar_time is None


def test_bar_aggregator_single_bar():
    """Test aggregating a single bar."""
    agg = BarAggregator.from_timeframe("1m")

    # First tick - no completed bar yet
    ts1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = agg.add_price(100.0, ts1)
    assert result is None
    assert agg.current_bar is not None
    assert agg.current_bar.open == 100.0
    assert agg.current_bar.close == 100.0

    # Second tick within same minute - updates current bar
    ts2 = datetime(2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    result = agg.add_price(105.0, ts2)
    assert result is None
    assert agg.current_bar.high == 105.0
    assert agg.current_bar.close == 105.0

    # Third tick in new minute - completes previous bar
    ts3 = datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    result = agg.add_price(102.0, ts3)
    assert result is not None
    assert result.open == 100.0
    assert result.high == 105.0
    assert result.close == 105.0


def test_bar_aggregator_updates_ohlc():
    """Test that bar correctly updates OHLC values."""
    agg = BarAggregator.from_timeframe("1m")
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Add prices to build a bar
    agg.add_price(100.0, base_time)
    agg.add_price(110.0, base_time.replace(second=10))  # New high
    agg.add_price(95.0, base_time.replace(second=20))  # New low
    agg.add_price(105.0, base_time.replace(second=30))  # Final close

    assert agg.current_bar is not None
    assert agg.current_bar.open == 100.0
    assert agg.current_bar.high == 110.0
    assert agg.current_bar.low == 95.0
    assert agg.current_bar.close == 105.0


def test_dummy_exchange_client():
    """Test DummyExchangeClient functionality."""
    exchange = DummyExchangeClient(symbol="BTC/USDT", initial_price=50000.0)

    # Test getting price
    price = exchange.get_latest_price("BTC/USDT")
    assert price == 50000.0

    # Test price sequence
    exchange.set_price_sequence([50100.0, 50200.0, 50300.0])
    assert exchange.get_latest_price("BTC/USDT") == 50100.0
    assert exchange.get_latest_price("BTC/USDT") == 50200.0
    assert exchange.get_latest_price("BTC/USDT") == 50300.0

    # Test unknown symbol
    with pytest.raises(ValueError):
        exchange.get_latest_price("ETH/USDT")


def test_dummy_strategy():
    """Test DummyStrategy behavior."""
    strategy = DummyStrategy("BTC/USDT")
    account = AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT")
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )

    # First bar: should open long
    order = strategy.on_bar(bar, account)
    assert order is not None
    assert order.side == "long"
    assert order.size == 0.5

    # Simulate position opened
    account.position_size = 0.5
    account.entry_price = 50000.0

    # Second bar: should close
    order = strategy.on_bar(bar, account)
    assert order is not None
    assert order.side == "flat"


def test_live_trading_engine_initialization():
    """Test LiveTradingEngine can be created."""
    strategy = DummyStrategy("BTC/USDT")
    exchange = DummyExchangeClient("BTC/USDT")
    portfolio = PortfolioSimulator(
        symbol="BTC/USDT",
        account=AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"),
    )

    engine = LiveTradingEngine(
        strategy=strategy,
        exchange=exchange,
        portfolio=portfolio,
        symbol="BTC/USDT",
        timeframe="1m",
        poll_interval_sec=0.1,
    )

    assert engine.strategy == strategy
    assert engine.exchange == exchange
    assert engine.portfolio == portfolio
    assert engine.symbol == "BTC/USDT"
    assert engine.timeframe == "1m"
    assert not engine.is_running


def test_live_trading_engine_run_once():
    """Test single step execution."""
    strategy = DummyStrategy("BTC/USDT")
    exchange = DummyExchangeClient("BTC/USDT", initial_price=50000.0)
    portfolio = PortfolioSimulator(
        symbol="BTC/USDT",
        account=AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"),
    )

    engine = LiveTradingEngine(
        strategy=strategy,
        exchange=exchange,
        portfolio=portfolio,
        symbol="BTC/USDT",
        timeframe="1m",
    )

    # Run once - should poll price and add to aggregator
    success = engine.run_once()
    assert success is True

    # No bar completed yet (need new minute)
    assert engine.result.bars_processed == 0


def test_live_trading_engine_bar_processing():
    """Test that bars are processed and orders executed."""
    strategy = DummyStrategy("BTC/USDT")
    exchange = DummyExchangeClient("BTC/USDT")
    portfolio = PortfolioSimulator(
        symbol="BTC/USDT",
        account=AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"),
    )

    engine = LiveTradingEngine(
        strategy=strategy,
        exchange=exchange,
        portfolio=portfolio,
        symbol="BTC/USDT",
        timeframe="1m",
    )

    # Simulate two bars by manually processing
    bar1 = Bar(
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    bar2 = Bar(
        timestamp=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        open=50050.0,
        high=50150.0,
        low=50000.0,
        close=50100.0,
        volume=100.0,
    )

    # Process first bar
    engine._process_bar(bar1)
    assert engine.result.bars_processed == 1
    assert engine.result.orders_executed == 1
    assert portfolio.account.position_size != 0  # Position opened

    # Process second bar
    engine._process_bar(bar2)
    assert engine.result.bars_processed == 2
    assert engine.result.orders_executed == 2
    assert portfolio.account.position_size == 0  # Position closed


def test_live_trading_engine_callbacks():
    """Test that callbacks are triggered."""
    strategy = DummyStrategy("BTC/USDT")
    exchange = DummyExchangeClient("BTC/USDT")
    portfolio = PortfolioSimulator(
        symbol="BTC/USDT",
        account=AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"),
    )

    engine = LiveTradingEngine(
        strategy=strategy,
        exchange=exchange,
        portfolio=portfolio,
        symbol="BTC/USDT",
        timeframe="1m",
    )

    # Track callbacks
    bars_received = []
    orders_received = []
    errors_received = []

    def on_bar(bar: Bar):
        bars_received.append(bar)

    def on_order(order: Order, bar: Bar):
        orders_received.append((order, bar))

    def on_error(error: Exception):
        errors_received.append(error)

    engine.set_callbacks(on_new_bar=on_bar, on_order_executed=on_order, on_error=on_error)

    # Process a bar
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )
    engine._process_bar(bar)

    # Verify callbacks were called
    assert len(bars_received) == 1
    assert len(orders_received) == 1


def test_live_trading_engine_error_handling():
    """Test error handling in engine."""

    class ErrorStrategy(Strategy):
        def __init__(self, symbol: str):
            super().__init__(symbol)

        def on_bar(self, bar: Bar, account: AccountState):
            raise ValueError("Intentional error for testing")

    strategy = ErrorStrategy("BTC/USDT")
    exchange = DummyExchangeClient("BTC/USDT")
    portfolio = PortfolioSimulator(
        symbol="BTC/USDT",
        account=AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"),
    )

    engine = LiveTradingEngine(
        strategy=strategy,
        exchange=exchange,
        portfolio=portfolio,
        symbol="BTC/USDT",
        timeframe="1m",
    )

    # Set error handler
    errors = []

    def on_error(e):
        errors.append(e)

    engine.set_callbacks(on_error=on_error)

    # Process bar - should catch error
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    # Should not raise, error should be handled
    engine._process_bar(bar)

    # But it should append to result errors
    assert len(engine.result.errors) > 0


def test_live_trading_engine_stop():
    """Test stopping the engine."""
    strategy = DummyStrategy("BTC/USDT")
    exchange = DummyExchangeClient("BTC/USDT")
    portfolio = PortfolioSimulator(
        symbol="BTC/USDT",
        account=AccountState(equity=10000.0, position_size=0.0, entry_price=None, symbol="BTC/USDT"),
    )

    engine = LiveTradingEngine(
        strategy=strategy,
        exchange=exchange,
        portfolio=portfolio,
        symbol="BTC/USDT",
        timeframe="1m",
    )

    # Start engine
    engine.is_running = True
    engine.result.start_time = datetime.now(timezone.utc)

    # Stop engine
    engine.stop()

    assert not engine.is_running
    assert engine.result.end_time is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
