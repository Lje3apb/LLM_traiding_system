"""FastAPI server for the LLM Trading System."""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from llm_trading_system.api.auth import (
    authenticate_user,
    generate_ws_token,
    get_current_user,
    optional_auth,
    require_auth,
    validate_ws_token,
)
from llm_trading_system.api import api_routes, ui_routes, ws_routes
from llm_trading_system.api.services.validation import (
    sanitize_error_message,
    validate_data_path,
)
from llm_trading_system.data.data_manager import get_data_manager
from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict
from llm_trading_system.engine.live_service import (
    LiveSessionConfig,
    LiveSessionManager,
    get_session_manager,
)
from llm_trading_system.strategies import storage

# Setup logger
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="LLM Trading System API",
    version="0.1.0",
    description="HTTP JSON API for backtesting and strategy management",
)

# ============================================================================
# Middleware Configuration
# ============================================================================
# IMPORTANT: Middleware order matters!
# - Middleware is executed in REVERSE order for responses
# - First added = outermost layer = executes first for requests, last for responses
#
# Order (outer to inner):
# 1. CORS - Must be first to handle preflight requests
# 2. Security Headers - Applied to all responses
# 3. Session Management - Handles authentication
# 4. CSRF Middleware - Added via @app.middleware decorator below
# 5. Application Logic
# ============================================================================

# ============================================================================
# CORS Configuration (Cross-Origin Resource Sharing)
# ============================================================================
# Controls which origins can access the API
# Default: No CORS (empty allow_origins list)
# To enable CORS for specific origins, set CORS_ORIGINS environment variable:
#   CORS_ORIGINS="http://localhost:3000,https://trading.example.com"

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
allowed_origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Empty by default - no CORS
    allow_credentials=True,  # Allow cookies and authorization headers
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)

