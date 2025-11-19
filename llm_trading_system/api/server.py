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
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from llm_trading_system.api.auth import (
    authenticate_user,
    generate_ws_token,
    get_current_user,
    optional_auth,
    require_auth,
    validate_ws_token,
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

# Initialize rate limiter with global defaults
# Uses IP address as identifier for rate limiting
# Note: Use os.devnull to prevent .env reading and avoid Windows encoding issues
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",  # Use in-memory storage (suitable for single-instance deployment)
    config_filename=os.devnull,  # Use null device to prevent .env reading (cross-platform fix for Windows encoding)
    default_limits=["1000/hour"],  # Global fallback: 1000 requests per hour per IP
)
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
# Helper Functions
# ============================================================================


def _validate_data_path(path_str: str) -> Path:
    """Validate and resolve data path to prevent path traversal attacks.

    Args:
        path_str: User-provided path string

    Returns:
        Resolved absolute Path object

    Raises:
        ValueError: If path contains traversal attempts or is outside allowed directory
    """
    # Define allowed base directories
    project_root = Path(__file__).resolve().parent.parent.parent
    allowed_dirs = [
        project_root / "data",
        project_root / "temp",
        Path.cwd() / "data",
    ]

    # Resolve the path
    try:
        user_path = Path(path_str).resolve()
    except (ValueError, OSError) as e:
        raise ValueError(f"Invalid path: {e}")

    # Check if path is within any allowed directory
    for allowed_dir in allowed_dirs:
        try:
            allowed_dir_resolved = allowed_dir.resolve()
            # Check if user_path is relative to allowed_dir
            user_path.relative_to(allowed_dir_resolved)
            # Path is safe, return it
            return user_path
        except (ValueError, OSError):
            # Not relative to this allowed_dir, try next
            continue

    # If we get here, path is not in any allowed directory
    raise ValueError(
        f"Path '{path_str}' is outside allowed directories. "
        f"Data files must be in 'data/' or 'temp/' directories."
    )


def _sanitize_error_message(e: Exception) -> str:
    """Sanitize exception message to avoid leaking sensitive information.

    Args:
        e: The exception to sanitize

    Returns:
        A safe error message string
    """
    error_type = type(e).__name__

    # Whitelist safe exception types that can show full message
    safe_types = {"ValueError", "FileNotFoundError", "HTTPException", "KeyError"}

    if error_type in safe_types:
        return str(e)
    else:
        # Generic message for other exceptions (prevents leaking internal details)
        return f"{error_type} occurred. Check server logs for details."


@app.get("/health")
@limiter.limit("60/minute")  # PUBLIC/LIGHT: Health check monitoring
async def health_check(request: Request) -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Status dictionary
    """
    return {"status": "ok"}


@app.get("/strategies")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): List strategies
async def list_strategies(request: Request) -> dict[str, list[str]]:
    """List all available strategy configurations.

    Returns:
        Dictionary with "items" key containing list of config names
    """
    try:
        configs = storage.list_configs()
        return {"items": configs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list configs: {e}")


@app.get("/strategies/{name}")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get strategy
async def get_strategy(request: Request, name: str) -> dict[str, Any]:
    """Load a strategy configuration by name.

    Args:
        name: Strategy config name

    Returns:
        Strategy configuration dictionary

    Raises:
        HTTPException: If config not found (404) or error loading (500)
    """
    try:
        config = storage.load_config(name)
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


@app.post("/strategies/{name}")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Save strategy
async def save_strategy(request: Request, name: str, config: dict[str, Any]) -> dict[str, str]:
    """Save or update a strategy configuration.

    Args:
        name: Strategy config name
        config: Strategy configuration dictionary

    Returns:
        Status dictionary with "status" and "name"

    Raises:
        HTTPException: If validation fails (400) or save error (500)
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


