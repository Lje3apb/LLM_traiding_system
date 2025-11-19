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

from llm_trading_system.api.rate_limiter import limiter
from llm_trading_system.api.services.validation import (
    sanitize_error_message,
    validate_data_path,
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
async def list_strategies(request: Request) -> dict[str, list[str]]:
    """List all available trading strategies.

    Returns names of all saved strategy configurations.

    Args:
        request: FastAPI Request object (required for rate limiting)

    Returns:
        Dictionary with "items" key containing list of strategy names

    Raises:
        HTTPException: 500 if strategy listing fails

    Example:
        >>> GET /strategies
        {"items": ["momentum_strategy", "mean_reversion", "llm_regime"]}
    """
    try:
        configs = storage.list_configs()
        return {"items": configs}
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
        config = storage.load_config(name)
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


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
        HTTPException: 400 if validation fails, 500 if save fails

    Example:
        >>> POST /strategies/my_strategy
        >>> {
        ...     "strategy_type": "momentum",
        ...     "mode": "backtest",
        ...     "symbol": "BTCUSDT",
        ...     "params": {...}
        ... }
        {"status": "saved", "name": "my_strategy"}
    """
    # Basic validation
    if "strategy_type" not in config:
        raise HTTPException(
            status_code=400, detail="Config must contain 'strategy_type' field"
        )

    if "mode" not in config:
        raise HTTPException(status_code=400, detail="Config must contain 'mode' field")

    try:
        storage.save_config(name, config)
        return {"status": "saved", "name": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")


@router.delete("/strategies/{name}")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Delete strategy
async def delete_strategy(request: Request, name: str) -> dict[str, str]:
    """Delete a trading strategy configuration.

    Args:
        request: FastAPI Request object (required for rate limiting)
        name: Strategy name to delete

    Returns:
        Status dictionary

    Raises:
        HTTPException: 404 if strategy not found, 500 on other errors

    Example:
        >>> DELETE /strategies/old_strategy
        {"status": "deleted", "name": "old_strategy"}
    """
    try:
        storage.delete_config(name)
        return {"status": "deleted", "name": name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete config: {e}")


# ============================================================================
# Backtesting
# ============================================================================


@router.post("/backtest")
@limiter.limit("10/minute;100/day")  # HEAVY OPERATION: Run backtest (CPU intensive)
async def run_backtest(request_obj: Request, request: dict[str, Any]) -> dict[str, Any]:
    """Run a backtest for a given configuration and data.

    Request body should contain:
        - config: dict (strategy configuration)
        - data_path: str (path to CSV file)
        - use_llm: bool (optional, default: false)
        - llm_model: str (optional, default: llama3.2)
        - llm_url: str (optional, default: http://localhost:11434)
        - initial_equity: float (optional, default: 10000)
        - fee_rate: float (optional, default: 0.001)
        - slippage_bps: float (optional, default: 1.0)

    Returns:
        Backtest summary dictionary with metrics

    Raises:
        HTTPException: If validation fails (400) or backtest error (500)
    """
    # Validate required fields
    body = request
    if "config" not in body:
        raise HTTPException(status_code=400, detail="Missing 'config' field")

    if "data_path" not in body:
        raise HTTPException(status_code=400, detail="Missing 'data_path' field")

    # Extract parameters with defaults
    config = body["config"]
    data_path_str = body["data_path"]
    use_llm = body.get("use_llm", False)
    llm_model = body.get("llm_model")
    llm_url = body.get("llm_url")
    initial_equity = body.get("initial_equity", 10_000.0)
    fee_rate = body.get("fee_rate", 0.001)
    slippage_bps = body.get("slippage_bps", 1.0)

    # Validate data_path to prevent path traversal
    try:
        validated_path = validate_data_path(data_path_str)
        data_path = str(validated_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid data_path: {e}")

    try:
        # Run backtest using service layer
        summary = run_backtest_from_config_dict(
            config=config,
            data_path=data_path,
            use_llm=use_llm,
            llm_model=llm_model,
            llm_url=llm_url,
            initial_equity=initial_equity,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        return summary

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Backtest failed: {sanitize_error_message(e)}"
        )


# ============================================================================
# Live Trading Sessions
# ============================================================================


@router.get("/api/live/sessions")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): List sessions
async def list_live_sessions(request: Request) -> dict[str, list[dict[str, Any]]]:
    """List all live/paper trading sessions.

    Returns:
        Dictionary with "sessions" key containing list of session status dicts

    Example:
        >>> GET /api/live/sessions
        {
            "sessions": [
                {"id": "session_123", "status": "running", "strategy": "momentum"},
                {"id": "session_456", "status": "stopped", "strategy": "mean_reversion"}
            ]
        }
    """
    try:
        manager = get_session_manager()
        sessions = manager.list_status()
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list sessions: {sanitize_error_message(e)}"
        )


@router.get("/api/live/sessions/{session_id}")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get session status
async def get_live_session_status(
    request: Request,
    session_id: str
) -> dict[str, Any]:
    """Get status and current state of a live/paper trading session.

    Args:
        request: FastAPI Request object (required for rate limiting)
        session_id: Session ID

    Returns:
        Session status dictionary with last_state

    Raises:
        HTTPException: If session not found (404)
    """
    try:
        manager = get_session_manager()
        return manager.get_status(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get session status: {sanitize_error_message(e)}"
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