# ============================================================================
# Security Headers Middleware
# ============================================================================
# Adds security headers to all HTTP responses to protect against common attacks

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses.

    Security headers added:
    - Strict-Transport-Security (HSTS): Forces HTTPS for 1 year
    - X-Frame-Options: Prevents clickjacking attacks
    - X-Content-Type-Options: Prevents MIME-sniffing attacks
    - Referrer-Policy: Controls referrer information leakage
    - X-XSS-Protection: Enables browser XSS filtering (legacy browsers)
    - Content-Security-Policy: Restricts resource loading (defense in depth)

    Note: HSTS header only added in production (when ENV=production)
    """
    response = await call_next(request)

    # Strict-Transport-Security (HSTS)
    # Only set in production to avoid issues in development
    if os.getenv("ENV", "").lower() == "production":
        # max-age=31536000: 1 year in seconds
        # includeSubDomains: Apply to all subdomains
        # preload: Allow inclusion in browser HSTS preload lists
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

    # X-Frame-Options: DENY
    # Prevents page from being displayed in iframe/frame/embed/object
    # Protects against clickjacking attacks
    response.headers["X-Frame-Options"] = "DENY"

    # X-Content-Type-Options: nosniff
    # Prevents browsers from MIME-sniffing responses
    # Forces browser to respect Content-Type header
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Referrer-Policy: same-origin
    # Only send referrer for same-origin requests
    # Prevents leaking sensitive information in referrer header
    response.headers["Referrer-Policy"] = "same-origin"

    # X-XSS-Protection: 1; mode=block (legacy, but good for old browsers)
    # Enables browser XSS filtering and blocks page if attack detected
    # Modern browsers use CSP instead, but this adds defense in depth
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Content-Security-Policy (CSP)
    # Restrictive CSP for defense in depth
    # default-src 'self': Only load resources from same origin
    # script-src: Allow inline scripts and unpkg.com for charts library
    # style-src: Allow inline styles
    # img-src: Allow images from same origin and data URIs
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )

    return response

# ============================================================================
# Session Management (Authentication)
# ============================================================================

# Add SessionMiddleware for session-based authentication
# IMPORTANT: In production, use a secure random secret key from environment variable
# Generate a new secret with: python -c "import secrets; print(secrets.token_hex(32))"
SESSION_SECRET_KEY = os.getenv(
    "SESSION_SECRET_KEY",
    "default-dev-secret-key-change-in-production-12345678901234567890"
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="trading_session",
    max_age=86400,  # 24 hours in seconds
    same_site="strict",
    https_only=os.getenv("ENV", "").lower() == "production",
)

# ============================================================================
# Custom Exception Handlers
# ============================================================================


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: HTTPException):
    """Handle 401 Unauthorized errors.

    For UI endpoints: Redirect to login page
    For API endpoints: Return JSON error
    """
    path = request.url.path

    if path.startswith("/ui") and not path.startswith("/ui/login"):
        # UI endpoint - redirect to login with next parameter
        from urllib.parse import quote
        login_url = f"/ui/login?next={quote(path)}"
        return RedirectResponse(url=login_url, status_code=303)
    else:
        # API endpoint - return JSON error
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc.detail)}
        )


# ============================================================================
# Rate Limiting (DoS Protection & Abuse Prevention)
# ============================================================================

# Import shared rate limiter (created in rate_limiter.py to avoid circular imports
# and Windows .env encoding issues)
from llm_trading_system.api.rate_limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================================
# Rate Limit Strategy (by endpoint category)
# ============================================================================
#
# CATEGORY                      | LIMIT                  | USE CASE
# ------------------------------|------------------------|---------------------------
# Public/Light                  | 60/minute              | Health check, public info
# Standard Business (Read)      | 1000/hour              | GET strategies, sessions, data
# Standard Business (Write)     | 30/minute;500/hour     | Save/delete strategies, settings
# Authentication                | 20/minute;100/hour     | Login attempts (brute force protection)
# Heavy Operations              | 10/minute;100/day      | Backtest, live session creation
# Very Heavy Operations         | 3/minute;20/day        | Data download from exchanges
# Session Control               | 50/minute              | Start/stop trading sessions
# Chart Data                    | 60/minute              | Chart data requests
# File Listing                  | 60/minute              | File listing operations
#
# Combined Limits (e.g., "10/minute;100/day"):
#   - First limit (10/minute) prevents burst abuse
#   - Second limit (100/day) prevents sustained abuse
#   - Both must be satisfied for request to succeed
#
# ============================================================================
# Endpoint Rate Limit Configuration Table
# ============================================================================
#
# | METHOD | ENDPOINT                                    | RATE LIMIT             | CATEGORY                   | AUTH   |
# |--------|---------------------------------------------|------------------------|----------------------------|--------|
# | GET    | /health                                     | 60/minute              | Public/Light               | No     |
# | GET    | /                                           | 60/minute              | Public/Light               | No     |
# | GET    | /ui/login                                   | 60/minute              | Public/Light               | No     |
# | POST   | /ui/login                                   | 20/minute;100/hour     | Authentication             | No     |
# | GET    | /ui/logout                                  | 60/minute              | Public/Light               | Yes    |
# | GET    | /strategies                                 | 1000/hour              | Standard Business (Read)   | No     |
# | GET    | /strategies/{name}                          | 1000/hour              | Standard Business (Read)   | No     |
# | POST   | /strategies/{name}                          | 30/minute;500/hour     | Standard Business (Write)  | No     |
# | DELETE | /strategies/{name}                          | 30/minute;500/hour     | Standard Business (Write)  | No     |
# | GET    | /api/live/sessions                          | 1000/hour              | Standard Business (Read)   | No     |
# | POST   | /api/live/sessions                          | 10/minute;100/day      | Heavy Operation            | Yes    |
# | GET    | /api/live/sessions/{id}                     | 1000/hour              | Standard Business (Read)   | No     |
# | POST   | /api/live/sessions/{id}/start               | 50/minute              | Session Control            | Yes    |
# | POST   | /api/live/sessions/{id}/stop                | 50/minute              | Session Control            | Yes    |
# | GET    | /api/live/sessions/{id}/trades              | 1000/hour              | Standard Business (Read)   | No     |
# | GET    | /api/live/sessions/{id}/bars                | 1000/hour              | Standard Business (Read)   | No     |
# | GET    | /api/live/sessions/{id}/account             | 1000/hour              | Standard Business (Read)   | No     |
# | WS     | /ws/live/{id}                               | None (WebSocket)       | Real-time Data             | No     |
# | POST   | /backtest                                   | 10/minute;100/day      | Heavy Operation            | No     |
# | GET    | /ui/                                        | 1000/hour              | Standard Business (Read)   | Yes    |
# | GET    | /ui/live                                    | 1000/hour              | Standard Business (Read)   | Yes    |
# | GET    | /ui/strategies/new                          | 1000/hour              | Standard Business (Read)   | Yes    |
# | GET    | /ui/strategies/{name}/edit                  | 1000/hour              | Standard Business (Read)   | Yes    |
# | POST   | /ui/strategies/{name}/save                  | 30/minute;500/hour     | Standard Business (Write)  | Yes    |
# | POST   | /ui/strategies/{name}/delete                | 30/minute;500/hour     | Standard Business (Write)  | Yes    |
# | GET    | /ui/strategies/{name}/backtest              | 1000/hour              | Standard Business (Read)   | Yes    |
# | POST   | /ui/strategies/{name}/backtest              | 10/minute;100/day      | Heavy Operation            | Yes    |
# | GET    | /ui/backtest/{name}/chart-data              | 60/minute              | Chart Data                 | Yes    |
# | POST   | /ui/strategies/{name}/download_data         | 3/minute;20/day        | Very Heavy Operation       | Yes    |
# | GET    | /ui/settings                                | 1000/hour              | Standard Business (Read)   | Yes    |
# | POST   | /ui/settings                                | 30/minute;500/hour     | Standard Business (Write)  | Yes    |
# | GET    | /ui/data/files                              | 60/minute              | File Listing               | Yes    |
#
# Total Endpoints: 32 (31 HTTP + 1 WebSocket)
# Authenticated Endpoints: 19
# Public Endpoints: 13
#
# Notes:
# - Global default fallback: 1000/hour (applied if no specific limit is set)
# - WebSocket endpoint (/ws/live/{id}) does not use rate limiting (managed by connection limits)
# - All rate limits are per-IP address
# - Combined limits (e.g., "10/minute;100/day") require both conditions to be satisfied
#
# ============================================================================

# ============================================================================
# Setup templates and static files
# ============================================================================
BASE_DIR = Path(__file__).resolve().parent
# Jinja2Templates enables autoescape by default for .html, .htm, .xml files
# This prevents XSS attacks by automatically escaping user-provided content
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# CSRF token generation is handled by the csrf_middleware below
# Templates receive csrf_token from request.cookies

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ============================================================================
# Register API Routes
# ============================================================================
# Include API routes from separate module
app.include_router(api_routes.router, tags=["API"])

# ============================================================================
# Register UI Routes
# ============================================================================
# Include UI routes from separate module
app.include_router(ui_routes.router, tags=["UI"])

# Share templates with ui_routes (limiter is already shared via rate_limiter.py)
ui_routes.templates = templates

# ============================================================================
# Register WebSocket Routes
# ============================================================================
# Include WebSocket routes from separate module
app.include_router(ws_routes.router, tags=["WebSocket"])

# Global storage for backtest results (in-memory cache)
# Key: strategy name, Value: dict with summary, ohlcv_data, trades, data_path
_backtest_cache: dict[str, dict[str, Any]] = {}


# ============================================================================
# CSRF Protection (Double Submit Cookie Pattern)
# ============================================================================


def _generate_csrf_token() -> str:
    """Generate a secure random CSRF token.

    Returns:
        64-character hexadecimal CSRF token
    """
    return secrets.token_hex(32)


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
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing from cookie. Please refresh the page and try again."
        )

    if not form_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing from form submission. This request has been blocked for security."
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(cookie_token, form_token):
        raise HTTPException(
            status_code=403,
            detail="CSRF token validation failed. This may indicate a Cross-Site Request Forgery attack."
        )


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """Add CSRF token cookie to all GET requests for UI pages.

    This middleware implements the Double Submit Cookie pattern:
    1. On GET requests to /ui/*, set a random CSRF token in a cookie
    2. The cookie is accessible to JavaScript (httponly=False)
    3. Forms must submit this token for POST requests
    4. Token is validated server-side against the cookie

    Security Properties:
    - SameSite=Strict prevents CSRF from external sites
    - Secure=True in production (HTTPS only)
    - Token changes on each page load (stateless)
    """
    response = await call_next(request)

    # Only set CSRF cookie for GET requests to UI pages
    if request.method == "GET" and request.url.path.startswith("/ui"):
        csrf_token = _generate_csrf_token()

        # Determine if we're in production
        is_production = os.getenv("ENV", "").lower() == "production"

        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,  # Allow JavaScript to read for form submission
            samesite="strict",  # Prevent CSRF from external sites
            secure=is_production,  # HTTPS only in production
            max_age=3600,  # 1 hour expiration
        )

    return response


# ============================================================================
# Live Trading API (JSON)
# ============================================================================
# NOTE: Basic API routes (health, strategies, backtest, list/get sessions)
#       are now in api_routes.py and included via app.include_router()
# NOTE: Helper functions (validate_data_path, sanitize_error_message)
#       are now in services/validation.py and imported above
# ============================================================================


@app.post("/api/live/sessions")
@limiter.limit("10/minute;100/day")  # HEAVY OPERATION: Create live trading session
async def create_live_session(request_obj: Request, request: dict[str, Any], user=Depends(require_auth)) -> dict[str, Any]:
    """Create a new live/paper trading session.

    Request body should contain:
        - mode: "paper" or "real"
        - symbol: Trading symbol (e.g., "BTCUSDT")
        - timeframe: Bar timeframe (default: "5m")
        - strategy_config: Strategy configuration dict or name
        - llm_enabled: Enable LLM wrapper (default: false)
        - llm_config: LLM configuration dict (optional)
        - initial_deposit: Initial deposit for paper trading (default: 10000)
        - fee_rate: Trading fee rate (default: 0.0005)
        - slippage_bps: Slippage in basis points (default: 1.0)
        - poll_interval: Polling interval in seconds (default: 1.0)

    Returns:
        Session info with session_id, mode, status, and initial state

    Raises:
        HTTPException: If validation fails (400/422) or creation error (500)
    """
    # Extract and validate required fields
    body = request
    if "mode" not in body:
        raise HTTPException(status_code=400, detail="Missing 'mode' field")

    if "symbol" not in body:
        raise HTTPException(status_code=400, detail="Missing 'symbol' field")

    if "strategy_config" not in body:
        raise HTTPException(status_code=400, detail="Missing 'strategy_config' field")

    try:
        # Build LiveSessionConfig
        config = LiveSessionConfig(
            mode=body["mode"],
            symbol=body["symbol"],
            timeframe=body.get("timeframe", "5m"),
            strategy_config=body["strategy_config"],
            llm_enabled=body.get("llm_enabled", False),
            llm_config=body.get("llm_config"),
            initial_deposit=body.get("initial_deposit", 10000.0),
            fee_rate=body.get("fee_rate", 0.0005),
            slippage_bps=body.get("slippage_bps", 1.0),
            poll_interval=body.get("poll_interval", 1.0),
        )

        # Create session
        manager = get_session_manager()
        session_id = manager.create_session(config)

        # Get initial status
        status = manager.get_status(session_id)

        return status

    except ValueError as e:
        # Configuration error or missing env vars
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Other errors
        raise HTTPException(
            status_code=500, detail=f"Failed to create session: {sanitize_error_message(e)}"
        )


@app.post("/api/live/sessions/{session_id}/start")
@limiter.limit("50/minute")  # SESSION CONTROL: Start trading session
async def start_live_session(request: Request, session_id: str, user=Depends(require_auth)) -> dict[str, Any]:
    """Start a live/paper trading session.

    Args:
        session_id: Session ID

    Returns:
        Session status with current state

    Raises:
        HTTPException: If session not found (404) or start error (500)
    """
    try:
        manager = get_session_manager()
        status = manager.start_session(session_id)
        return status
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start session: {sanitize_error_message(e)}"
        )


@app.post("/api/live/sessions/{session_id}/stop")
@limiter.limit("50/minute")  # SESSION CONTROL: Stop trading session
async def stop_live_session(request: Request, session_id: str, user=Depends(require_auth)) -> dict[str, Any]:
    """Stop a live/paper trading session.

    Args:
        session_id: Session ID

    Returns:
        Session status with final state

    Raises:
        HTTPException: If session not found (404) or stop error (500)
    """
    try:
        manager = get_session_manager()
        status = manager.stop_session(session_id)
        return status
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop session: {sanitize_error_message(e)}"
        )


@app.get("/api/live/sessions/{session_id}/trades")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get session trades
async def get_live_session_trades(request: Request, session_id: str, limit: int = 100) -> dict[str, Any]:
    """Get trades from a live/paper trading session.

    Args:
        session_id: Session ID
        limit: Maximum number of trades to return (default: 100)

    Returns:
        Dictionary with "trades" key containing list of trade dicts

    Raises:
        HTTPException: If session not found (404)
    """
    try:
        manager = get_session_manager()
        trades = manager.get_trades(session_id, limit=limit)
        return {"trades": trades}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get trades: {sanitize_error_message(e)}"
        )


@app.get("/api/live/sessions/{session_id}/bars")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get session bars
async def get_live_session_bars(request: Request, session_id: str, limit: int = 500) -> dict[str, Any]:
    """Get recent bars from a live/paper trading session.

    Args:
        session_id: Session ID
        limit: Maximum number of bars to return (default: 500)

    Returns:
        Dictionary with "bars" key containing list of bar dicts

    Raises:
        HTTPException: If session not found (404)
    """
    try:
        manager = get_session_manager()
        bars = manager.get_recent_bars(session_id, limit=limit)
        return {"bars": bars}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get bars: {sanitize_error_message(e)}"
        )


@app.get("/api/live/sessions/{session_id}/account")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get account snapshot
async def get_live_session_account(request: Request, session_id: str) -> dict[str, Any]:
    """Get account snapshot from a live/paper trading session.

    This returns the current account state including:
    - mode: "paper" or "real"
    - equity: Current equity (for real mode, from live exchange)
    - balance: Current balance
    - position: Current position info (if any)

    Args:
        session_id: Session ID

    Returns:
        Account snapshot dictionary

    Raises:
        HTTPException: If session not found (404)
    """
    try:
        manager = get_session_manager()
        return manager.get_account_snapshot(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get account snapshot: {sanitize_error_message(e)}"
        )


# ============================================================================
# WebSocket Routes
# ============================================================================
# NOTE: WebSocket endpoint has been migrated to ws_routes.py
# Included via app.include_router(ws_routes.router) above
# ============================================================================


# ============================================================================
# Web UI Routes
# ============================================================================
# NOTE: All UI routes have been migrated to ui_routes.py
# Included via app.include_router(ui_routes.router) above
# ============================================================================



def main() -> None:
    """Run the API server for local development."""
    import uvicorn

    uvicorn.run(
        "llm_trading_system.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
