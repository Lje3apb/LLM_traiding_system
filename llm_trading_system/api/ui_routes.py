"""Web UI routes for the LLM Trading System.

This module contains all HTML-based UI endpoints for the web interface.
Extracted from server.py for better modularity.
"""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from llm_trading_system.api.auth import get_current_user, require_auth
from llm_trading_system.api.rate_limiter import limiter
from llm_trading_system.api.services.validation import (
    sanitize_error_message,
    validate_data_path,
)
from llm_trading_system.data.data_manager import get_data_manager
from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict
from llm_trading_system.strategies import storage

# Setup logger
logger = logging.getLogger(__name__)

# Create API router
router = APIRouter()

# Templates will be set by server.py after router creation
templates = None

# Global storage for backtest results (in-memory cache)
# Key: strategy name, Value: dict with summary, ohlcv_data, trades, data_path
_backtest_cache: dict[str, dict[str, Any]] = {}


def _serialize_trade(trade: Any) -> dict[str, Any]:
    """Serialize a Trade object to a JSON-serializable dictionary.

    Args:
        trade: Trade object from portfolio

    Returns:
        Dictionary with serialized trade data
    """
    return {
        "open_time": trade.open_time.isoformat(),
        "close_time": trade.close_time.isoformat() if trade.close_time else None,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "size": trade.size,
        "pnl": trade.pnl,
    }


def _serialize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Serialize backtest summary for JSON response.

    Converts Trade objects in trades_list to dictionaries.

    Args:
        summary: Backtest summary dictionary

    Returns:
        JSON-serializable summary dictionary
    """
    serialized = summary.copy()

    # Serialize trades_list if present
    if "trades_list" in serialized and serialized["trades_list"]:
        serialized["trades_list"] = [
            _serialize_trade(trade) for trade in serialized["trades_list"]
        ]

    return serialized


# ============================================================================
# CSRF Protection Helpers
# ============================================================================


def _current_csrf_token(request: Request) -> str:
    """Return the CSRF token associated with this request.

    When csrf_middleware issues a fresh token for a GET request it stores the
    value in request.state.csrf_token before the handler executes. This helper
    prefers that stateful value (so templates can embed the same token that will
    be written to the cookie) and falls back to the inbound cookie otherwise.
    """

    token = getattr(request.state, "csrf_token", None)
    if token:
        return token
    return request.cookies.get("csrf_token", "")


def _verify_csrf_token(request: Request, form_token: str | None) -> None:
    """Verify CSRF token using Double Submit Cookie pattern.

    Args:
        request: FastAPI Request object containing cookies
        form_token: CSRF token from form submission

    Raises:
        HTTPException: If CSRF validation fails (403 Forbidden)

    Security Note:
        Uses constant-time comparison to prevent timing attacks
    """
    # Get token from cookie
    cookie_token = request.cookies.get("csrf_token")

    # Validate both tokens exist
    if not cookie_token:
        logger.warning(f"CSRF validation failed: cookie_token missing for {request.url.path}")
        raise HTTPException(
            status_code=403,
            detail=(
                "CSRF token missing from cookie. Please refresh the page and try again. "
                "If this persists, try clearing your browser cookies for this site."
            )
        )

    if not form_token:
        logger.warning(f"CSRF validation failed: form_token missing for {request.url.path}")
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing from form submission. This request has been blocked for security."
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(cookie_token, form_token):
        logger.warning(
            f"CSRF validation failed: token mismatch for {request.url.path}. "
            f"Cookie token: {cookie_token[:8]}..., Form token: {form_token[:8] if form_token else 'None'}..."
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "CSRF token validation failed. This may indicate a Cross-Site Request Forgery attack. "
                "Please refresh the page and try again. If this persists, clear your browser cookies."
            )
        )


# ============================================================================
# Web UI Routes (HTML)
# ============================================================================


@router.get("/", response_class=RedirectResponse)
@limiter.limit("60/minute")  # PUBLIC/LIGHT: Root redirect
async def root(request: Request) -> RedirectResponse:
    """Redirect root to Web UI.

    Returns:
        Redirect to /ui/
    """
    return RedirectResponse(url="/ui/")


# ============================================================================
# Authentication Routes
# ============================================================================


@router.get("/ui/login", response_class=HTMLResponse)
@limiter.limit("60/minute")  # PUBLIC/LIGHT: Login page view
async def login_page(
    request: Request,
    next: str = "/ui/",
    error: str = ""
) -> HTMLResponse:
    """Web UI: Login page.

    Args:
        request: FastAPI request object
        next: URL to redirect to after successful login
        error: Error message to display (if any)

    Returns:
        HTML response with login form
    """
    import os

    # If already logged in, redirect to next page
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse(url=next, status_code=303)

    # Generate a new CSRF token for this page load
    csrf_token = secrets.token_hex(32)

    # Determine if we're in production
    is_production = os.getenv("ENV", "").lower() == "production"

    # Create response with CSRF token in cookie
    response = templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next,
            "error": error,
            "csrf_token": csrf_token,
        },
    )

    # Set CSRF cookie (must match the token in the form)
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # Allow JavaScript to read for form submission
        samesite="strict",  # Prevent CSRF from external sites
        secure=is_production,  # HTTPS only in production
        max_age=3600,  # 1 hour expiration
    )

    return response


@router.post("/ui/login")
@limiter.limit("20/minute;100/hour")  # AUTHENTICATION: Login attempts (brute force protection)
async def login(
    request: Request,
    csrf_token: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/ui/"),
) -> RedirectResponse:
    """Web UI: Process login form.

    Args:
        request: FastAPI request object
        csrf_token: CSRF token from form
        username: Username from form
        password: Password from form
        next: URL to redirect to after successful login

    Returns:
        Redirect to next page on success, or back to login on failure
    """
    from llm_trading_system.api.auth import authenticate_user

    # CSRF validation
    _verify_csrf_token(request, csrf_token)

    # Authenticate user
    user = authenticate_user(username, password)

    if not user:
        # Authentication failed - redirect back to login with error
        return RedirectResponse(
            url=f"/ui/login?next={next}&error=Invalid+username+or+password",
            status_code=303
        )

    # Authentication successful - create session
    request.session["user_id"] = user.user_id
    request.session["username"] = user.username

    # Redirect to next page
    return RedirectResponse(url=next, status_code=303)


@router.get("/ui/logout")
@limiter.limit("60/minute")  # PUBLIC/LIGHT: Logout
async def logout(request: Request) -> RedirectResponse:
    """Web UI: Logout endpoint.

    Clears session and redirects to login page.

    Args:
        request: FastAPI request object

    Returns:
        Redirect to login page
    """
    # Clear session
    request.session.clear()

    # Redirect to login page
    return RedirectResponse(url="/ui/login", status_code=303)


@router.get("/ui/", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Strategy list page
async def ui_index(request: Request, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: List all strategy configurations.

    Args:
        request: FastAPI request object

    Returns:
        HTML response with strategy list
    """
    try:
        from llm_trading_system.config.service import load_config as load_app_config

        # Load AppConfig
        app_cfg = load_app_config()

        strategy_names = storage.list_configs()

        # Load configs to get strategy types
        strategies = []
        for name in strategy_names:
            try:
                config = storage.load_config(name)
                strategy_type = config.get('strategy_type', 'indicator')
                mode = config.get('mode', 'quant_only')

                # Determine display type
                if mode == 'llm_only':
                    display_type = 'LLM Only'
                elif mode == 'hybrid':
                    display_type = 'Hybrid (LLM + Indicator)'
                else:
                    display_type = strategy_type.capitalize()

                strategies.append({
                    'name': name,
                    'type': display_type,
                    'mode': mode,
                    'symbol': config.get('symbol', 'BTCUSDT'),
                })
            except Exception as e:
                # If config fails to load, log as ERROR (corrupted config is serious)
                logger.error(f"Invalid/corrupted strategy config '{name}': {e}. Skipping.")
                strategies.append({
                    'name': name,
                    'type': 'Error',  # More obvious than 'Unknown'
                    'mode': 'error',
                    'symbol': 'N/A',
                })

        # Get live trading enabled from AppConfig
        live_enabled = app_cfg.exchange.live_trading_enabled

        # Get CSRF token from middleware (falls back to cookie)
        csrf_token = _current_csrf_token(request)

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "strategies": strategies,
                "live_enabled": live_enabled,
                "csrf_token": csrf_token,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list configs: {e}")


