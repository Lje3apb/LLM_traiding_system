"""Authentication and authorization module for LLM Trading System.

This module provides:
- User management with password hashing
- Session-based authentication
- FastAPI dependencies for protecting endpoints
- WebSocket token generation and validation
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class User:
    """User model for authentication."""

    user_id: str
    username: str
    hashed_password: str
    email: str
    is_active: bool = True
    is_admin: bool = False


# ============================================================================
# User Database (In-Memory)
# ============================================================================
# NOTE: In production, replace this with a proper database (PostgreSQL, SQLite, etc.)
# For now, we use a simple in-memory dictionary for demonstration

_USERS_DB: dict[str, User] = {
    "admin": User(
        user_id="user_001",
        username="admin",
        # Default password: "admin123" (CHANGE THIS IN PRODUCTION!)
        hashed_password="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5UpKFSTwVi7.m",
        email="admin@trading.local",
        is_active=True,
        is_admin=True,
    ),
    "trader": User(
        user_id="user_002",
        username="trader",
        # Default password: "trader123" (CHANGE THIS IN PRODUCTION!)
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p0eN3Fd3E7bK/1Cj8XuVCqvi",
        email="trader@trading.local",
        is_active=True,
        is_admin=False,
    ),
}


# ============================================================================
# Password Utilities
# ============================================================================


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash.

    Args:
        plain_password: The plaintext password
        hashed_password: The hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password for storage.

    Args:
        password: The plaintext password

    Returns:
        The hashed password
    """
    return pwd_context.hash(password)


# ============================================================================
# User Management
# ============================================================================


def get_user(username: str) -> Optional[User]:
    """Get a user by username.

    Args:
        username: The username to look up

    Returns:
        User object if found, None otherwise
    """
    return _USERS_DB.get(username)


def authenticate_user(username: str, password: str) -> Optional[User]:
    """Authenticate a user by username and password.

    Args:
        username: The username
        password: The plaintext password

    Returns:
        User object if authentication succeeds, None otherwise
    """
    user = get_user(username)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_user(username: str, password: str, email: str, is_admin: bool = False) -> User:
    """Create a new user (for future use).

    Args:
        username: The username
        password: The plaintext password (will be hashed)
        email: The user's email
        is_admin: Whether user has admin privileges

    Returns:
        The created User object

    Raises:
        ValueError: If username already exists
    """
    if username in _USERS_DB:
        raise ValueError(f"Username '{username}' already exists")

    user_id = f"user_{secrets.token_hex(8)}"
    user = User(
        user_id=user_id,
        username=username,
        hashed_password=get_password_hash(password),
        email=email,
        is_active=True,
        is_admin=is_admin,
    )
    _USERS_DB[username] = user
    return user


# ============================================================================
# Session Management
# ============================================================================


def get_current_user_id(request: Request) -> Optional[str]:
    """Get the current user ID from session.

    Args:
        request: FastAPI Request object

    Returns:
        User ID if logged in, None otherwise
    """
    return request.session.get("user_id")


def get_current_user(request: Request) -> Optional[User]:
    """Get the current user from session.

    Args:
        request: FastAPI Request object

    Returns:
        User object if logged in, None otherwise
    """
    user_id = get_current_user_id(request)
    if not user_id:
        return None

    # Find user by user_id
    for user in _USERS_DB.values():
        if user.user_id == user_id:
            return user

    return None


# ============================================================================
# FastAPI Dependencies for Authentication
# ============================================================================


async def require_auth(request: Request) -> User:
    """FastAPI dependency that requires authentication.

    For UI endpoints: Raises 401 which will be caught by exception handler and redirected to login.
    For API endpoints: Raises 401 Unauthorized.

    Args:
        request: FastAPI Request object

    Returns:
        The authenticated User object

    Raises:
        HTTPException: 401/403 if not authenticated or inactive
    """
    user = get_current_user(request)

    if not user:
        # Raise 401 - exception handler will redirect UI requests to login
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="User account is disabled"
        )

    return user


async def require_admin(request: Request) -> User:
    """FastAPI dependency that requires admin privileges.

    Args:
        request: FastAPI Request object

    Returns:
        The authenticated admin User object

    Raises:
        HTTPException: 401/403 if not authenticated or not admin
    """
    user = await require_auth(request)

    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required"
        )

    return user


async def optional_auth(request: Request) -> Optional[User]:
    """FastAPI dependency for optional authentication.

    Returns user if logged in, None otherwise (no exception raised).

    Args:
        request: FastAPI Request object

    Returns:
        User object if logged in, None otherwise
    """
    return get_current_user(request)


# ============================================================================
# WebSocket Token Generation and Validation
# ============================================================================

# WebSocket token serializer (uses same secret as SessionMiddleware)
# Tokens are time-limited and signed to prevent tampering
_WS_SECRET_KEY = os.getenv(
    "SESSION_SECRET_KEY",
    "default-dev-secret-key-change-in-production-12345678901234567890"
)
_ws_token_serializer = URLSafeTimedSerializer(_WS_SECRET_KEY, salt="websocket-auth")


def generate_ws_token(user_id: str) -> str:
    """Generate a signed WebSocket authentication token for a user.

    The token contains the user_id and is time-limited for security.
    Tokens expire after 1 hour.

    Args:
        user_id: User ID to encode in the token

    Returns:
        Signed token string that can be validated with validate_ws_token()

    Example:
        >>> token = generate_ws_token("user_001")
        >>> # Client connects with: ws://host/ws/live/session_id?token={token}
    """
    return _ws_token_serializer.dumps({"user_id": user_id})


def validate_ws_token(token: str) -> Optional[str]:
    """Validate a WebSocket authentication token and extract user_id.

    This function verifies that:
    1. The token signature is valid (not tampered with)
    2. The token has not expired (max_age: 1 hour)
    3. The user_id in the token corresponds to an active user

    Args:
        token: Token string from WebSocket query parameters

    Returns:
        User ID if token is valid, None otherwise

    Security Notes:
        - Tokens expire after 3600 seconds (1 hour)
        - Invalid signatures are rejected
        - Expired tokens are rejected
        - Tokens for inactive users are rejected

    Example:
        >>> user_id = validate_ws_token(token)
        >>> if user_id:
        ...     # Token valid, allow WebSocket connection
        ... else:
        ...     # Token invalid, reject connection
    """
    if not token:
        return None

    try:
        # Verify signature and expiration (max_age: 1 hour)
        data = _ws_token_serializer.loads(token, max_age=3600)
        user_id = data.get("user_id")

        if not user_id:
            return None

        # Verify user exists and is active
        for user in _USERS_DB.values():
            if user.user_id == user_id and user.is_active:
                return user_id

        return None

    except SignatureExpired:
        # Token expired
        return None
    except Exception:
        # Invalid token format or signature
        return None
