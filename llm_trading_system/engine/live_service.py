"""Live trading session management service.

This module provides session management for live/paper trading with real-time
state tracking and API integration.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from llm_trading_system.engine.live_trading import LiveTradingEngine, LiveTradingResult
from llm_trading_system.engine.portfolio import PortfolioSimulator, Trade
from llm_trading_system.exchange.base import ExchangeClient
from llm_trading_system.exchange.config import (
    get_exchange_client_from_env,
    get_exchange_type_from_env,
)
from llm_trading_system.strategies import (
    AccountState,
    Bar,
    LLMRegimeConfig,
    LLMRegimeWrappedStrategy,
    create_strategy_from_config,
)

logger = logging.getLogger(__name__)

# Type aliases
TradingMode = Literal["paper", "real"]
SessionStatus = Literal["created", "running", "stopped", "error"]


@dataclass
class PositionSnapshot:
    """Snapshot of current position state."""

    symbol: str
    size: float
    avg_price: float | None
    unrealized_pnl: float
    realized_pnl: float = 0.0


@dataclass
class TradeSnapshot:
    """Snapshot of a trade for UI."""

    id: str
    timestamp: datetime
    side: Literal["long", "short"]
    quantity: float
    price: float
    pnl: float | None


@dataclass
class BarSnapshot:
    """Snapshot of a bar for UI."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SessionState:
    """Aggregated state of a live session for UI.

    This caches the latest state to avoid repeatedly computing it.
    """

    timestamp: datetime
    last_bar: BarSnapshot | None
    position: PositionSnapshot | None
    equity: float
    balance: float
    realized_pnl: float
    recent_trades: list[TradeSnapshot]
    status: SessionStatus
    mode: TradingMode


@dataclass
class LiveSessionConfig:
    """Configuration for a live trading session.

    Attributes:
        mode: Trading mode ("paper" or "real")
        symbol: Trading symbol (e.g., "BTCUSDT")
        timeframe: Bar timeframe (e.g., "5m", "1h")
        strategy_config: Strategy configuration dict or name
        llm_enabled: Whether to use LLM regime wrapper
        llm_config: LLM regime configuration (if llm_enabled=True)
        initial_deposit: Initial deposit for paper trading (ignored in real mode)
        fee_rate: Trading fee rate (paper mode only)
        slippage_bps: Slippage in basis points (paper mode only)
        poll_interval: Polling interval in seconds
    """

    mode: TradingMode
    symbol: str
    timeframe: str = "5m"
    strategy_config: dict[str, Any] | str | None = None
    llm_enabled: bool = False
    llm_config: dict[str, Any] | None = None
    initial_deposit: float = 10000.0
    fee_rate: float = 0.0005
    slippage_bps: float = 1.0
    poll_interval: float = 1.0

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.mode not in ("paper", "real"):
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'paper' or 'real'")

        if self.mode == "paper" and self.initial_deposit <= 0:
            raise ValueError("initial_deposit must be positive for paper trading")

        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")


