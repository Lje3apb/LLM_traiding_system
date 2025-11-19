# Server.py Integration Example

## How to Integrate api_routes Module

This document shows how to integrate the refactored `api_routes.py` module into the main `server.py` file.

## Current Status

✅ **Completed:**
- `services/validation.py` - Validation helper functions
- `api_routes.py` - Demonstration API routes module with 10 endpoints

🔨 **In Progress:**
- Full migration of all API routes
- UI routes module
- WebSocket routes module

## Integration Steps

### Step 1: Import the Router

Add this import to `server.py`:

```python
from llm_trading_system.api import api_routes
```

### Step 2: Register the Router

After middleware configuration, add:

```python
# ============================================================================
# Register API Routes
# ============================================================================

# Include API routes from separate module
app.include_router(
    api_routes.router,
    tags=["API"],
)

# Share the rate limiter instance
api_routes.limiter = limiter
```

### Step 3: Remove Duplicate Routes (Optional)

Once verified working, you can remove the duplicate route definitions from `server.py`:

- `/health`
- `/strategies` (GET)
- `/strategies/{name}` (GET, POST, DELETE)
- `/backtest` (POST)
- `/api/live/sessions` (GET)
- `/api/live/sessions/{session_id}` (GET)

**IMPORTANT:** Test thoroughly before removing old routes!

## Complete Integration Example

Here's a minimal `server.py` showing the integration:

```python
\"\"\"FastAPI server for the LLM Trading System.\"\"\"

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

# Import route modules (NEW!)
from llm_trading_system.api import api_routes

# Setup logger
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="LLM Trading System API",
    version="0.1.0",
    description="HTTP JSON API for backtesting and strategy management",
)

# ============================================================================
# Middleware Configuration (unchanged)
# ============================================================================

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
allowed_origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security Headers
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    # ... (unchanged)
    response = await call_next(request)
    # Add security headers...
    return response

# Session Management
SESSION_SECRET_KEY = os.getenv(
    "SESSION_SECRET_KEY",
    "default-dev-secret-key-change-in-production-12345678901234567890"
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="trading_session",
    max_age=86400,
    same_site="strict",
    https_only=os.getenv("ENV", "").lower() == "production",
)

# ============================================================================
# Rate Limiting (unchanged)
# ============================================================================

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    config_filename=os.devnull,
    default_limits=["1000/hour"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================================
# Register Route Modules (NEW!)
# ============================================================================

# Include API routes from separate module
app.include_router(
    api_routes.router,
    tags=["API"],
)

# Share the rate limiter instance with api_routes
api_routes.limiter = limiter

# ============================================================================
# UI Routes (kept in server.py for now, will be migrated later)
# ============================================================================

# ... all UI routes stay here for now ...

# ============================================================================
# WebSocket Routes (kept in server.py for now, will be migrated later)
# ============================================================================

# ... WebSocket route stays here for now ...

# ============================================================================
# Static Files & Templates (unchanged)
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
```

## Testing the Integration

### 1. Test API Endpoints

```bash
# Test health check
curl http://localhost:8000/health

# Test list strategies
curl http://localhost:8000/strategies

# Test get strategy
curl http://localhost:8000/strategies/my_strategy

# Test create strategy
curl -X POST http://localhost:8000/strategies/new_strategy \\
  -H "Content-Type: application/json" \\
  -d '{"symbol": "BTCUSDT", "timeframe": "1h"}'
```

### 2. Verify Rate Limiting

```bash
# Send 100 requests rapidly - should get rate limited
for i in {1..100}; do
  curl http://localhost:8000/health
done
```

### 3. Check Logs

The new module uses the same logging infrastructure:

```python
import logging
logger = logging.getLogger(__name__)
logger.info("API route accessed")
```

## Rollback Plan

If issues occur, rollback is simple:

1. Comment out the `app.include_router(api_routes.router)` line
2. Restart the server
3. Old routes in `server.py` will continue working

## Next Steps

After verifying `api_routes.py` works:

1. Migrate remaining API routes to `api_routes.py`
2. Create `ui_routes.py` for UI endpoints
3. Create `ws_routes.py` for WebSocket endpoint
4. Remove old route definitions from `server.py`
5. Update tests to import from new modules

## Benefits Already Achieved

Even with partial migration:

✅ **Validation logic centralized** - `services/validation.py` can be used across all modules
✅ **API routes documented** - Clear docstrings for all endpoints
✅ **Pattern established** - Easy to follow for remaining routes
✅ **Testability improved** - `api_routes.router` can be tested independently
✅ **Code organization** - Clear separation of concerns

## File Structure After Migration

```
llm_trading_system/api/
├── server.py                    # Main app (300 lines)
│   ├── App creation
│   ├── Middleware configuration
│   ├── Route registration
│   └── Static file mounting
│
├── api_routes.py                # API endpoints (500 lines) ✅ CREATED
│   ├── Health check
│   ├── Strategy CRUD
│   ├── Backtesting
│   └── Live trading sessions
│
├── ui_routes.py                 # UI endpoints (600 lines) 🔨 TODO
│   ├── Authentication pages
│   ├── Strategy management UI
│   ├── Backtesting UI
│   └── Settings UI
│
├── ws_routes.py                 # WebSocket (100 lines) 🔨 TODO
│   └── Real-time session updates
│
├── services/                    # Business logic ✅ CREATED
│   ├── __init__.py
│   └── validation.py           # Validation helpers
│
├── auth.py                      # Authentication (existing)
├── templates/                   # Jinja2 templates (existing)
└── static/                      # Static files (existing)
```

## Code Quality Improvements

### Before Refactoring
- Single file: 2210 lines
- Mixed concerns: UI, API, WebSocket, validation
- Duplicated error handling patterns
- Hard to test individual routes

### After Refactoring
- Multiple focused modules: ~300 lines each
- Clear separation of concerns
- Reusable service functions
- Individual routes easily testable
- Better documentation with docstrings
- Reduced code duplication

## Performance Impact

**None.** The refactoring is purely organizational:
- Same FastAPI routing mechanism
- Same middleware execution order
- Same business logic
- Same external API behavior

The only difference is code organization for maintainability.