@app.delete("/strategies/{name}")
@limiter.limit("30/minute;500/hour")  # STANDARD BUSINESS (WRITE): Delete strategy
async def delete_strategy(request: Request, name: str) -> dict[str, str]:
    """Delete a strategy configuration.

    Args:
        name: Strategy config name

    Returns:
        Status dictionary

    Raises:
        HTTPException: If config not found (404) or error deleting (500)
    """
    try:
        storage.delete_config(name)
        return {"status": "deleted", "name": name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete config: {e}")


@app.post("/backtest")
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
        validated_path = _validate_data_path(data_path_str)
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
            status_code=500, detail=f"Backtest failed: {_sanitize_error_message(e)}"
        )


# ============================================================================
# Live Trading API (JSON)
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
            status_code=500, detail=f"Failed to create session: {_sanitize_error_message(e)}"
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
            status_code=500, detail=f"Failed to start session: {_sanitize_error_message(e)}"
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
            status_code=500, detail=f"Failed to stop session: {_sanitize_error_message(e)}"
        )


@app.get("/api/live/sessions/{session_id}")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): Get session status
async def get_live_session_status(request: Request, session_id: str) -> dict[str, Any]:
    """Get status and current state of a live/paper trading session.

    Args:
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
            status_code=500, detail=f"Failed to get session status: {_sanitize_error_message(e)}"
        )


@app.get("/api/live/sessions")
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): List sessions
async def list_live_sessions(request: Request) -> dict[str, list[dict[str, Any]]]:
    """List all live/paper trading sessions.

    Returns:
        Dictionary with "sessions" key containing list of session status dicts
    """
    try:
        manager = get_session_manager()
        sessions = manager.list_status()
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list sessions: {_sanitize_error_message(e)}"
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
            status_code=500, detail=f"Failed to get trades: {_sanitize_error_message(e)}"
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
            status_code=500, detail=f"Failed to get bars: {_sanitize_error_message(e)}"
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
            status_code=500,
            detail=f"Failed to get account snapshot: {_sanitize_error_message(e)}",
        )


@app.websocket("/ws/live/{session_id}")
async def live_session_websocket(websocket: WebSocket, session_id: str, token: str = "") -> None:
    """WebSocket endpoint for real-time live session updates.

    Security Features:
    - Token-based authentication (query parameter ?token=...)
    - Origin validation (prevents CSRF attacks)
    - Connection limits per user
    - Message rate limiting
    - Permission checks (users can only access their own sessions)
    - Message validation (pydantic schemas)
    - Resource cleanup on disconnect

    Streams:
    - state_update: Current session state (periodically every 2 seconds)
    - trade: New trade executed
    - bar: New bar completed
    - pong: Response to ping messages

    Args:
        websocket: WebSocket connection
        session_id: Trading session ID to monitor
        token: Authentication token (required query parameter)

    Query Parameters:
        token: WebSocket authentication token generated by generate_ws_token()

    Incoming Message Format:
        {
            "type": "ping" | "subscribe" | "unsubscribe",
            "payload": {...}
        }

    Outgoing Message Format:
        {
            "type": "pong" | "state_update" | "trade" | "bar" | "error",
            "payload": {...},
            "message": "error message (for type=error)"
        }

    Security:
        - Requires valid authentication token (expires after 1 hour)
        - Invalid tokens → close with code 4401
        - Invalid origin → close with code 1008
        - Too many connections → close with code 1008
        - No permission → close with code 1008
        - Maximum connection duration: 1 hour
        - Rate limit: 10 messages/second, 100 messages/minute per user
    """
    from llm_trading_system.api.services.websocket_security import (
        check_connection_limit,
        check_message_rate_limit,
        check_session_permission,
        register_connection,
        unregister_connection,
        validate_incoming_message,
        validate_origin,
    )

    # ========================================================================
    # Step 1: Validate authentication token BEFORE accepting connection
    # ========================================================================
    user_id = validate_ws_token(token)

    if not user_id:
        logger.warning(f"WebSocket auth failed: invalid token for session {session_id}")
        await websocket.close(code=4401, reason="Invalid or expired authentication token")
        return

    # ========================================================================
    # Step 2: Validate Origin header (prevent CSRF attacks)
    # ========================================================================
    if not validate_origin(websocket):
        logger.warning(f"WebSocket rejected: invalid origin for user {user_id}")
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    # ========================================================================
    # Step 3: Check connection limit (prevent resource exhaustion)
    # ========================================================================
    if not check_connection_limit(user_id, websocket):
        logger.warning(f"WebSocket rejected: connection limit for user {user_id}")
        await websocket.close(code=1008, reason="Too many connections")
        return

    # ========================================================================
    # Step 4: Get session manager and check permissions
    # ========================================================================
    manager = get_session_manager()

    # Check if user has permission to access this session
    if not check_session_permission(user_id, session_id, manager):
        logger.warning(f"WebSocket rejected: user {user_id} has no permission for session {session_id}")
        await websocket.close(code=1008, reason="Access denied")
        return

    # ========================================================================
    # Step 5: All checks passed - accept connection
    # ========================================================================
    await websocket.accept()

    # Store user_id in websocket state for later use
    websocket.state.user_id = user_id

    # Register connection for tracking
    register_connection(user_id, websocket)

    try:
        # Get initial session status
        try:
            status = manager.get_status(session_id)
        except KeyError:
            await websocket.send_json(
                {"type": "error", "message": f"Session {session_id} not found"}
            )
            await websocket.close()
            return

        # Send initial state
        await websocket.send_json({"type": "state_update", "payload": status})

        # Connection management
        import asyncio
        import time

        MAX_CONNECTION_TIME = 3600  # 1 hour maximum
        connection_start = time.time()

        # Main message loop
        while True:
            # Check connection age
            connection_age = time.time() - connection_start
            if connection_age > MAX_CONNECTION_TIME:
                await websocket.send_json({
                    "type": "error",
                    "message": "Connection timeout - maximum duration (1 hour) exceeded. Please reconnect."
                })
                break

            # Wait for client messages with timeout
            try:
                raw_message = await asyncio.wait_for(
                    websocket.receive_text(), timeout=2.0
                )

                # ============================================================
                # Rate limiting check for incoming messages
                # ============================================================
                if not check_message_rate_limit(user_id):
                    # Rate limit exceeded - close connection
                    await websocket.send_json({
                        "type": "error",
                        "message": "Rate limit exceeded. Connection closed."
                    })
                    await websocket.close(code=1008, reason="Rate limit exceeded")
                    break

                # ============================================================
                # Validate message structure
                # ============================================================
                message = validate_incoming_message(raw_message)
                if not message:
                    # Invalid message - send error but don't close connection
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid message format. Must be JSON with 'type' and optional 'payload'."
                    })
                    continue

                # ============================================================
                # Handle different message types
                # ============================================================
                if message.type == "ping":
                    await websocket.send_json({"type": "pong"})

                elif message.type == "subscribe":
                    # Future: implement subscription management
                    pass

                elif message.type == "unsubscribe":
                    # Future: implement subscription management
                    pass

            except asyncio.TimeoutError:
                # No message from client - send periodic update
                pass

            # ============================================================
            # Send periodic state update
            # ============================================================
            try:
                status = manager.get_status(session_id)
                await websocket.send_json({"type": "state_update", "payload": status})
            except KeyError:
                # Session was deleted
                await websocket.send_json(
                    {"type": "error", "message": f"Session {session_id} was deleted"}
                )
                break
            except Exception as e:
                # Error getting status - log and send sanitized error
                logger.error(f"Error getting session status: {e}", exc_info=True)
                await websocket.send_json(
                    {"type": "error", "message": "Error fetching session status"}
                )

            # Sleep before next update
            await asyncio.sleep(2.0)

    except WebSocketDisconnect:
        # Client disconnected - normal cleanup
        logger.info(f"WebSocket client disconnected: user {user_id}, session {session_id}")

    except Exception as e:
        # Unexpected error - log and send sanitized error
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json(
                {"type": "error", "message": "Internal server error"}
            )
        except:
            pass

    finally:
        # ====================================================================
        # Cleanup resources
        # ====================================================================
        # Unregister connection
        unregister_connection(user_id, websocket)

        # Close connection if still open
        try:
            await websocket.close()
        except:
            pass

        logger.info(f"WebSocket closed: user {user_id}, session {session_id}")


# ============================================================================
# Web UI Routes (HTML)
# ============================================================================


@app.get("/", response_class=RedirectResponse)
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


@app.get("/ui/login", response_class=HTMLResponse)
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
    # If already logged in, redirect to next page
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse(url=next, status_code=303)

    # Get CSRF token from cookie
    csrf_token = request.cookies.get("csrf_token", "")

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next,
            "error": error,
            "csrf_token": csrf_token,
        },
    )


@app.post("/ui/login")
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


@app.get("/ui/logout")
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


@app.get("/ui/", response_class=HTMLResponse)
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

        # Get CSRF token from cookie (set by csrf_middleware)
        csrf_token = request.cookies.get("csrf_token", "")

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


@app.get("/ui/live", response_class=HTMLResponse)
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


@app.get("/ui/strategies/new", response_class=HTMLResponse)
@limiter.limit("1000/hour")  # STANDARD BUSINESS (READ): New strategy form
async def ui_new_strategy(request: Request, user=Depends(require_auth)) -> HTMLResponse:
    """Web UI: Show form to create a new strategy.

    Args:
        request: FastAPI request object

    Returns:
        HTML response with empty strategy form
    """
    # Get CSRF token from cookie (set by csrf_middleware)
    csrf_token = request.cookies.get("csrf_token", "")

    return templates.TemplateResponse(
        "strategy_form.html",
        {
            "request": request,
            "name": None,
            "config": {},
            "csrf_token": csrf_token,
        },
    )


@app.get("/ui/strategies/{name}/edit", response_class=HTMLResponse)
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

        # Get CSRF token from cookie (set by csrf_middleware)
        csrf_token = request.cookies.get("csrf_token", "")

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


@app.post("/ui/strategies/{name}/save")
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


@app.post("/ui/strategies/{name}/delete")
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


@app.get("/ui/strategies/{name}/backtest", response_class=HTMLResponse)
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

        # Get CSRF token from cookie (set by csrf_middleware)
        csrf_token = request.cookies.get("csrf_token", "")

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


@app.post("/ui/strategies/{name}/backtest", response_class=HTMLResponse)
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
            validated_path = _validate_data_path(data_path)
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
            status_code=500, detail=f"Backtest failed: {_sanitize_error_message(e)}"
        )


@app.get("/ui/backtest/{name}/chart-data")
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

        # Extract trades from summary (if available)
        trades_data = []

        # Re-run backtest to get trades data
        # (since summary might not include full trade details)
        from llm_trading_system.engine.backtester import Backtester
        from llm_trading_system.engine.data_feed import CSVDataFeed
        from llm_trading_system.strategies import create_strategy_from_config

        config = cached_data["config"]
        symbol = config.get("symbol", "BTCUSDT")
        strategy = create_strategy_from_config(config, llm_client=None)
        data_feed = CSVDataFeed(path=Path(data_path), symbol=symbol)

        backtester = Backtester(
            strategy=strategy,
            data_feed=data_feed,
            initial_equity=summary.get("initial_equity", 10000.0),
            fee_rate=0.001,
            slippage_bps=1.0,
            symbol=symbol,
        )

        result = backtester.run()

        # Detect bar interval from OHLCV data
        interval_seconds = 3600  # default 1 hour
        if len(ohlcv_data) >= 2:
            interval_seconds = ohlcv_data[1]["time"] - ohlcv_data[0]["time"]

        # Format trades for chart
        for trade in result.trades:
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
            detail=f"Failed to load chart data: {_sanitize_error_message(e)}"
        )


@app.post("/ui/strategies/{name}/download_data")
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


@app.get("/ui/settings", response_class=HTMLResponse)
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

        # Get CSRF token from cookie (set by csrf_middleware)
        csrf_token = request.cookies.get("csrf_token", "")

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


@app.post("/ui/settings")
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


@app.get("/ui/data/files")
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