@router.get("/ui/live", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Live trading page
async def ui_live_trading(request: Request, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: Live trading page for paper and real trading.

    Args:
        request: FastAPI request object
        user: Authenticated user (injected by require_auth dependency)

    Returns:
        HTML response with live trading UI

    Note:
        Generates a WebSocket authentication token for the user to enable
        real-time updates via WebSocket connection. Token expires after 1 hour.
    """
    from llm_trading_system.api.auth import generate_ws_token

    try:
        from llm_trading_system.config.service import load_config as load_app_config

        # Load AppConfig
        app_cfg = load_app_config()

        # Get live trading enabled from AppConfig
        live_enabled = app_cfg.exchange.live_trading_enabled

        # Get strategies
        strategies = storage.list_configs()

        # Define symbols and timeframes
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
        timeframes = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

        # Generate WebSocket authentication token for this user
        # Token is time-limited (1 hour) and signed to prevent tampering
        ws_token = generate_ws_token(user.user_id)

        return templates.TemplateResponse(
            "live_trading.html",
            {
                "request": request,
                "strategies": strategies,
                "symbols": symbols,
                "timeframes": timeframes,
                "live_enabled": live_enabled,
                # Defaults from AppConfig
                "default_initial_deposit": app_cfg.ui.default_initial_deposit,
                "default_symbol": app_cfg.exchange.default_symbol,
                "default_timeframe": app_cfg.exchange.default_timeframe,
                # WebSocket authentication token
                "ws_token": ws_token,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load live trading page: {e}")


@router.get("/ui/strategies/new", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): New strategy form
async def ui_new_strategy(request: Request, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: Show form to create a new strategy.

    Args:
        request: FastAPI request object

    Returns:
        HTML response with empty strategy form
    """
    # Get CSRF token from middleware (falls back to cookie)
    csrf_token = _current_csrf_token(request)

    return templates.TemplateResponse(
        "strategy_form.html",
        {
            "request": request,
            "name": None,
            "config": {},
            "csrf_token": csrf_token,
        },
    )


@router.get("/ui/strategies/{name}/edit", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Edit strategy form
async def ui_edit_strategy(request: Request, name: str, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: Show form to edit an existing strategy.

    Args:
        request: FastAPI request object
        name: Strategy config name

    Returns:
        HTML response with populated strategy form

    Raises:
        HTTPException: If config not found (404) or error loading (500)
    """
    try:
        config = storage.load_config(name)

        # Get CSRF token from middleware (falls back to cookie)
        csrf_token = _current_csrf_token(request)

        return templates.TemplateResponse(
            "strategy_form.html",
            {
                "request": request,
                "name": name,
                "config": config,
                "csrf_token": csrf_token,
            },
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


@router.post("/ui/strategies/{name}/save")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Save strategy
async def ui_save_strategy(
    request: Request,
    name: str,
    user=Depends(require_auth),  # Authentication required
    csrf_token: str = Form(...),  # CSRF protection
    strategy_name: str = Form(..., alias="name"),
    strategy_type: str = Form(...),
    mode: str = Form(...),
    symbol: str = Form(...),
    base_size: float = Form(...),
    allow_long: bool = Form(False),
    allow_short: bool = Form(False),
    # Risk / Money Management
    base_position_pct: float = Form(10.0),
    pyramiding: int = Form(1),
    use_martingale: bool = Form(False),
    martingale_mult: float = Form(1.5),
    tp_long_pct: float = Form(2.0),
    sl_long_pct: float = Form(2.0),
    tp_short_pct: float = Form(2.0),
    sl_short_pct: float = Form(2.0),
    use_tp_sl: bool = Form(False),
    # Time filter parameters
    time_filter_enabled: bool = Form(False),
    time_filter_start_hour: int = Form(0),
    time_filter_end_hour: int = Form(23),
    # Indicator parameters
    ema_fast_len: int = Form(...),
    ema_slow_len: int = Form(...),
    rsi_len: int = Form(...),
    rsi_ovb: int = Form(...),
    rsi_ovs: int = Form(...),
    bb_len: int = Form(...),
    bb_mult: float = Form(...),
    atr_len: int = Form(...),
    adx_len: int = Form(...),
    vol_ma_len: int = Form(21),
    vol_mult: float = Form(0.5),
    # LLM parameters
    k_max: float = Form(2.0),
    llm_horizon_hours: int = Form(24),
    llm_min_prob_edge: float = Form(0.55),
    llm_min_trend_strength: float = Form(0.6),
    llm_refresh_interval_bars: int = Form(60),
    # Trading rules
    rules_long_entry: str = Form("[]"),
    rules_short_entry: str = Form("[]"),
    rules_long_exit: str = Form("[]"),
    rules_short_exit: str = Form("[]"),
) -> RedirectResponse:
    """Web UI: Save a strategy configuration.

    Args:
        name: URL path parameter (for existing configs)
        strategy_name: Strategy name from form
        (other form fields...)

    Returns:
        Redirect to edit page for the saved strategy

    Raises:
        HTTPException: If validation fails (400) or save error (500)
    """
    # CSRF validation (must be first to prevent processing invalid requests)
    _verify_csrf_token(request, csrf_token)

    # Validate strategy parameters before processing
    # RSI thresholds
    if rsi_ovs >= rsi_ovb:
        raise HTTPException(
            status_code=400,
            detail=f"RSI Oversold must be less than RSI Overbought. Got ovs={rsi_ovs}, ovb={rsi_ovb}"
        )

    # Time filter parameters
    if time_filter_enabled:
        if not (0 <= time_filter_start_hour <= 23):
            raise HTTPException(
                status_code=400,
                detail=f"time_filter_start_hour must be in [0, 23], got {time_filter_start_hour}"
            )
        if not (0 <= time_filter_end_hour <= 23):
            raise HTTPException(
                status_code=400,
                detail=f"time_filter_end_hour must be in [0, 23], got {time_filter_end_hour}"
            )

    # TP/SL validation
    if use_tp_sl:
        if tp_long_pct <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"TP Long % must be greater than 0, got {tp_long_pct}"
            )
        if sl_long_pct <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"SL Long % must be greater than 0, got {sl_long_pct}"
            )
        if tp_short_pct <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"TP Short % must be greater than 0, got {tp_short_pct}"
            )
        if sl_short_pct <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"SL Short % must be greater than 0, got {sl_short_pct}"
            )

    # Pyramiding validation
    if pyramiding < 1:
        raise HTTPException(
            status_code=400,
            detail=f"Pyramiding must be at least 1, got {pyramiding}"
        )

    # Base position validation
    if base_position_pct <= 0 or base_position_pct > 100:
        raise HTTPException(
            status_code=400,
            detail=f"Base Position % must be between 0 and 100, got {base_position_pct}"
        )

    # Use form name if different from URL name (for new strategies)
    actual_name = strategy_name if name == "new" else name

    # Parse rules from JSON strings
    try:
        long_entry = json.loads(rules_long_entry)
        short_entry = json.loads(rules_short_entry)
        long_exit = json.loads(rules_long_exit)
        short_exit = json.loads(rules_short_exit)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid rules JSON: {e}")

    # Build config dictionary
    config = {
        "strategy_type": strategy_type,
        "mode": mode,
        "symbol": symbol,
        "base_size": base_size,
        "allow_long": allow_long,
        "allow_short": allow_short,
        # Risk / Money Management
        "base_position_pct": base_position_pct,
        "pyramiding": pyramiding,
        "use_martingale": use_martingale,
        "martingale_mult": martingale_mult,
        "tp_long_pct": tp_long_pct,
        "sl_long_pct": sl_long_pct,
        "tp_short_pct": tp_short_pct,
        "sl_short_pct": sl_short_pct,
        "use_tp_sl": use_tp_sl,
        # Time filter
        "time_filter_enabled": time_filter_enabled,
        "time_filter_start_hour": time_filter_start_hour,
        "time_filter_end_hour": time_filter_end_hour,
        # Indicator parameters
        "ema_fast_len": ema_fast_len,
        "ema_slow_len": ema_slow_len,
        "rsi_len": rsi_len,
        "rsi_ovb": rsi_ovb,
        "rsi_ovs": rsi_ovs,
        "bb_len": bb_len,
        "bb_mult": bb_mult,
        "atr_len": atr_len,
        "adx_len": adx_len,
        "vol_ma_len": vol_ma_len,
        "vol_mult": vol_mult,
        # LLM parameters
        "k_max": k_max,
        "llm_horizon_hours": llm_horizon_hours,
        "llm_min_prob_edge": llm_min_prob_edge,
        "llm_min_trend_strength": llm_min_trend_strength,
        "llm_refresh_interval_bars": llm_refresh_interval_bars,
        # Trading rules
        "rules": {
            "long_entry": long_entry,
            "short_entry": short_entry,
            "long_exit": long_exit,
            "short_exit": short_exit,
        },
    }

    # Save config
    try:
        storage.save_config(actual_name, config)
        return RedirectResponse(
            url=f"/ui/strategies/{actual_name}/edit", status_code=303
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")


@router.post("/ui/strategies/{name}/delete")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Delete strategy
async def ui_delete_strategy(
    request: Request,
    name: str,
    user=Depends(require_auth),  # Authentication required
    csrf_token: str = Form(...),  # CSRF protection
) -> RedirectResponse:
    """Web UI: Delete a strategy configuration.

    Args:
        request: FastAPI request object
        name: Strategy config name
        csrf_token: CSRF token from form

    Returns:
        Redirect to index page

    Raises:
        HTTPException: If config not found (404) or error deleting (500)
    """
    # CSRF validation (must be first to prevent processing invalid requests)
    _verify_csrf_token(request, csrf_token)

    try:

        storage.delete_config(name)
        return RedirectResponse(url="/ui/", status_code=303)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete config: {e}")


@router.get("/ui/strategies/{name}/backtest", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Backtest form
async def ui_backtest_form(request: Request, name: str, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: Show backtest form for a strategy.

    Args:
        request: FastAPI request object
        name: Strategy config name

    Returns:
        HTML response with backtest form

    Raises:
        HTTPException: If config not found (404)
    """
    try:
        from llm_trading_system.config.service import load_config as load_app_config

        config = storage.load_config(name)

        # Load AppConfig for default values
        app_cfg = load_app_config()

        # Get CSRF token from middleware (falls back to cookie)
        csrf_token = _current_csrf_token(request)

        return templates.TemplateResponse(
            "backtest_form.html",
            {
                "request": request,
                "name": name,
                "config": config,
                # Default values from AppConfig
                "default_backtest_equity": app_cfg.ui.default_backtest_equity,
                "default_commission": app_cfg.ui.default_commission,
                "default_slippage": app_cfg.ui.default_slippage,
                "default_symbol": app_cfg.exchange.default_symbol,
                "default_timeframe": app_cfg.exchange.default_timeframe,
                "default_llm_model": app_cfg.llm.default_model,
                "default_llm_url": app_cfg.llm.ollama_base_url,
                "csrf_token": csrf_token,
            },
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


@router.post("/ui/strategies/{name}/backtest", response_class=HTMLResponse)
@limiter.limit("10/minute;100/day")  # HEAVY OPERATION: Run backtest (CPU intensive)
async def ui_run_backtest(
    request: Request,
    name: str,
    user=Depends(require_auth),  # Authentication required
    csrf_token: str = Form(...),  # CSRF protection
    data_path: str = Form(...),
    use_llm: bool = Form(False),
    llm_model: str = Form("llama3.2"),
    llm_url: str = Form("http://localhost:11434"),
    initial_equity: float = Form(10000.0),
    fee_rate: float = Form(0.001),
    slippage_bps: float = Form(1.0),
) -> HTMLResponse:
    """Web UI: Run a backtest and show results.

    Args:
        request: FastAPI request object
        name: Strategy config name
        data_path: Path to CSV data file
        use_llm: Whether to use LLM
        llm_model: LLM model name
        llm_url: Ollama server URL
        initial_equity: Initial equity
        fee_rate: Trading fee rate
        slippage_bps: Slippage in basis points

    Returns:
        HTML response with backtest results

    Raises:
        HTTPException: If config not found, data not found, or backtest fails
    """
    # CSRF validation (must be first to prevent processing invalid requests)
    _verify_csrf_token(request, csrf_token)

    try:

        # Load config
        config = storage.load_config(name)

        # Validate data_path to prevent path traversal attacks
        try:
            validated_path = validate_data_path(data_path)
            data_path = str(validated_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid data_path: {e}")

        # Validate numeric parameters
        if initial_equity <= 0:
            raise HTTPException(status_code=400, detail="Initial equity must be positive")
        if fee_rate < 0 or fee_rate > 1:
            raise HTTPException(status_code=400, detail="Fee rate must be between 0 and 1")
        if slippage_bps < 0:
            raise HTTPException(status_code=400, detail="Slippage must be non-negative")

        # Run backtest
        summary = run_backtest_from_config_dict(
            config=config,
            data_path=data_path,
            use_llm=use_llm,
            llm_model=llm_model if use_llm else None,
            llm_url=llm_url if use_llm else None,
            initial_equity=initial_equity,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        # Cache backtest results for chart endpoint
        _backtest_cache[name] = {
            "summary": summary,
            "data_path": data_path,
            "config": config,
        }

        # Get live trading enabled from AppConfig
        from llm_trading_system.config.service import load_config as load_app_config
        app_cfg = load_app_config()
        live_enabled = app_cfg.exchange.live_trading_enabled

        # Render results
        return templates.TemplateResponse(
            "backtest_result.html",
            {
                "request": request,
                "name": name,
                "summary": summary,
                "live_enabled": live_enabled,
            },
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Backtest failed: {sanitize_error_message(e)}"
        )


@router.get("/ui/backtest/{name}/chart-data")
@limiter.limit("60/minute")  # CHART DATA: Backtest chart data
async def ui_get_backtest_chart_data(request: Request, name: str) -> JSONResponse:
    """Web UI: Get chart data for backtest visualization.

    Args:
        name: Strategy config name

    Returns:
        JSON response with OHLCV data and trades for Lightweight Charts

    Raises:
        HTTPException: If backtest data not found
    """
    try:
        # Check if we have cached backtest data
        if name not in _backtest_cache:
            raise HTTPException(
                status_code=404,
                detail=f"No backtest data found for '{name}'. Please run backtest first."
            )

        cached_data = _backtest_cache[name]
        data_path = cached_data["data_path"]
        summary = cached_data["summary"]

        # Read OHLCV data from CSV
        import pandas as pd
        from datetime import datetime, timezone

        df = pd.read_csv(data_path)

        # Convert to Lightweight Charts format
        ohlcv_data = []
        for _, row in df.iterrows():
            # Parse timestamp (handle both Unix seconds and ISO format)
            ts_str = str(row["timestamp"]).strip()
            if ts_str.isdigit():
                # Unix seconds
                unix_time = int(ts_str)
            else:
                # ISO format - parse and convert to Unix timestamp
                if ts_str.endswith("Z") or ts_str.endswith("z"):
                    ts_str = ts_str[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                unix_time = int(dt.timestamp())

            ohlcv_data.append({
                "time": unix_time,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })

        # Extract trades from summary (cached trades list)
        trades_data = []

        # Get cached trades from summary
        cached_trades = summary.get("trades_list", [])

        # Detect bar interval from OHLCV data
        interval_seconds = 3600  # default 1 hour
        if len(ohlcv_data) >= 2:
            interval_seconds = ohlcv_data[1]["time"] - ohlcv_data[0]["time"]

        # Format trades for chart
        for trade in cached_trades:
            # Parse timestamps
            entry_ts = trade.open_time
            exit_ts = trade.close_time

            # Calculate entry/exit Unix timestamps
            entry_unix = int(entry_ts.timestamp()) if entry_ts else 0
            exit_unix = int(exit_ts.timestamp()) if exit_ts else 0

            # Calculate bars held using detected interval
            bars_held = 0
            if entry_unix and exit_unix and interval_seconds > 0:
                time_diff = exit_unix - entry_unix
                bars_held = max(1, time_diff // interval_seconds)

            trades_data.append({
                "side": trade.side,
                "entry_time": entry_unix,
                "entry_price": float(trade.entry_price),
                "exit_time": exit_unix,
                "exit_price": float(trade.exit_price) if trade.exit_price else 0,
                "size": float(trade.size),
                "pnl": float(trade.pnl) if trade.pnl is not None else 0,
                "bars_held": bars_held,
            })

        return JSONResponse({
            "ohlcv": ohlcv_data,
            "trades": trades_data,
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load chart data: {sanitize_error_message(e)}"
        )


@router.post("/ui/strategies/{name}/download_data")
@limiter.limit("3/minute;20/day")  # VERY HEAVY OPERATION: Download market data from exchange
async def ui_download_data(
    request: Request,
    name: str,
    user=Depends(require_auth),  # Authentication required
    csrf_token: str = Form(...),  # CSRF protection
    symbol: str = Form(...),
    interval: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
) -> StreamingResponse:
    """Web UI: Download OHLCV data from Binance archive with real-time progress.

    Args:
        name: Strategy config name (for context)
        symbol: Trading pair (e.g. BTCUSDT)
        interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Streaming response with progress updates (newline-delimited JSON)
    """
    # CSRF validation (must be first to prevent processing invalid requests)
    _verify_csrf_token(request, csrf_token)

    from datetime import datetime, timedelta
    import pandas as pd

    async def generate_progress() -> AsyncIterator[str]:
        """Generate progress updates as JSON lines.

        Yields:
            str: Newline-delimited JSON progress update
        """
        try:
            # Validate dates
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError as e:
                yield json.dumps(
                    {"type": "error", "message": f"Invalid date format. Use YYYY-MM-DD: {e}"}
                ) + "\n"
                return

            if end_dt < start_dt:
                yield json.dumps(
                    {"type": "error", "message": "End date must be greater than or equal to start date"}
                ) + "\n"
                return

            # Check if date range is too large
            days_diff = (end_dt - start_dt).days
            if days_diff > 365:
                warning = f"Large date range ({days_diff} days) may take a while"
                yield json.dumps({"type": "warning", "message": warning}) + "\n"

            # Check if data is cached
            data_manager = get_data_manager()
            filepath = data_manager._get_filepath(symbol, interval, start_date, end_date)

            if data_manager.check_data_coverage(filepath, start_date, end_date):
                # Data is cached
                yield json.dumps(
                    {"type": "info", "message": "Using cached data..."}
                ) + "\n"
                df = data_manager.load_from_csv(filepath)
                yield json.dumps(
                    {
                        "type": "complete",
                        "file_path": str(filepath),
                        "rows": len(df),
                        "message": f"Loaded {len(df)} rows from cache",
                    }
                ) + "\n"
                return

            # Download fresh data
            from llm_trading_system.data.binance_loader import BinanceArchiveLoader

            loader = BinanceArchiveLoader(symbol, interval)

            # Send initial message
            yield json.dumps(
                {"type": "info", "message": f"Starting download of {days_diff + 1} days..."}
            ) + "\n"

            # Download with progress tracking
            dates_list = [start_dt + timedelta(days=i) for i in range(days_diff + 1)]

            dfs = []
            for idx, date in enumerate(dates_list, 1):
                date_str = date.strftime("%Y-%m-%d")
                filename = f"{symbol}-{interval}-{date_str}.zip"

                # Send progress update
                yield json.dumps(
                    {
                        "type": "progress",
                        "current": idx,
                        "total": len(dates_list),
                        "date": date_str,
                        "filename": filename,
                        "percent": int((idx / len(dates_list)) * 100),
                    }
                ) + "\n"

                # Download day
                try:
                    df = loader._download_day(date)
                    if df is not None:
                        dfs.append(df)
                except Exception as e:
                    yield json.dumps(
                        {"type": "warning", "message": f"Failed {date_str}: {str(e)[:50]}"}
                    ) + "\n"

            if not dfs:
                yield json.dumps(
                    {"type": "error", "message": f"No data downloaded for {symbol} {interval}"}
                ) + "\n"
                return

            # Processing data
            yield json.dumps({"type": "info", "message": "Processing data..."}) + "\n"

            # Merge dataframes
            df = pd.concat(dfs, ignore_index=True)
            df = df.sort_values("open_time").reset_index(drop=True)
            df = df.drop_duplicates(subset=["open_time"], keep="first")

            # Save to CSV
            data_manager.save_to_csv(df, filepath)

            # Send completion
            yield json.dumps(
                {
                    "type": "complete",
                    "file_path": str(filepath),
                    "rows": len(df),
                    "message": f"Downloaded {days_diff + 1} days, {len(df)} rows",
                }
            ) + "\n"

        except Exception as e:
            yield json.dumps(
                {"type": "error", "message": f"Download failed: {type(e).__name__}: {str(e)[:100]}"}
            ) + "\n"

    return StreamingResponse(generate_progress(), media_type="application/x-ndjson")


@router.get("/ui/settings", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Settings page
async def settings_page(request: Request, saved: bool = False, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: System settings page for AppConfig management.

    Args:
        request: FastAPI request object
        saved: Whether settings were just saved (query parameter)

    Returns:
        HTML response with settings form
    """
    try:
        from llm_trading_system.config.service import load_config
        from llm_trading_system.infra.llm_infra import list_ollama_models

        # Load current config
        cfg = load_config()

        # Fetch available Ollama models
        ollama_models = list_ollama_models(cfg.llm.ollama_base_url)

        # Check if Ollama connection failed (empty list could mean connection error)
        ollama_connection_error = len(ollama_models) == 0

        # Get CSRF token from middleware (falls back to cookie)
        csrf_token = _current_csrf_token(request)

        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "config": cfg,
                "ollama_models": ollama_models,
                "ollama_connection_error": ollama_connection_error,
                "saved": saved,
                "csrf_token": csrf_token,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {e}")


@router.post("/ui/settings")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Save settings
async def save_settings(
    request: Request,
    user=Depends(require_auth),  # Authentication required
    csrf_token: str = Form(...),  # CSRF protection
    # LLM settings
    llm_provider: str = Form(...),
    default_model: str = Form(...),
    ollama_base_url: str = Form(...),
    openai_api_base: str = Form(""),
    openai_api_key: str = Form(""),
    temperature: float = Form(...),
    timeout_seconds: int = Form(...),
    # API settings
    newsapi_key: str = Form(""),
    newsapi_base_url: str = Form(...),
    cryptopanic_api_key: str = Form(""),
    cryptopanic_base_url: str = Form(...),
    coinmetrics_base_url: str = Form(...),
    blockchain_com_base_url: str = Form(...),
    binance_base_url: str = Form(...),
    binance_fapi_url: str = Form(...),
    # Market settings
    base_asset: str = Form(...),
    horizon_hours: int = Form(...),
    use_news: bool = Form(False),
    use_onchain: bool = Form(False),
    use_funding: bool = Form(False),
    # Risk settings
    base_long_size: float = Form(...),
    base_short_size: float = Form(...),
    k_max: float = Form(...),
    edge_gain: float = Form(...),
    edge_gamma: float = Form(...),
    base_k: float = Form(...),
    # Exchange settings
    exchange_type: str = Form(...),
    exchange_name: str = Form(...),
    exchange_api_key: str = Form(""),
    exchange_api_secret: str = Form(""),
    use_testnet: bool = Form(False),
    live_trading_enabled: bool = Form(False),
    default_symbol: str = Form(...),
    default_timeframe: str = Form(...),
    # UI defaults
    default_initial_deposit: float = Form(...),
    default_backtest_equity: float = Form(...),
    default_commission: float = Form(...),
    default_slippage: float = Form(...),
) -> RedirectResponse:
    """Web UI: Save system settings to AppConfig.

    Args:
        (all form fields...)

    Returns:
        Redirect to settings page with saved=1 query parameter
    """
    # CSRF validation (must be first to prevent processing invalid requests)
    _verify_csrf_token(request, csrf_token)

    try:
        import os
        from llm_trading_system.config.service import load_config, save_config

        # SECURITY: Check for HTTPS when submitting API keys in production
        # Allow HTTP only in development (ENV != production)
        is_production = os.getenv("ENV", "").lower() == "production"
        has_sensitive_data = bool(openai_api_key or exchange_api_key or exchange_api_secret or
                                  newsapi_key or cryptopanic_api_key)

        if is_production and has_sensitive_data and request.url.scheme != "https":
            raise HTTPException(
                status_code=400,
                detail="API keys can only be submitted over HTTPS in production. "
                       "Configure reverse proxy (nginx/traefik) with SSL certificate."
            )

        # Load current config
        cfg = load_config()

        # Validate numeric parameters
        if not (0.0 <= temperature <= 2.0):
            raise HTTPException(status_code=400, detail="Temperature must be between 0 and 2")
        if timeout_seconds <= 0:
            raise HTTPException(status_code=400, detail="Timeout must be positive")
        if horizon_hours <= 0:
            raise HTTPException(status_code=400, detail="Horizon hours must be positive")
        if not (0.0 <= base_long_size <= 1.0):
            raise HTTPException(status_code=400, detail="Base long size must be between 0 and 1")
        if not (0.0 <= base_short_size <= 1.0):
            raise HTTPException(status_code=400, detail="Base short size must be between 0 and 1")
        if k_max < 0:
            raise HTTPException(status_code=400, detail="K max must be non-negative")
        if edge_gain < 0:
            raise HTTPException(status_code=400, detail="Edge gain must be non-negative")
        if not (0.0 <= edge_gamma <= 1.0):
            raise HTTPException(status_code=400, detail="Edge gamma must be between 0 and 1")
        if base_k < 0:
            raise HTTPException(status_code=400, detail="Base k must be non-negative")
        if default_initial_deposit < 0:
            raise HTTPException(status_code=400, detail="Default initial deposit must be non-negative")
        if default_backtest_equity < 0:
            raise HTTPException(status_code=400, detail="Default backtest equity must be non-negative")
        if not (0.0 <= default_commission <= 100.0):
            raise HTTPException(status_code=400, detail="Default commission must be between 0 and 100")
        if default_slippage < 0:
            raise HTTPException(status_code=400, detail="Default slippage must be non-negative")

        # Update LLM settings
        cfg.llm.llm_provider = llm_provider
        cfg.llm.default_model = default_model
        cfg.llm.ollama_base_url = ollama_base_url
        cfg.llm.temperature = temperature
        cfg.llm.timeout_seconds = timeout_seconds

        # Update OpenAI settings (preserve secrets if empty)
        if openai_api_base:
            cfg.llm.openai_api_base = openai_api_base
        if openai_api_key:
            cfg.llm.openai_api_key = openai_api_key

        # Update API settings (preserve secrets if empty)
        if newsapi_key:
            cfg.api.newsapi_key = newsapi_key
        cfg.api.newsapi_base_url = newsapi_base_url
        if cryptopanic_api_key:
            cfg.api.cryptopanic_api_key = cryptopanic_api_key
        cfg.api.cryptopanic_base_url = cryptopanic_base_url
        cfg.api.coinmetrics_base_url = coinmetrics_base_url
        cfg.api.blockchain_com_base_url = blockchain_com_base_url
        cfg.api.binance_base_url = binance_base_url
        cfg.api.binance_fapi_url = binance_fapi_url

        # Update Market settings
        cfg.market.base_asset = base_asset
        cfg.market.horizon_hours = horizon_hours
        cfg.market.use_news = use_news
        cfg.market.use_onchain = use_onchain
        cfg.market.use_funding = use_funding

        # Update Risk settings
        cfg.risk.base_long_size = base_long_size
        cfg.risk.base_short_size = base_short_size
        cfg.risk.k_max = k_max
        cfg.risk.edge_gain = edge_gain
        cfg.risk.edge_gamma = edge_gamma
        cfg.risk.base_k = base_k

        # Update Exchange settings (preserve secrets if empty)
        cfg.exchange.exchange_type = exchange_type
        cfg.exchange.exchange_name = exchange_name
        if exchange_api_key:
            cfg.exchange.api_key = exchange_api_key
        if exchange_api_secret:
            cfg.exchange.api_secret = exchange_api_secret
        cfg.exchange.use_testnet = use_testnet
        cfg.exchange.live_trading_enabled = live_trading_enabled
        cfg.exchange.default_symbol = default_symbol
        cfg.exchange.default_timeframe = default_timeframe

        # Update UI defaults
        cfg.ui.default_initial_deposit = default_initial_deposit
        cfg.ui.default_backtest_equity = default_backtest_equity
        cfg.ui.default_commission = default_commission
        cfg.ui.default_slippage = default_slippage

        # Save config
        save_config(cfg)

        # Redirect with success message
        return RedirectResponse(url="/ui/settings?saved=1", status_code=303)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


@router.get("/ui/data/files")
@limiter.limit("60/minute")  # FILE LISTING: List data files
async def ui_list_data_files(request: Request) -> JSONResponse:
    """Web UI: List available CSV data files.

    Returns:
        JSON response with list of CSV files in data/ directory
    """
    try:
        data_dir = Path("data")
        if not data_dir.exists():
            return JSONResponse({"files": []})

        # Get all CSV files
        csv_files = sorted(data_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)

        # Build file list with metadata
        files = []
        for filepath in csv_files:
            try:
                # Get file size
                size_bytes = filepath.stat().st_size
                size_mb = size_bytes / (1024 * 1024)

                # Try to count rows (quick check - just count lines)
                with open(filepath, "r", encoding="utf-8") as f:
                    row_count = sum(1 for _ in f) - 1  # -1 for header

                files.append(
                    {
                        "path": str(filepath),
                        "name": filepath.name,
                        "size_mb": round(size_mb, 2),
                        "rows": row_count,
                    }
                )
            except Exception as e:
                # If we can't read the file, still include it but without metadata
                files.append({"path": str(filepath), "name": filepath.name, "size_mb": 0, "rows": 0})

        return JSONResponse({"files": files})

    except Exception as e:
        return JSONResponse({"files": [], "error": str(e)})


# ============================================================================
# Interactive Backtest Parameter Editing
# ============================================================================


@router.get("/ui/strategies/{name}/params")
@limiter.limit("60/minute")  # PARAMETER FETCH: Get strategy parameters
async def ui_get_strategy_params(request: Request, name: str, user=Depends(require_auth)) -> JSONResponse:
    """Web UI: Get strategy parameters for editing.

    Args:
        request: FastAPI request object
        name: Strategy config name

    Returns:
        JSON response with strategy parameters

    Raises:
        HTTPException: If config not found (404) or error loading (500)
    """
    try:
        config = storage.load_config(name)

        # Return all parameters for editing
        return JSONResponse({
            "success": True,
            "params": {
                # Strategy Type & Mode
                "strategy_type": config.get("strategy_type", "indicator"),
                "mode": config.get("mode", "quant_only"),
                "symbol": config.get("symbol", "BTCUSDT"),

                # Trading Rules (JSON)
                "rules": config.get("rules", {}),

                # LLM Parameters
                "k_max": config.get("k_max", 2.0),
                "llm_horizon_hours": config.get("llm_horizon_hours", 24),
                "llm_min_prob_edge": config.get("llm_min_prob_edge", 0.55),
                "llm_min_trend_strength": config.get("llm_min_trend_strength", 0.6),
                "llm_refresh_interval_bars": config.get("llm_refresh_interval_bars", 60),

                # Indicator Parameters
                "rsi_len": config.get("rsi_len", 14),
                "rsi_ovb": config.get("rsi_ovb", 70),
                "rsi_ovs": config.get("rsi_ovs", 30),
                "bb_len": config.get("bb_len", 20),
                "bb_mult": config.get("bb_mult", 2.0),
                "ema_fast_len": config.get("ema_fast_len", 12),
                "ema_slow_len": config.get("ema_slow_len", 26),
                "atr_len": config.get("atr_len", 14),
                "adx_len": config.get("adx_len", 14),
                "vol_ma_len": config.get("vol_ma_len", 21),
                "vol_mult": config.get("vol_mult", 0.5),

                # Position & Risk Management
                "base_size": config.get("base_size", 0.1),
                "allow_long": config.get("allow_long", True),
                "allow_short": config.get("allow_short", True),
                "base_position_pct": config.get("base_position_pct", 10.0),
                "pyramiding": config.get("pyramiding", 1),
                "use_martingale": config.get("use_martingale", False),
                "martingale_mult": config.get("martingale_mult", 1.5),

                # TP/SL
                "use_tp_sl": config.get("use_tp_sl", False),
                "tp_long_pct": config.get("tp_long_pct", 2.0),
                "sl_long_pct": config.get("sl_long_pct", 2.0),
                "tp_short_pct": config.get("tp_short_pct", 2.0),
                "sl_short_pct": config.get("sl_short_pct", 2.0),

                # Time Filter
                "time_filter_enabled": config.get("time_filter_enabled", False),
                "time_filter_start_hour": config.get("time_filter_start_hour", 0),
                "time_filter_end_hour": config.get("time_filter_end_hour", 23),
            }
        })

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load params: {e}")


@router.post("/ui/strategies/{name}/recalculate")
@limiter.limit("60/minute;1000/day")  # Interactive parameter tuning - allow frequent recalculations
async def ui_recalculate_backtest(
    request: Request,
    name: str,
    user=Depends(require_auth),  # Authentication required
) -> JSONResponse:
    """Web UI: Recalculate backtest with new parameters (without saving).

    Args:
        request: FastAPI request object
        name: Strategy config name

    Returns:
        JSON response with new backtest results

    Raises:
        HTTPException: If config not found or backtest fails
    """
    try:
        # Get JSON body
        body = await request.json()

        # Validate CSRF token from JSON body
        csrf_token = body.get("csrf_token")
        _verify_csrf_token(request, csrf_token)

        # Get parameters from body
        params = body.get("params", {})

        # Debug: Log received parameters
        logger.info(f"=== RECALCULATE: Received parameters for {name} ===")
        logger.info(f"use_martingale: {params.get('use_martingale')}")
        logger.info(f"martingale_mult: {params.get('martingale_mult')}")
        logger.info(f"use_tp_sl: {params.get('use_tp_sl')}")
        logger.info(f"====================================================")

        # Get last backtest data path from cache
        if name not in _backtest_cache:
            raise HTTPException(
                status_code=400,
                detail="No previous backtest found. Please run backtest first."
            )

        cached_data = _backtest_cache[name]
        data_path = cached_data["data_path"]
        old_summary = cached_data["summary"]

        # Load base config and merge with new parameters
        config = storage.load_config(name)

        # Debug: Log config before update
        logger.info(f"=== CONFIG BEFORE UPDATE ===")
        logger.info(f"Config from file - use_martingale: {config.get('use_martingale')}")
        logger.info(f"Config from file - martingale_mult: {config.get('martingale_mult')}")
        logger.info(f"=============================")

        # Update config with new parameters (without saving to disk)
        config.update({
            "strategy_type": params.get("strategy_type", config.get("strategy_type")),
            "mode": params.get("mode", config.get("mode")),
            "symbol": params.get("symbol", config.get("symbol")),
            "rules": params.get("rules", config.get("rules")),
            "k_max": float(params.get("k_max", config.get("k_max", 2.0))),
            "llm_horizon_hours": int(params.get("llm_horizon_hours", config.get("llm_horizon_hours", 24))),
            "llm_min_prob_edge": float(params.get("llm_min_prob_edge", config.get("llm_min_prob_edge", 0.55))),
            "llm_min_trend_strength": float(params.get("llm_min_trend_strength", config.get("llm_min_trend_strength", 0.6))),
            "llm_refresh_interval_bars": int(params.get("llm_refresh_interval_bars", config.get("llm_refresh_interval_bars", 60))),
            "rsi_len": int(params.get("rsi_len", config.get("rsi_len", 14))),
            "rsi_ovb": int(params.get("rsi_ovb", config.get("rsi_ovb", 70))),
            "rsi_ovs": int(params.get("rsi_ovs", config.get("rsi_ovs", 30))),
            "bb_len": int(params.get("bb_len", config.get("bb_len", 20))),
            "bb_mult": float(params.get("bb_mult", config.get("bb_mult", 2.0))),
            "ema_fast_len": int(params.get("ema_fast_len", config.get("ema_fast_len", 12))),
            "ema_slow_len": int(params.get("ema_slow_len", config.get("ema_slow_len", 26))),
            "atr_len": int(params.get("atr_len", config.get("atr_len", 14))),
            "adx_len": int(params.get("adx_len", config.get("adx_len", 14))),
            "vol_ma_len": int(params.get("vol_ma_len", config.get("vol_ma_len", 21))),
            "vol_mult": float(params.get("vol_mult", config.get("vol_mult", 0.5))),
            "base_size": float(params.get("base_size", config.get("base_size", 0.1))),
            "allow_long": bool(params.get("allow_long", config.get("allow_long", True))),
            "allow_short": bool(params.get("allow_short", config.get("allow_short", True))),
            "base_position_pct": float(params.get("base_position_pct", config.get("base_position_pct", 10.0))),
            "pyramiding": int(params.get("pyramiding", config.get("pyramiding", 1))),
            "use_martingale": bool(params.get("use_martingale", config.get("use_martingale", False))),
            "martingale_mult": float(params.get("martingale_mult", config.get("martingale_mult", 1.5))),
            "use_tp_sl": bool(params.get("use_tp_sl", config.get("use_tp_sl", False))),
            "tp_long_pct": float(params.get("tp_long_pct", config.get("tp_long_pct", 2.0))),
            "sl_long_pct": float(params.get("sl_long_pct", config.get("sl_long_pct", 2.0))),
            "tp_short_pct": float(params.get("tp_short_pct", config.get("tp_short_pct", 2.0))),
            "sl_short_pct": float(params.get("sl_short_pct", config.get("sl_short_pct", 2.0))),
            "time_filter_enabled": bool(params.get("time_filter_enabled", config.get("time_filter_enabled", False))),
            "time_filter_start_hour": int(params.get("time_filter_start_hour", config.get("time_filter_start_hour", 0))),
            "time_filter_end_hour": int(params.get("time_filter_end_hour", config.get("time_filter_end_hour", 23))),
        })

        # Debug: Log updated config
        logger.info(f"=== RECALCULATE: Updated config ===")
        logger.info(f"use_martingale: {config.get('use_martingale')}")
        logger.info(f"martingale_mult: {config.get('martingale_mult')}")
        logger.info(f"====================================")

        # Validate strategy parameters before running backtest
        # RSI thresholds
        rsi_ovs = config.get("rsi_ovs", 30)
        rsi_ovb = config.get("rsi_ovb", 70)
        if rsi_ovs >= rsi_ovb:
            raise HTTPException(
                status_code=400,
                detail=f"RSI Oversold must be less than RSI Overbought. Got ovs={rsi_ovs}, ovb={rsi_ovb}"
            )

        # Time filter parameters
        if config.get("time_filter_enabled", False):
            time_filter_start_hour = config.get("time_filter_start_hour", 0)
            time_filter_end_hour = config.get("time_filter_end_hour", 23)
            if not (0 <= time_filter_start_hour <= 23):
                raise HTTPException(
                    status_code=400,
                    detail=f"time_filter_start_hour must be in [0, 23], got {time_filter_start_hour}"
                )
            if not (0 <= time_filter_end_hour <= 23):
                raise HTTPException(
                    status_code=400,
                    detail=f"time_filter_end_hour must be in [0, 23], got {time_filter_end_hour}"
                )

        # TP/SL validation
        if config.get("use_tp_sl", False):
            tp_long_pct = config.get("tp_long_pct", 2.0)
            sl_long_pct = config.get("sl_long_pct", 2.0)
            tp_short_pct = config.get("tp_short_pct", 2.0)
            sl_short_pct = config.get("sl_short_pct", 2.0)
            if tp_long_pct <= 0:
                raise HTTPException(status_code=400, detail=f"TP Long % must be greater than 0, got {tp_long_pct}")
            if sl_long_pct <= 0:
                raise HTTPException(status_code=400, detail=f"SL Long % must be greater than 0, got {sl_long_pct}")
            if tp_short_pct <= 0:
                raise HTTPException(status_code=400, detail=f"TP Short % must be greater than 0, got {tp_short_pct}")
            if sl_short_pct <= 0:
                raise HTTPException(status_code=400, detail=f"SL Short % must be greater than 0, got {sl_short_pct}")

        # Pyramiding validation
        pyramiding = config.get("pyramiding", 1)
        if pyramiding < 1:
            raise HTTPException(status_code=400, detail=f"Pyramiding must be at least 1, got {pyramiding}")

        # Base position validation
        base_position_pct = config.get("base_position_pct", 10.0)
        if base_position_pct <= 0 or base_position_pct > 100:
            raise HTTPException(status_code=400, detail=f"Base Position % must be between 0 and 100, got {base_position_pct}")

        # Run backtest with new parameters
        summary = run_backtest_from_config_dict(
            config=config,
            data_path=data_path,
            use_llm=False,  # Don't use LLM for recalculation by default
            llm_model=None,
            llm_url=None,
            initial_equity=old_summary.get("initial_equity", 10000.0),
            fee_rate=0.001,
            slippage_bps=1.0,
        )

        # Update cache with new results
        _backtest_cache[name] = {
            "summary": summary,
            "data_path": data_path,
            "config": config,
        }

        # Return new summary (serialize Trade objects for JSON)
        return JSONResponse({
            "success": True,
            "summary": _serialize_summary(summary)
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recalculate backtest failed for '{name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Recalculate failed: {sanitize_error_message(e)}"
        )


@router.post("/ui/strategies/{name}/save-params")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Save strategy parameters
async def ui_save_strategy_params(
    request: Request,
    name: str,
    user=Depends(require_auth),  # Authentication required
) -> JSONResponse:
    """Web UI: Save strategy parameters to disk.

    Args:
        request: FastAPI request object
        name: Strategy config name

    Returns:
        JSON response with success status

    Raises:
        HTTPException: If validation fails or save error
    """
    try:
        # Get JSON body
        body = await request.json()

        # Validate CSRF token from JSON body
        csrf_token = body.get("csrf_token")
        _verify_csrf_token(request, csrf_token)

        # Get parameters from body
        params = body.get("params", {})

        # Load base config
        config = storage.load_config(name)

        # Update config with new parameters
        config.update({
            "strategy_type": params.get("strategy_type", config.get("strategy_type")),
            "mode": params.get("mode", config.get("mode")),
            "symbol": params.get("symbol", config.get("symbol")),
            "rules": params.get("rules", config.get("rules")),
            "k_max": float(params.get("k_max", config.get("k_max", 2.0))),
            "llm_horizon_hours": int(params.get("llm_horizon_hours", config.get("llm_horizon_hours", 24))),
            "llm_min_prob_edge": float(params.get("llm_min_prob_edge", config.get("llm_min_prob_edge", 0.55))),
            "llm_min_trend_strength": float(params.get("llm_min_trend_strength", config.get("llm_min_trend_strength", 0.6))),
            "llm_refresh_interval_bars": int(params.get("llm_refresh_interval_bars", config.get("llm_refresh_interval_bars", 60))),
            "rsi_len": int(params.get("rsi_len", config.get("rsi_len", 14))),
            "rsi_ovb": int(params.get("rsi_ovb", config.get("rsi_ovb", 70))),
            "rsi_ovs": int(params.get("rsi_ovs", config.get("rsi_ovs", 30))),
            "bb_len": int(params.get("bb_len", config.get("bb_len", 20))),
            "bb_mult": float(params.get("bb_mult", config.get("bb_mult", 2.0))),
            "ema_fast_len": int(params.get("ema_fast_len", config.get("ema_fast_len", 12))),
            "ema_slow_len": int(params.get("ema_slow_len", config.get("ema_slow_len", 26))),
            "atr_len": int(params.get("atr_len", config.get("atr_len", 14))),
            "adx_len": int(params.get("adx_len", config.get("adx_len", 14))),
            "vol_ma_len": int(params.get("vol_ma_len", config.get("vol_ma_len", 21))),
            "vol_mult": float(params.get("vol_mult", config.get("vol_mult", 0.5))),
            "base_size": float(params.get("base_size", config.get("base_size", 0.1))),
            "allow_long": bool(params.get("allow_long", config.get("allow_long", True))),
            "allow_short": bool(params.get("allow_short", config.get("allow_short", True))),
            "base_position_pct": float(params.get("base_position_pct", config.get("base_position_pct", 10.0))),
            "pyramiding": int(params.get("pyramiding", config.get("pyramiding", 1))),
            "use_martingale": bool(params.get("use_martingale", config.get("use_martingale", False))),
            "martingale_mult": float(params.get("martingale_mult", config.get("martingale_mult", 1.5))),
            "use_tp_sl": bool(params.get("use_tp_sl", config.get("use_tp_sl", False))),
            "tp_long_pct": float(params.get("tp_long_pct", config.get("tp_long_pct", 2.0))),
            "sl_long_pct": float(params.get("sl_long_pct", config.get("sl_long_pct", 2.0))),
            "tp_short_pct": float(params.get("tp_short_pct", config.get("tp_short_pct", 2.0))),
            "sl_short_pct": float(params.get("sl_short_pct", config.get("sl_short_pct", 2.0))),
            "time_filter_enabled": bool(params.get("time_filter_enabled", config.get("time_filter_enabled", False))),
            "time_filter_start_hour": int(params.get("time_filter_start_hour", config.get("time_filter_start_hour", 0))),
            "time_filter_end_hour": int(params.get("time_filter_end_hour", config.get("time_filter_end_hour", 23))),
        })

        # Save config to disk
        storage.save_config(name, config)

        return JSONResponse({
            "success": True,
            "message": "Strategy parameters saved successfully"
        })

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Save params failed for '{name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save parameters: {sanitize_error_message(e)}"
        )
