"""Live trading engine for executing strategies in real-time.

This module provides a unified engine for both live and paper trading,
integrating Strategy, Portfolio, and ExchangeClient components.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from llm_trading_system.engine.portfolio import PortfolioSimulator, Trade
from llm_trading_system.exchange.base import ExchangeClient
from llm_trading_system.strategies.base import AccountState, Bar, Order, Strategy

logger = logging.getLogger(__name__)


@dataclass
class BarAggregator:
    """Aggregates price ticks into OHLCV bars.

    Collects price data over a specified timeframe and produces
    complete bars for strategy consumption.

    Attributes:
        timeframe: Timeframe string (e.g., "1m", "5m", "1h")
        interval_seconds: Timeframe in seconds
        current_bar: Bar being built
        last_bar_time: Timestamp of last completed bar
    """

    timeframe: str
    interval_seconds: int
    current_bar: Bar | None = None
    last_bar_time: datetime | None = None

    @classmethod
    def from_timeframe(cls, timeframe: str) -> BarAggregator:
        """Create aggregator from timeframe string.

        Args:
            timeframe: Timeframe like "1m", "5m", "15m", "1h", "4h", "1d"

        Returns:
            BarAggregator instance

        Raises:
            ValueError: If timeframe format is invalid
        """
        interval = parse_timeframe(timeframe)
        return cls(timeframe=timeframe, interval_seconds=interval)

    def add_price(self, price: float, timestamp: datetime, volume: float = 0.0) -> Bar | None:
        """Add a price tick and potentially complete a bar.

        Args:
            price: Current price
            timestamp: Price timestamp
            volume: Volume (if available)

        Returns:
            Completed Bar if interval ended, None otherwise
        """
        # Determine which bar period this price belongs to
        bar_start = self._get_bar_start_time(timestamp)

        # If this is a new bar period
        if self.current_bar is None or bar_start > self.current_bar.timestamp:
            # Save previous bar if exists
            completed_bar = self.current_bar

            # Start new bar
            self.current_bar = Bar(
                timestamp=bar_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            self.last_bar_time = bar_start

            return completed_bar

        # Update current bar
        self.current_bar.high = max(self.current_bar.high, price)
        self.current_bar.low = min(self.current_bar.low, price)
        self.current_bar.close = price
        self.current_bar.volume += volume

        return None

    def _get_bar_start_time(self, timestamp: datetime) -> datetime:
        """Get the start time of the bar period containing the timestamp."""
        ts_seconds = int(timestamp.timestamp())
        bar_start_seconds = (ts_seconds // self.interval_seconds) * self.interval_seconds
        return datetime.fromtimestamp(bar_start_seconds, tz=timezone.utc)


@dataclass
class LiveTradingResult:
    """Results and metrics from live trading session.

    Attributes:
        equity_curve: List of (timestamp, equity) tuples
        trades: List of completed trades
        bars_processed: Number of bars processed
        orders_executed: Number of orders executed
        errors: List of error messages encountered
        start_time: Session start time
        end_time: Session end time (None if still running)
    """

    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    bars_processed: int = 0
    orders_executed: int = 0
    errors: list[str] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None


class LiveTradingEngine:
    """Live trading engine for executing strategies in real-time.

    Integrates Strategy, Portfolio, and ExchangeClient to execute
    trades on either live or paper accounts.

    Attributes:
        strategy: Trading strategy to execute
        exchange: Exchange client (live or paper)
        portfolio: Portfolio simulator for tracking positions
        symbol: Trading symbol
        timeframe: Bar timeframe (e.g., "5m", "1h")
        poll_interval_sec: Seconds between price polls
        use_historical_warmup: Whether to warm up strategy with historical data
    """

    def __init__(
        self,
        strategy: Strategy,
        exchange: ExchangeClient,
        portfolio: PortfolioSimulator,
        symbol: str,
        timeframe: str = "5m",
        poll_interval_sec: float = 1.0,
        use_historical_warmup: bool = False,
    ) -> None:
        """Initialize live trading engine.

        Args:
            strategy: Trading strategy instance
            exchange: Exchange client (BinanceFuturesClient or PaperExchangeClient)
            portfolio: Portfolio simulator instance
            symbol: Trading symbol (e.g., "BTC/USDT")
            timeframe: Timeframe for bars (e.g., "1m", "5m", "1h")
            poll_interval_sec: Seconds between exchange polls
            use_historical_warmup: Load historical bars to warm up strategy
        """
        self.strategy = strategy
        self.exchange = exchange
        self.portfolio = portfolio
        self.symbol = symbol
        self.timeframe = timeframe
        self.poll_interval_sec = poll_interval_sec
        self.use_historical_warmup = use_historical_warmup

        # State
        self.bar_aggregator = BarAggregator.from_timeframe(timeframe)
        self.is_running = False
        self.result = LiveTradingResult()

        # Callbacks
        self.on_new_bar: Callable[[Bar], None] | None = None
        self.on_order_executed: Callable[[Order, Bar], None] | None = None
        self.on_error: Callable[[Exception], None] | None = None

        logger.info(
            f"LiveTradingEngine initialized: symbol={symbol}, "
            f"timeframe={timeframe}, poll_interval={poll_interval_sec}s"
        )

    def run_once(self) -> bool:
        """Execute one trading step (poll price, update bar, check strategy).

        Returns:
            True if step completed successfully, False if error occurred

        Raises:
            Exception: If critical error occurs and no error handler set
        """
        try:
            # Get current price from exchange
            price = self.exchange.get_latest_price(self.symbol)
            timestamp = datetime.now(timezone.utc)

            logger.debug(f"Polled price: {price} at {timestamp}")

            # Add price to bar aggregator
            completed_bar = self.bar_aggregator.add_price(price, timestamp)

            # If we completed a bar, process it
            if completed_bar is not None:
                self._process_bar(completed_bar)

            return True

        except Exception as e:
            error_msg = f"Error in run_once: {e}"
            logger.error(error_msg, exc_info=True)
            self.result.errors.append(error_msg)

            if self.on_error:
                self.on_error(e)
            else:
                raise

            return False

    def run_forever(self) -> LiveTradingResult:
        """Run live trading in an infinite loop.

        This will continuously poll the exchange and execute strategy
        until stop() is called or an unhandled error occurs.

        Returns:
            LiveTradingResult with session statistics

        Raises:
            Exception: If critical error occurs
        """
        logger.info("Starting live trading engine")
        self.is_running = True
        self.result.start_time = datetime.now(timezone.utc)

        # Warm up with historical data if requested
        if self.use_historical_warmup:
            self._warmup_strategy()

        try:
            while self.is_running:
                self.run_once()
                time.sleep(self.poll_interval_sec)

        except KeyboardInterrupt:
            logger.info("Live trading interrupted by user")

        finally:
            self.stop()

        return self.result

    def stop(self) -> None:
        """Stop the live trading engine gracefully."""
        if not self.is_running:
            return

        logger.info("Stopping live trading engine")
        self.is_running = False
        self.result.end_time = datetime.now(timezone.utc)

        # Log final statistics
        duration = (
            (self.result.end_time - self.result.start_time).total_seconds()
            if self.result.start_time and self.result.end_time
            else 0
        )

        logger.info(
            f"Live trading session ended: "
            f"duration={duration:.1f}s, "
            f"bars={self.result.bars_processed}, "
            f"orders={self.result.orders_executed}, "
            f"trades={len(self.result.trades)}, "
            f"errors={len(self.result.errors)}"
        )

    def _process_bar(self, bar: Bar) -> None:
        """Process a completed bar through the strategy.

        Args:
            bar: Completed OHLCV bar
        """
        logger.info(
            f"New bar: {bar.timestamp.isoformat()} | "
            f"O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f}"
        )

        self.result.bars_processed += 1

        try:
            # Trigger callback
            if self.on_new_bar:
                self.on_new_bar(bar)

            # Update portfolio mark-to-market
            self.portfolio.mark_to_market(bar)

            # Update account state for strategy
            account = self.portfolio.account

            # Get order from strategy
            order = self.strategy.on_bar(bar, account)

            # Execute order if strategy returned one
            if order is not None:
                self._execute_order(order, bar)

            # Update result metrics
            self.result.equity_curve.append((bar.timestamp, account.equity))
            self.result.trades = self.portfolio.trades.copy()

        except Exception as e:
            error_msg = f"Error processing bar: {e}"
            logger.error(error_msg, exc_info=True)
            self.result.errors.append(error_msg)

            if self.on_error:
                self.on_error(e)
            else:
                raise

    def _execute_order(self, order: Order, bar: Bar) -> None:
        """Execute an order from the strategy.

        Args:
            order: Order to execute
            bar: Current bar
        """
        logger.info(
            f"Executing order: {order.side} {order.symbol} size={order.size:.4f}"
        )

        try:
            # For paper trading, update market data first
            if hasattr(self.exchange, "update_market_data"):
                self.exchange.update_market_data(bar)

            # Execute through portfolio (which handles paper/live differences)
            self.portfolio.process_order(order, bar)

            self.result.orders_executed += 1

            # Log execution
            logger.info(
                f"Order executed: position={self.portfolio.account.position_size:.4f}, "
                f"equity={self.portfolio.account.equity:.2f}"
            )

            # Trigger callback
            if self.on_order_executed:
                self.on_order_executed(order, bar)

        except Exception as e:
            error_msg = f"Failed to execute order: {e}"
            logger.error(error_msg, exc_info=True)
            self.result.errors.append(error_msg)

            if self.on_error:
                self.on_error(e)
            else:
                raise

    def _warmup_strategy(self) -> None:
        """Warm up strategy with historical bars if available.

        This helps strategies that need historical context (e.g., indicators)
        to have data before live trading starts.
        """
        logger.info(f"Warming up strategy with historical {self.timeframe} bars")

        try:
            # Try to get historical bars from exchange
            # Note: This is a simple implementation, may need adjustment
            # based on exchange capabilities
            historical_bar = self.exchange.get_latest_bar(self.symbol, self.timeframe)

            if historical_bar:
                logger.info(f"Loaded 1 historical bar for warmup")
                # Process through strategy without executing orders
                self.strategy.on_bar(historical_bar, self.portfolio.account)
                self.portfolio.mark_to_market(historical_bar)

        except Exception as e:
            logger.warning(f"Could not load historical data for warmup: {e}")

    def set_callbacks(
        self,
        on_new_bar: Callable[[Bar], None] | None = None,
        on_order_executed: Callable[[Order, Bar], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Set callback functions for events.

        Args:
            on_new_bar: Called when a new bar is completed
            on_order_executed: Called when an order is executed
            on_error: Called when an error occurs
        """
        self.on_new_bar = on_new_bar
        self.on_order_executed = on_order_executed
        self.on_error = on_error


def parse_timeframe(timeframe: str) -> int:
    """Parse timeframe string to seconds.

    Args:
        timeframe: Timeframe like "1m", "5m", "15m", "1h", "4h", "1d"

    Returns:
        Interval in seconds

    Raises:
        ValueError: If format is invalid

    Examples:
        >>> parse_timeframe("1m")
        60
        >>> parse_timeframe("5m")
        300
        >>> parse_timeframe("1h")
        3600
        >>> parse_timeframe("1d")
        86400
    """
    timeframe = timeframe.lower().strip()

    if timeframe.endswith("m"):
        minutes = int(timeframe[:-1])
        return minutes * 60
    elif timeframe.endswith("h"):
        hours = int(timeframe[:-1])
        return hours * 3600
    elif timeframe.endswith("d"):
        days = int(timeframe[:-1])
        return days * 86400
    else:
        raise ValueError(
            f"Invalid timeframe format: {timeframe}. "
            "Expected format like '1m', '5m', '1h', '4h', '1d'"
        )


__all__ = [
    "LiveTradingEngine",
    "LiveTradingResult",
    "BarAggregator",
    "parse_timeframe",
]
