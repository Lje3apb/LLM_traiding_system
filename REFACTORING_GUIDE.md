# Server.py Refactoring Guide

## Overview

This document describes the modular refactoring of `server.py` (2210 lines) into a maintainable structure.

## New Module Structure

```
llm_trading_system/api/
├── server.py                    # Main app, middleware, configuration (reduced to ~300 lines)
├── ui_routes.py                 # All UI endpoints (~600 lines)
├── api_routes.py                # All API endpoints (~500 lines)
├── ws_routes.py                 # WebSocket endpoints (~100 lines)
├── services/
│   ├── __init__.py
│   └── validation.py            # Validation helpers (COMPLETED)
├── auth.py                      # Authentication (existing)
├── templates/                   # Jinja2 templates (existing)
└── static/                      # Static files (existing)
```

## Migration Strategy

### Phase 1: Extract Services ✅ COMPLETED
- [x] Create `services/validation.py` with helper functions
- [x] Extract `validate_data_path()`, `sanitize_error_message()`, `validate_strategy_name()`

### Phase 2: Create Route Modules (IN PROGRESS)
- [ ] Create `api_routes.py` for API endpoints
- [ ] Create `ui_routes.py` for UI endpoints
- [ ] Create `ws_routes.py` for WebSocket endpoints

### Phase 3: Refactor server.py
- [ ] Keep only: app creation, middleware, configuration
- [ ] Import and register route modules
- [ ] Remove duplicated code

## Route Organization

### API Routes (api_routes.py)
**Health & Strategy Management:**
- `GET /health` - Health check endpoint
- `GET /strategies` - List all strategies
- `GET /strategies/{name}` - Get specific strategy
- `POST /strategies/{name}` - Save strategy
- `DELETE /strategies/{name}` - Delete strategy
- `POST /backtest` - Run backtest

**Live Trading Sessions:**
- `POST /api/live/sessions` - Create live session
- `GET /api/live/sessions` - List all sessions
- `GET /api/live/sessions/{id}` - Get session status
- `POST /api/live/sessions/{id}/start` - Start session
- `POST /api/live/sessions/{id}/stop` - Stop session
- `GET /api/live/sessions/{id}/trades` - Get session trades
- `GET /api/live/sessions/{id}/bars` - Get session bars
- `GET /api/live/sessions/{id}/account` - Get account snapshot

### UI Routes (ui_routes.py)
**Authentication:**
- `GET /` - Root redirect
- `GET /ui/login` - Login page
- `POST /ui/login` - Process login
- `GET /ui/logout` - Logout

**Strategy Management:**
- `GET /ui/` - Strategy list page
- `GET /ui/strategies/new` - New strategy form
- `GET /ui/strategies/{name}/edit` - Edit strategy form
- `POST /ui/strategies/{name}/save` - Save strategy
- `POST /ui/strategies/{name}/delete` - Delete strategy

**Backtesting:**
- `GET /ui/strategies/{name}/backtest` - Backtest form
- `POST /ui/strategies/{name}/backtest` - Run backtest
- `GET /ui/backtest/{name}/chart-data` - Chart data

**Live Trading:**
- `GET /ui/live` - Live trading page

**Data & Settings:**
- `POST /ui/strategies/{name}/download_data` - Download data
- `GET /ui/settings` - Settings page
- `POST /ui/settings` - Save settings
- `GET /ui/data/files` - List data files

### WebSocket Routes (ws_routes.py)
- `WS /ws/live/{session_id}` - Real-time session updates

## Code Deduplication Opportunities

### 1. Error Handling Pattern
**Before:**
```python
except Exception as e:
    raise HTTPException(
        status_code=500,
        detail=f"Failed to load X: {_sanitize_error_message(e)}"
    )
```

**After (create decorator):**
```python
from functools import wraps

def handle_errors(operation: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise  # Re-raise HTTP exceptions
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to {operation}: {sanitize_error_message(e)}"
                )
        return wrapper
    return decorator

# Usage:
@handle_errors("load strategies")
async def get_strategies():
    ...
```

### 2. Template Response Pattern
**Before:**
```python
return templates.TemplateResponse(
    "some_template.html",
    {
        "request": request,
        "csrf_token": request.cookies.get("csrf_token", ""),
        # ... other context
    }
)
```