class LiveSession:
    """Manages a single live/paper trading session.

    This wraps LiveTradingEngine and provides state tracking,
    callbacks, and API integration.
    """

    def __init__(
        self,
        session_id: str,
        config: LiveSessionConfig,
        engine: LiveTradingEngine,
        exchange: ExchangeClient,
        portfolio: PortfolioSimulator,
    ) -> None:
        """Initialize live session.

        Args:
            session_id: Unique session identifier
            config: Session configuration
            engine: Live trading engine instance
            exchange: Exchange client instance
            portfolio: Portfolio simulator instance
        """
        self.session_id = session_id
        self.config = config
        self.engine = engine
        self.exchange = exchange
        self.portfolio = portfolio

        # State tracking
        self.status: SessionStatus = "created"
        self.last_state: SessionState = self._build_initial_state()
        self.start_time: datetime | None = None
        self.error_message: str | None = None

        # Thread for running engine
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Bar history for charts (limit to reasonable size)
        self._bar_history: list[Bar] = []
        self._max_bars = 5000

        # Setup callbacks to update state
        self.engine.set_callbacks(
            on_new_bar=self._on_new_bar,
            on_order_executed=self._on_order_executed,
            on_error=self._on_error,
        )

        logger.info(
            f"LiveSession {session_id} created: mode={config.mode}, "
            f"symbol={config.symbol}, timeframe={config.timeframe}"
        )

    def start(self) -> None:
        """Start the live trading session in a background thread."""
        with self._lock:
            if self.status == "running":
                raise RuntimeError(f"Session {self.session_id} is already running")

            self.status = "running"
            self.start_time = datetime.now(timezone.utc)
            self._update_last_state()

            # Start engine in background thread
            self._thread = threading.Thread(
                target=self._run_engine, daemon=True, name=f"LiveSession-{self.session_id}"
            )
            self._thread.start()

            logger.info(f"LiveSession {self.session_id} started")

    def stop(self) -> None:
        """Stop the live trading session gracefully.

        Issue #6 fix: Increased timeout and proper resource cleanup.
        """
        with self._lock:
            if self.status != "running":
                logger.warning(
                    f"Session {self.session_id} is not running (status={self.status})"
                )
                return

            logger.info(f"Stopping LiveSession {self.session_id}")
            self.engine.stop()
            self.status = "stopped"
            self._update_last_state()

        # Issue #6: Wait for thread to finish (increased timeout to 30s)
        if self._thread and self._thread.is_alive():
            logger.info(f"Waiting for engine thread to stop (timeout=30s)...")
            self._thread.join(timeout=30.0)

            # Issue #6: Force termination warning if thread still alive
            if self._thread.is_alive():
                logger.error(
                    f"Engine thread for session {self.session_id} did not stop "
                    f"within 30 seconds. Thread may be hung. Consider restarting."
                )

        # Issue #6: Cleanup resources
        self._cleanup_resources()

        logger.info(f"LiveSession {self.session_id} stopped")

    def _cleanup_resources(self) -> None:
        """Clean up session resources.

        Issue #6 fix: Explicit cleanup of exchange, strategy, portfolio resources.
        """
        try:
            # Close exchange connection if it has a cleanup method
            if hasattr(self.exchange, "close") and callable(self.exchange.close):
                try:
                    self.exchange.close()
                    logger.debug(f"Closed exchange connection for session {self.session_id}")
                except Exception as e:
                    logger.warning(f"Error closing exchange connection: {e}")

            # Clear bar history to free memory
            with self._lock:
                self._bar_history.clear()
                logger.debug(f"Cleared bar history for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error during resource cleanup: {e}", exc_info=True)

    def get_status(self) -> dict[str, Any]:
        """Get current session status and state.

        Returns:
            Dictionary with session info, config, and current state
        """
        with self._lock:
            return self.to_status_dict()

    def to_status_dict(self) -> dict[str, Any]:
        """Convert session to status dictionary for API responses.

        Returns:
            Dictionary with session_id, mode, config, status, and last_state
        """
        return {
            "session_id": self.session_id,
            "mode": self.config.mode,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "llm_enabled": self.config.llm_enabled,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "error_message": self.error_message,
            "last_state": self._serialize_state(self.last_state),
        }

    def get_account_snapshot(self) -> dict[str, Any]:
        """Get current account snapshot (equity, balance, position).

        For paper mode, reads from portfolio.
        For real mode, queries exchange for live data.

        Returns:
            Dictionary with equity, balance, and position info
        """
        with self._lock:
            if self.config.mode == "paper":
                # Use portfolio state (thread-safe access)
                account = self.portfolio.get_account_snapshot()
                return {
                    "mode": "paper",
                    "equity": account.equity,
                    "balance": account.equity,  # Same for paper
                    "position": self._get_position_snapshot(),
                }
            else:
                # Query live exchange
                try:
                    account_info = self.exchange.get_account_info()
                    position_info = self.exchange.get_position(self.config.symbol)

                    return {
                        "mode": "real",
                        "equity": account_info.total_balance + account_info.unrealized_pnl,
                        "balance": account_info.total_balance,
                        "position": (
                            {
                                "symbol": position_info.symbol,
                                "size": position_info.size,
                                "avg_price": position_info.entry_price,
                                "unrealized_pnl": position_info.unrealized_pnl,
                            }
                            if position_info
                            else None
                        ),
                    }
                except Exception as e:
                    logger.error(f"Failed to get account snapshot: {e}")
                    # Fallback to cached state
                    return {
                        "mode": "real",
                        "equity": self.last_state.equity,
                        "balance": self.last_state.balance,
                        "position": (
                            asdict(self.last_state.position)
                            if self.last_state.position
                            else None
                        ),
                    }

    def get_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent trades from this session.

        Args:
            limit: Maximum number of trades to return

        Returns:
            List of trade dictionaries
        """
        with self._lock:
            # Thread-safe access to portfolio trades (Issue #1 fix)
            trades = self.portfolio.get_trades_snapshot(limit)
            return [self._trade_to_dict(t, idx) for idx, t in enumerate(trades)]

    def get_recent_bars(self, limit: int = 500) -> list[dict[str, Any]]:
        """Get recent bars for charting.

        Args:
            limit: Maximum number of bars to return

        Returns:
            List of bar dictionaries
        """
        with self._lock:
            bars = self._bar_history[-limit:] if self._bar_history else []
            return [self._bar_to_dict(b) for b in bars]

    # Private methods

    def _run_engine(self) -> None:
        """Run the trading engine (called in background thread)."""
        try:
            logger.info(f"Engine thread started for session {self.session_id}")
            self.engine.run_forever()
        except Exception as e:
            logger.error(
                f"Engine error in session {self.session_id}: {e}", exc_info=True
            )
            with self._lock:
                self.status = "error"
                self.error_message = str(e)
                self._update_last_state()

    def _build_initial_state(self) -> SessionState:
        """Build initial session state."""
        return SessionState(
            timestamp=datetime.now(timezone.utc),
            last_bar=None,
            position=None,
            equity=self.config.initial_deposit if self.config.mode == "paper" else 0.0,
            balance=self.config.initial_deposit if self.config.mode == "paper" else 0.0,
            realized_pnl=0.0,
            recent_trades=[],
            status="created",
            mode=self.config.mode,
        )

    def _update_last_state(self) -> None:
        """Update last_state with current portfolio/exchange state."""
        try:
            # Get equity and balance based on mode
            if self.config.mode == "paper":
                # Thread-safe access to portfolio account
                account = self.portfolio.get_account_snapshot()
                equity = account.equity
                balance = equity  # Paper mode: equity = balance
            else:
                # Real mode: query exchange
                try:
                    account_info = self.exchange.get_account_info()
                    equity = account_info.total_balance + account_info.unrealized_pnl
                    balance = account_info.total_balance
                except Exception as e:
                    logger.warning(f"Failed to query account info: {e}")
                    equity = self.last_state.equity
                    balance = self.last_state.balance

            # Get latest bar
            last_bar_snapshot = None
            if self._bar_history:
                last_bar = self._bar_history[-1]
                last_bar_snapshot = BarSnapshot(
                    timestamp=last_bar.timestamp,
                    open=last_bar.open,
                    high=last_bar.high,
                    low=last_bar.low,
                    close=last_bar.close,
                    volume=last_bar.volume,
                )

            # Get position snapshot
            position = self._get_position_snapshot()

            # Get recent trades (last 10) - thread-safe access
            recent_trades = []
            trades_snapshot = self.portfolio.get_trades_snapshot(10)
            for idx, trade in enumerate(trades_snapshot):
                recent_trades.append(
                    TradeSnapshot(
                        id=f"{self.session_id}-{idx}",
                        timestamp=trade.open_time,
                        side=trade.side,
                        quantity=trade.size,
                        price=trade.entry_price,
                        pnl=trade.pnl,
                    )
                )

            # Calculate realized PnL - thread-safe access
            all_trades = self.portfolio.get_trades_snapshot()
            realized_pnl = sum(t.pnl for t in all_trades if t.pnl is not None)

            self.last_state = SessionState(
                timestamp=datetime.now(timezone.utc),
                last_bar=last_bar_snapshot,
                position=position,
                equity=equity,
                balance=balance,
                realized_pnl=realized_pnl,
                recent_trades=recent_trades,
                status=self.status,
                mode=self.config.mode,
            )

        except Exception as e:
            logger.error(f"Failed to update last_state: {e}", exc_info=True)

    def _get_position_snapshot(self) -> PositionSnapshot | None:
        """Get current position snapshot.

        Thread-safe: Uses portfolio's thread-safe methods (Issue #2 fix).
        """
        # Thread-safe access to account state
        account = self.portfolio.get_account_snapshot()

        if account.position_size == 0:
            return None

        unrealized_pnl = 0.0
        if self._bar_history and account.entry_price:
            current_price = self._bar_history[-1].close
            # Thread-safe access to position units (Issue #2 fix)
            position_units = self.portfolio.get_position_units()
            unrealized_pnl = position_units * (current_price - account.entry_price)

        return PositionSnapshot(
            symbol=self.config.symbol,
            size=account.position_size,
            avg_price=account.entry_price,
            unrealized_pnl=unrealized_pnl,
        )

    def _on_new_bar(self, bar: Bar) -> None:
        """Callback when new bar is created."""
        with self._lock:
            # Add to history
            self._bar_history.append(bar)
            if len(self._bar_history) > self._max_bars:
                self._bar_history.pop(0)

            # Update state
            self._update_last_state()

    def _on_order_executed(self, order: Any, bar: Bar) -> None:
        """Callback when order is executed."""
        with self._lock:
            self._update_last_state()

    def _on_error(self, error: Exception) -> None:
        """Callback when error occurs."""
        with self._lock:
            self.status = "error"
            self.error_message = str(error)
            self._update_last_state()

    def _serialize_state(self, state: SessionState) -> dict[str, Any]:
        """Serialize SessionState for JSON response."""
        return {
            "timestamp": state.timestamp.isoformat(),
            "last_bar": asdict(state.last_bar) if state.last_bar else None,
            "position": asdict(state.position) if state.position else None,
            "equity": state.equity,
            "balance": state.balance,
            "realized_pnl": state.realized_pnl,
            "recent_trades": [asdict(t) for t in state.recent_trades],
            "status": state.status,
            "mode": state.mode,
        }

    def _trade_to_dict(self, trade: Trade, index: int) -> dict[str, Any]:
        """Convert Trade to dictionary."""
        return {
            "id": f"{self.session_id}-{index}",
            "open_time": trade.open_time.isoformat(),
            "close_time": trade.close_time.isoformat() if trade.close_time else None,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "size": trade.size,
            "pnl": trade.pnl,
        }

    def _bar_to_dict(self, bar: Bar) -> dict[str, Any]:
        """Convert Bar to dictionary."""
        return {
            "timestamp": bar.timestamp.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }


class LiveSessionManager:
    """Manages multiple live trading sessions.

    This is a singleton service that creates, tracks, and provides
    access to live trading sessions.

    Issue #5 fix: Implements automatic cleanup of old stopped sessions.
    """

    # Issue #5: Session limits and TTL
    MAX_SESSIONS = 100  # Maximum number of sessions to keep
    SESSION_TTL_SECONDS = 3600  # 1 hour TTL for stopped sessions

    def __init__(self) -> None:
        """Initialize session manager."""
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()
        logger.info("LiveSessionManager initialized")

    def create_session(self, config: LiveSessionConfig) -> str:
        """Create a new live trading session.

        Args:
            config: Session configuration

        Returns:
            Session ID

        Raises:
            ValueError: If configuration is invalid or required env vars missing
        """
        # Validate mode
        if config.mode == "real":
            # Check if real trading is enabled
            exchange_type = get_exchange_type_from_env()
            live_enabled = os.getenv("EXCHANGE_LIVE_ENABLED", "false").lower() == "true"

            if exchange_type != "binance":
                raise ValueError(
                    f"Real trading requires EXCHANGE_TYPE=binance, got {exchange_type}"
                )

            if not live_enabled:
                raise ValueError(
                    "Real trading requires EXCHANGE_LIVE_ENABLED=true in environment. "
                    "This is a safety check to prevent accidental live trading."
                )

            # Check for API keys
            api_key = os.getenv("BINANCE_API_KEY", "")
            api_secret = os.getenv("BINANCE_API_SECRET", "")
            if not api_key or not api_secret:
                raise ValueError(
                    "Real trading requires BINANCE_API_KEY and BINANCE_API_SECRET "
                    "environment variables"
                )

        # Generate session ID
        session_id = str(uuid.uuid4())

        # Create exchange client
        try:
            exchange = get_exchange_client_from_env()
        except Exception as e:
            raise ValueError(f"Failed to create exchange client: {e}")

        # Create strategy
        strategy_config = config.strategy_config
        if isinstance(strategy_config, str):
            # Load from storage
            from llm_trading_system.strategies import storage

            strategy_config = storage.load_config(strategy_config)
        elif strategy_config is None:
            raise ValueError("strategy_config is required")

        try:
            strategy = create_strategy_from_config(strategy_config, llm_client=None)
        except Exception as e:
            raise ValueError(f"Failed to create strategy: {e}")

        # Wrap with LLM if enabled
        if config.llm_enabled:
            llm_config_dict = config.llm_config or {}
            llm_config = LLMRegimeConfig(**llm_config_dict)

            # Create LLM client
            # TODO: Support OpenAI
            from llm_trading_system.core.llm_client import create_ollama_client

            llm_client = create_ollama_client()
            strategy = LLMRegimeWrappedStrategy(
                inner_strategy=strategy,
                llm_client=llm_client,
                regime_config=llm_config,
            )

        # Create portfolio
        initial_equity = (
            config.initial_deposit if config.mode == "paper" else 1000.0  # Placeholder
        )
        account = AccountState(
            equity=initial_equity, position_size=0.0, entry_price=None
        )
        portfolio = PortfolioSimulator(
            symbol=config.symbol,
            account=account,
            fee_rate=config.fee_rate,
            slippage_bps=config.slippage_bps,
        )

        # Create live trading engine
        engine = LiveTradingEngine(
            strategy=strategy,
            exchange=exchange,
            portfolio=portfolio,
            symbol=config.symbol,
            timeframe=config.timeframe,
            poll_interval_sec=config.poll_interval,
        )

        # Create session
        session = LiveSession(
            session_id=session_id,
            config=config,
            engine=engine,
            exchange=exchange,
            portfolio=portfolio,
        )

        # Issue #5: Cleanup old sessions before creating new one
        self._cleanup_old_sessions()

        # Store session
        with self._lock:
            # Issue #5: Check session limit
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise RuntimeError(
                    f"Maximum session limit ({self.MAX_SESSIONS}) reached. "
                    f"Delete old sessions or wait for automatic cleanup."
                )

            self._sessions[session_id] = session

        logger.info(f"Created session {session_id}: {config.mode} mode")
        return session_id

    def start_session(self, session_id: str) -> dict[str, Any]:
        """Start a trading session.

        Args:
            session_id: Session ID

        Returns:
            Session status dict

        Raises:
            KeyError: If session not found
        """
        session = self._get_session(session_id)
        session.start()
        return session.get_status()

    def stop_session(self, session_id: str) -> dict[str, Any]:
        """Stop a trading session.

        Args:
            session_id: Session ID

        Returns:
            Session status dict

        Raises:
            KeyError: If session not found
        """
        session = self._get_session(session_id)
        session.stop()
        return session.get_status()

    def get_status(self, session_id: str) -> dict[str, Any]:
        """Get session status and current state.

        Args:
            session_id: Session ID

        Returns:
            Session status dict

        Raises:
            KeyError: If session not found
        """
        session = self._get_session(session_id)
        return session.get_status()

    def list_status(self) -> list[dict[str, Any]]:
        """Get status of all sessions.

        Returns:
            List of session status dicts
        """
        with self._lock:
            return [s.to_status_dict() for s in self._sessions.values()]

    def get_trades(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get trades from a session.

        Args:
            session_id: Session ID
            limit: Maximum trades to return

        Returns:
            List of trade dicts

        Raises:
            KeyError: If session not found
        """
        session = self._get_session(session_id)
        return session.get_trades(limit)

    def get_recent_bars(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        """Get recent bars from a session.

        Args:
            session_id: Session ID
            limit: Maximum bars to return

        Returns:
            List of bar dicts

        Raises:
            KeyError: If session not found
        """
        session = self._get_session(session_id)
        return session.get_recent_bars(limit)

    def get_account_snapshot(self, session_id: str) -> dict[str, Any]:
        """Get account snapshot from a session.

        Args:
            session_id: Session ID

        Returns:
            Account snapshot dict

        Raises:
            KeyError: If session not found
        """
        session = self._get_session(session_id)
        return session.get_account_snapshot()

    def delete_session(self, session_id: str) -> None:
        """Delete a session (must be stopped first).

        Args:
            session_id: Session ID

        Raises:
            KeyError: If session not found
            RuntimeError: If session is still running
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")

            if session.status == "running":
                raise RuntimeError(
                    f"Cannot delete running session {session_id}. Stop it first."
                )

            del self._sessions[session_id]
            logger.info(f"Deleted session {session_id}")

    def _cleanup_old_sessions(self) -> None:
        """Clean up old stopped sessions.

        Issue #5 fix: Removes sessions that have been stopped for more than
        SESSION_TTL_SECONDS to prevent memory leaks.
        """
        with self._lock:
            current_time = datetime.now(timezone.utc)
            sessions_to_delete = []

            for session_id, session in self._sessions.items():
                # Only cleanup stopped sessions
                if session.status != "stopped":
                    continue

                # Check if session has been stopped for too long
                if session.start_time is None:
                    # Session never started, can delete
                    sessions_to_delete.append(session_id)
                    continue

                # Calculate time since session stopped
                # We use current time - start time as approximation
                # (a proper solution would track stop_time)
                time_since_start = (current_time - session.start_time).total_seconds()

                # If session has been around for more than TTL, delete it
                # This is conservative - we delete old sessions even if recently stopped
                if time_since_start > self.SESSION_TTL_SECONDS:
                    sessions_to_delete.append(session_id)

            # Delete old sessions
            for session_id in sessions_to_delete:
                try:
                    # Call cleanup on the session before deleting
                    session = self._sessions[session_id]
                    if hasattr(session, "_cleanup_resources"):
                        session._cleanup_resources()

                    del self._sessions[session_id]
                    logger.info(
                        f"Auto-deleted old session {session_id} "
                        f"(cleanup policy: {self.SESSION_TTL_SECONDS}s TTL)"
                    )
                except Exception as e:
                    logger.error(f"Error deleting old session {session_id}: {e}")

    def _get_session(self, session_id: str) -> LiveSession:
        """Get session by ID.

        Args:
            session_id: Session ID

        Returns:
            LiveSession instance

        Raises:
            KeyError: If session not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")
            return session


# Global singleton instance
_session_manager: LiveSessionManager | None = None
_manager_lock = threading.Lock()


def get_session_manager() -> LiveSessionManager:
    """Get or create the global session manager instance.

    Returns:
        LiveSessionManager singleton
    """
    global _session_manager
    with _manager_lock:
        if _session_manager is None:
            _session_manager = LiveSessionManager()
        return _session_manager


__all__ = [
    "LiveSessionConfig",
    "LiveSession",
    "LiveSessionManager",
    "get_session_manager",
    "TradingMode",
    "SessionStatus",
]
