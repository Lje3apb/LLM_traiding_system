"""API routes for LLM Trading System.

This module contains all JSON API endpoints (non-UI) for:
- Health checks
- Strategy management
- Backtesting
- Live trading sessions

All routes in this module return JSON responses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from llm_trading_system.api.services.validation import (
    sanitize_error_message,
    validate_strategy_name,
)
from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict
from llm_trading_system.engine.live_service import (
    LiveSessionConfig,
    get_session_manager,
)
from llm_trading_system.strategies import storage

# Create router for API endpoints
router = APIRouter()

# Create limiter instance (will be shared with main app)
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# Health Check
# ============================================================================


@router.get("/health")
@limiter.limit("60/minute")  # PUBLIC/LIGHT: Health check monitoring
async def health_check(request: Request) -> dict[str, str]:
    """Health check endpoint.

    Returns a simple status response to indicate the service is healthy.
    Used by load balancers and monitoring systems.

    Args:
        request: FastAPI Request object (required for rate limiting)

    Returns:
        Dictionary with status "ok"

    Example:
        >>> GET /health
        {"status": "ok"}
    """
    return {"status": "ok"}


# ============================================================================
# Strategy Management
# ============================================================================


@router.get("/strategies")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): List strategies
async def list_strategies(request: Request) -> list[str]:
    """List all available trading strategies.

    Returns names of all saved strategy configurations.

    Args:
        request: FastAPI Request object (required for rate limiting)

    Returns:
        List of strategy names

    Raises:
        HTTPException: 500 if strategy listing fails

    Example:
        >>> GET /strategies
        ["momentum_strategy", "mean_reversion", "llm_regime"]
    """
    try:
        return storage.list_configs()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list configs: {sanitize_error_message(e)}"
        )


@router.get("/strategies/{name}")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get strategy
async def get_strategy(request: Request, name: str) -> dict[str, Any]:
    """Get a specific trading strategy configuration.

    Args:
        request: FastAPI Request object (required for rate limiting)
        name: Strategy name

    Returns:
        Strategy configuration dictionary

    Raises:
        HTTPException: 404 if strategy not found, 500 on other errors

    Example:
        >>> GET /strategies/momentum_strategy
        {
            "name": "momentum_strategy",
            "symbol": "BTCUSDT",
            "params": {...}
        }
    """
    try:
        # Validate strategy name to prevent injection
        validate_strategy_name(name)

        config = storage.load_config(name)
        if config is None:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{name}' not found"
            )
        return config
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load strategy: {sanitize_error_message(e)}"
        )


@router.post("/strategies/{name}")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Save strategy
async def save_strategy(
    request: Request,
    name: str,
    config: dict[str, Any]
) -> dict[str, str]:
    """Save a trading strategy configuration.

    Args:
        request: FastAPI Request object (required for rate limiting)
        name: Strategy name
        config: Strategy configuration dictionary

    Returns:
        Success message with strategy name

    Raises:
        HTTPException: 500 if save fails

    Example:
        >>> POST /strategies/my_strategy
        >>> {
        ...     "symbol": "BTCUSDT",
        ...     "params": {...}
        ... }
        {"message": "Strategy 'my_strategy' saved successfully"}
    """
    try:
        # Validate strategy name to prevent injection
        validate_strategy_name(name)

        storage.save_config(name, config)
        return {"message": f"Strategy '{name}' saved successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save strategy: {sanitize_error_message(e)}"
        )


@router.delete("/strategies/{name}")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Delete strategy
async def delete_strategy(request: Request, name: str) -> dict[str, str]:
    """Delete a trading strategy configuration.

    Args:
        request: FastAPI Request object (required for rate limiting)
        name: Strategy name to delete

    Returns:
        Success message with strategy name

    Raises:
        HTTPException: 404 if strategy not found, 500 on other errors

    Example:
        >>> DELETE /strategies/old_strategy
        {"message": "Strategy 'old_strategy' deleted successfully"}
    """
    try:
        # Validate strategy name to prevent injection
        validate_strategy_name(name)

        if not storage.config_exists(name):
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{name}' not found"
            )

        storage.delete_config(name)
        return {"message": f"Strategy '{name}' deleted successfully"}
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete strategy: {sanitize_error_message(e)}"
        )


# ============================================================================
# Backtesting
# ============================================================================


@router.post("/backtest")
@limiter.limit("10/minute;100/day")  # HEAVY OPERATION: Run backtest (CPU intensive)
async def run_backtest(request: Request, config: dict[str, Any]) -> dict[str, Any]:
    """Run a backtest with the given configuration.

    This is a CPU-intensive operation that simulates a trading strategy
    on historical data to evaluate its performance.

    Args:
        request: FastAPI Request object (required for rate limiting)
        config: Backtest configuration dictionary containing:
            - strategy: Strategy type and parameters
            - data: Data source configuration
            - period: Time period for backtest
            - initial_capital: Starting capital

    Returns:
        Backtest results including:
            - summary: Performance metrics
            - trades: List of executed trades
            - equity_curve: Equity over time

    Raises:
        HTTPException: 500 if backtest execution fails

    Example:
        >>> POST /backtest
        >>> {
        ...     "strategy": {"type": "momentum", "params": {...}},
        ...     "data": {"symbol": "BTCUSDT", "timeframe": "1h"},
        ...     "period": {"start": "2023-01-01", "end": "2023-12-31"},
        ...     "initial_capital": 10000
        ... }
        {
            "summary": {"total_return": 0.25, "sharpe_ratio": 1.5, ...},
            "trades": [...],
            "equity_curve": [...]
        }
    """
    try:
        result = run_backtest_from_config_dict(config)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Backtest failed: {sanitize_error_message(e)}"
        )


# ============================================================================
# Live Trading Sessions
# ============================================================================


@router.get("/api/live/sessions")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): List sessions
async def list_live_sessions(request: Request) -> list[dict[str, Any]]:
    """List all live trading sessions.

    Returns:
        List of session status dictionaries

    Raises:
        HTTPException: 500 if listing fails

    Example:
        >>> GET /api/live/sessions
        [
            {"id": "session_123", "status": "running", "strategy": "momentum"},
            {"id": "session_456", "status": "stopped", "strategy": "mean_reversion"}
        ]
    """
    try:
        manager = get_session_manager()
        sessions = manager.list_sessions()
        return sessions
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list sessions: {sanitize_error_message(e)}"
        )


@router.get("/api/live/sessions/{session_id}")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get session status
async def get_live_session_status(
    request: Request,
    session_id: str
) -> dict[str, Any]:
    """Get status of a specific live trading session.

    Args:
        request: FastAPI Request object (required for rate limiting)
        session_id: Session identifier

    Returns:
        Session status dictionary including:
            - id: Session identifier
            - status: Current status (running/stopped/error)
            - strategy: Strategy name
            - created_at: Creation timestamp
            - performance: Performance metrics

    Raises:
        HTTPException: 404 if session not found, 500 on other errors

    Example:
        >>> GET /api/live/sessions/session_123
        {
            "id": "session_123",
            "status": "running",
            "strategy": "momentum",
            "created_at": "2025-01-01T00:00:00Z",
            "performance": {"pnl": 150.50, "trades": 5}
        }
    """
    try:
        manager = get_session_manager()
        status = manager.get_status(session_id)
        return status
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session status: {sanitize_error_message(e)}"
        )


# ============================================================================
# Additional API routes would go here
# ============================================================================
# - POST /api/live/sessions - Create session
# - POST /api/live/sessions/{id}/start - Start session
# - POST /api/live/sessions/{id}/stop - Stop session
# - GET /api/live/sessions/{id}/trades - Get trades
# - GET /api/live/sessions/{id}/bars - Get bars
# - GET /api/live/sessions/{id}/account - Get account
#
# These follow the same pattern as demonstrated above.