**After (create helper):**
```python
def render_template(request: Request, template: str, **context):
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "csrf_token": request.cookies.get("csrf_token", ""),
            **context
        }
    )

# Usage:
return render_template(request, "some_template.html", strategies=strategies)
```

### 3. CSRF Validation Pattern
**Before (repeated 6 times):**
```python
_verify_csrf_token(request, csrf_token)
```

**After (create decorator):**
```python
from functools import wraps

def require_csrf(func):
    @wraps(func)
    async def wrapper(request: Request, csrf_token: str = Form(...), *args, **kwargs):
        _verify_csrf_token(request, csrf_token)
        return await func(request, *args, **kwargs)
    return wrapper

# Usage:
@app.post("/ui/login")
@require_csrf
async def login(request: Request, username: str = Form(...), ...):
    # CSRF already validated
    ...
```

## Example Refactored Module: api_routes.py

```python
\"\"\"API routes for LLM Trading System.\"\"\"

from fastapi import APIRouter, HTTPException, Request
from llm_trading_system.api.services.validation import sanitize_error_message
from llm_trading_system.strategies import storage

# Create router
router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    \"\"\"Health check endpoint.

    Returns:
        Status indicating the service is healthy
    \"\"\"
    return {"status": "ok"}


@router.get("/strategies")
async def list_strategies() -> list[str]:
    \"\"\"List all available strategies.

    Returns:
        List of strategy names

    Raises:
        HTTPException: If strategy listing fails
    \"\"\"
    try:
        return storage.list_configs()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list strategies: {sanitize_error_message(e)}"
        )


# ... more routes ...
```

## Example Refactored server.py

```python
\"\"\"FastAPI server for the LLM Trading System.\"\"\"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# Import route modules
from llm_trading_system.api import api_routes, ui_routes, ws_routes

# Create app
app = FastAPI(
    title="LLM Trading System API",
    version="0.1.0",
    description="HTTP JSON API for backtesting and strategy management",
)

# ============================================================================
# Middleware Configuration
# ============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security Headers
@app.middleware("http")
async def security_headers_middleware(request, call_next):
    # ... (keep as is)
    pass

# Session Management
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "..."),
    session_cookie="trading_session",
    max_age=86400,
    same_site="strict",
    https_only=os.getenv("ENV", "").lower() == "production",
)

# CSRF Middleware
@app.middleware("http")
async def csrf_middleware(request, call_next):
    # ... (keep as is)
    pass

# ============================================================================
# Register Route Modules
# ============================================================================

# API routes
app.include_router(api_routes.router, tags=["API"])

# UI routes
app.include_router(ui_routes.router, tags=["UI"])

# WebSocket routes
app.include_router(ws_routes.router, tags=["WebSocket"])

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
```

## Benefits of This Refactoring

1. **Maintainability**: Each module has a clear responsibility
2. **Testability**: Routes can be tested independently
3. **Readability**: ~300 lines per module vs 2210 lines
4. **Reusability**: Services can be used across routes
5. **Team Collaboration**: Different devs can work on different modules

## Migration Checklist

- [x] Create `services/` directory
- [x] Create `services/validation.py`
- [x] Create refactoring guide
- [ ] Create `api_routes.py` with APIRouter
- [ ] Create `ui_routes.py` with APIRouter
- [ ] Create `ws_routes.py` with APIRouter
- [ ] Update `server.py` to use `include_router()`
- [ ] Test all endpoints maintain same behavior
- [ ] Remove old code from `server.py`
- [ ] Update tests to import from new modules

## Testing Strategy

1. **Before refactoring**: Run all existing tests to establish baseline
2. **After creating each module**: Test that module's routes
3. **After updating server.py**: Run full test suite
4. **Verify external behavior unchanged**: All endpoints respond identically

## Next Steps

1. Create `api_routes.py` and migrate API endpoints
2. Create `ui_routes.py` and migrate UI endpoints
3. Create `ws_routes.py` and migrate WebSocket endpoint
4. Slim down `server.py` to just configuration
5. Run test suite to verify behavior preserved
6. Document any API changes (there should be none)
