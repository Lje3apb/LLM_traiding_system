# TODO: Implement CSRF Protection

**Priority**: HIGH
**Status**: ⚠️ NOT IMPLEMENTED
**Impact**: Security vulnerability - all POST forms are vulnerable to Cross-Site Request Forgery attacks

---

## Problem

All POST forms in the application lack CSRF protection, making them vulnerable to CSRF attacks where malicious sites can submit forms on behalf of authenticated users.

### Affected Forms

1. `/ui/strategies/{name}/backtest` (backtest_form.html)
2. `/ui/settings` (settings.html)
3. `/ui/strategies/{name}/save` (strategy_form.html)
4. `/ui/strategies/{name}/delete` (index.html)

---

## Solution Options

### Option 1: FastAPI CSRF Middleware (Recommended)

**Install Package:**
```bash
pip install fastapi-csrf-protect
```

**Implementation:**

```python
# In server.py

from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError
from pydantic import BaseModel

# CSRF configuration
class CsrfSettings(BaseModel):
    secret_key: str = "your-secret-key-here"  # CHANGE THIS!
    cookie_samesite: str = "lax"
    cookie_secure: bool = False  # Set to True in production with HTTPS

@CsrfProtect.load_config
def get_csrf_config():
    return CsrfSettings()

# Add exception handler
@app.exception_handler(CsrfProtectError)
def csrf_protect_exception_handler(request: Request, exc: CsrfProtectError):
    return JSONResponse(
        status_code=403,
        content={"detail": "CSRF token validation failed"}
    )

# In each POST endpoint, add:
@app.post("/ui/settings")
async def save_settings(
    request: Request,
    csrf_protect: CsrfProtect = Depends(),
    # ... other parameters
):
    await csrf_protect.validate_csrf(request)
    # ... rest of function

# In templates, add CSRF input:
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
```

**Template Changes Required:**
```html
<!-- In all POST forms, add hidden input -->
<form method="POST" action="...">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <!-- ... rest of form -->
</form>
```

**Pass csrf_token to templates:**
```python
# Add csrf_token function to template context
from fastapi_csrf_protect import generate_csrf

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals['csrf_token'] = lambda: generate_csrf()
```

---

### Option 2: Starlette CSRF Middleware

**Implementation:**

```python
# In server.py
from starlette.middleware.csrf import CSRFMiddleware

# Add middleware BEFORE app.mount() calls
app.add_middleware(
    CSRFMiddleware,
    secret="your-secret-key-here",  # CHANGE THIS!
    required_urls=["/ui/**"],  # Protect UI routes
)
```

**Pros:**
- Built into Starlette (no extra dependency)
- Simple configuration

**Cons:**
- Requires double-submit cookie pattern
- May require more template changes

---

### Option 3: Session-based CSRF (Most Secure)

**Requires:**
- Session management middleware (e.g., `fastapi-sessions`)
- Database or Redis for session storage

**Implementation:**
- Store CSRF tokens in secure server-side sessions
- Validate token on each POST request
- Most secure but adds complexity

---

## Implementation Checklist

### Backend (server.py)

- [ ] Choose CSRF protection option (Option 1 recommended)
- [ ] Install required packages
- [ ] Add CSRF middleware/protection
- [ ] Generate and store secret key securely (env variable)
- [ ] Add CSRF validation to all POST endpoints:
  - [ ] `/ui/strategies/{name}/backtest`
  - [ ] `/ui/settings`
  - [ ] `/ui/strategies/{name}/save`
  - [ ] `/ui/strategies/{name}/delete`
- [ ] Add exception handler for CSRF errors
- [ ] Make csrf_token available in template context

### Frontend (templates)

- [ ] Add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` to:
  - [ ] `backtest_form.html` (line ~12)
  - [ ] `settings.html` (line ~18)
  - [ ] `strategy_form.html` (line ~11)
  - [ ] `index.html` delete form (line ~212)

### Testing

- [ ] Test all forms submit successfully with CSRF tokens
- [ ] Test form submission fails without CSRF token
- [ ] Test form submission fails with invalid CSRF token
- [ ] Test form submission fails with expired CSRF token
- [ ] Test CSRF tokens are regenerated after use (if using single-use tokens)

### Security Considerations

- [ ] Use strong random secret key (32+ bytes)
- [ ] Store secret key in environment variable (not in code)
- [ ] Use HTTPS in production (cookie_secure=True)
- [ ] Set appropriate cookie SameSite policy (lax or strict)
- [ ] Consider token expiration time
- [ ] Log CSRF validation failures for monitoring

---

## Testing Commands

```bash
# Test valid form submission
curl -X POST http://localhost:8000/ui/settings \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "csrf_token=valid_token&..."

# Test missing CSRF token (should fail)
curl -X POST http://localhost:8000/ui/settings \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "field1=value1&..."
```

---

## References

- FastAPI CSRF Protect: https://github.com/aekasitt/fastapi-csrf-protect
- OWASP CSRF Prevention: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- Starlette CSRF: https://www.starlette.io/middleware/#csrfmiddleware

---

## Estimated Time

- **Basic Implementation**: 2-4 hours
- **Testing**: 1-2 hours
- **Total**: 3-6 hours

---

## Notes

- This is a **HIGH PRIORITY** security issue
- Should be implemented before deploying to production
- Consider implementing as part of next sprint
- May require testing with real browsers (not just curl)
- Should be combined with other security headers (CSP, X-Frame-Options, etc.)
