"""WebSocket security utilities and validation."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import WebSocket
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ============================================================================
# Global State for Connection Tracking
# ============================================================================

# Track active connections per user
_active_connections: dict[str, set[WebSocket]] = defaultdict(set)

# Track message rates per user (for spam protection)
_message_timestamps: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

# Configuration
MAX_CONNECTIONS_PER_USER = int(os.getenv("WS_MAX_CONNECTIONS_PER_USER", "5"))
MAX_MESSAGES_PER_SECOND = int(os.getenv("WS_MAX_MESSAGES_PER_SECOND", "10"))
MAX_MESSAGES_PER_MINUTE = int(os.getenv("WS_MAX_MESSAGES_PER_MINUTE", "100"))

# Allowed origins for WebSocket connections
ALLOWED_ORIGINS = os.getenv(
    "WS_ALLOWED_ORIGINS",
    "http://localhost:8000,http://localhost:3000,http://127.0.0.1:8000"
).split(",")


# ============================================================================
# Pydantic Models for Message Validation
# ============================================================================


class WSMessageIn(BaseModel):
    """Incoming WebSocket message from client."""

    type: Literal["ping", "subscribe", "unsubscribe"] = Field(
        ...,
        description="Message type - only specific types allowed"
    )
    payload: dict = Field(
        default_factory=dict,
        description="Message payload"
    )


class WSMessageOut(BaseModel):
    """Outgoing WebSocket message to client."""

    type: Literal["pong", "state_update", "trade", "bar", "error"] = Field(
        ...,
        description="Message type"
    )
    payload: dict | None = Field(
        default=None,
        description="Message payload"
    )
    message: str | None = Field(
        default=None,
        description="Error message (for type=error)"
    )


# ============================================================================
# Origin Validation
# ============================================================================


def validate_origin(websocket: WebSocket) -> bool:
    """Validate WebSocket origin header.

    Args:
        websocket: WebSocket connection

    Returns:
        True if origin is allowed, False otherwise

    Example:
        >>> if not validate_origin(websocket):
        ...     await websocket.close(code=1008, reason="Origin not allowed")
        ...     return
    """
    origin = websocket.headers.get("origin")

    # If no origin header, reject (should always be present from browser)
    if not origin:
        logger.warning("WebSocket connection without Origin header")
        return False

    # Normalize origin (remove trailing slash)
    origin = origin.rstrip("/")

    # Check if origin is in allowed list
    allowed = [o.rstrip("/") for o in ALLOWED_ORIGINS if o.strip()]

    if origin not in allowed:
        logger.warning(f"WebSocket connection from unauthorized origin: {origin}")
        return False

    return True


# ============================================================================
# Connection Limits
# ============================================================================


def check_connection_limit(user_id: str, websocket: WebSocket) -> bool:
    """Check if user has exceeded connection limit.

    Args:
        user_id: User identifier
        websocket: WebSocket connection

    Returns:
        True if connection allowed, False if limit exceeded

    Example:
        >>> if not check_connection_limit(user_id, websocket):
        ...     await websocket.close(code=1008, reason="Too many connections")
        ...     return
    """
    current_count = len(_active_connections[user_id])

    if current_count >= MAX_CONNECTIONS_PER_USER:
        logger.warning(
            f"User {user_id} exceeded connection limit: "
            f"{current_count}/{MAX_CONNECTIONS_PER_USER}"
        )
        return False

    return True


def register_connection(user_id: str, websocket: WebSocket) -> None:
    """Register a new WebSocket connection for a user.

    Args:
        user_id: User identifier
        websocket: WebSocket connection
    """
    _active_connections[user_id].add(websocket)
    logger.info(
        f"WebSocket connected: user={user_id}, "
        f"total_connections={len(_active_connections[user_id])}"
    )


def unregister_connection(user_id: str, websocket: WebSocket) -> None:
    """Unregister a WebSocket connection for a user.

    Args:
        user_id: User identifier
        websocket: WebSocket connection
    """
    _active_connections[user_id].discard(websocket)

    # Clean up empty sets
    if not _active_connections[user_id]:
        del _active_connections[user_id]

    logger.info(
        f"WebSocket disconnected: user={user_id}, "
        f"remaining_connections={len(_active_connections.get(user_id, set()))}"
    )


# ============================================================================
# Rate Limiting
# ============================================================================


def check_message_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded message rate limit.

    Args:
        user_id: User identifier

    Returns:
        True if message allowed, False if rate limit exceeded

    Example:
        >>> if not check_message_rate_limit(user_id):
        ...     logger.warning(f"Rate limit exceeded for user {user_id}")
        ...     continue  # Skip message
    """
    now = time.time()
    timestamps = _message_timestamps[user_id]

    # Add current timestamp
    timestamps.append(now)

    # Check messages per second (last 1 second)
    recent_count = sum(1 for ts in timestamps if now - ts <= 1.0)
    if recent_count > MAX_MESSAGES_PER_SECOND:
        logger.warning(
            f"User {user_id} exceeded per-second rate limit: "
            f"{recent_count}/{MAX_MESSAGES_PER_SECOND}"
        )
        return False

    # Check messages per minute (last 60 seconds)
    minute_count = sum(1 for ts in timestamps if now - ts <= 60.0)
    if minute_count > MAX_MESSAGES_PER_MINUTE:
        logger.warning(
            f"User {user_id} exceeded per-minute rate limit: "
            f"{minute_count}/{MAX_MESSAGES_PER_MINUTE}"
        )
        return False

    return True


# ============================================================================
# Permission Checks
# ============================================================================


def check_session_permission(user_id: str, session_id: str, session_manager) -> bool:
    """Check if user has permission to access a session.

    This ensures users can only access their own trading sessions.

    Args:
        user_id: User identifier
        session_id: Session identifier
        session_manager: LiveSessionManager instance

    Returns:
        True if user has permission, False otherwise

    Example:
        >>> if not check_session_permission(user_id, session_id, manager):
        ...     await websocket.close(code=1008, reason="Access denied")
        ...     return
    """
    try:
        # Get session status
        status = session_manager.get_status(session_id)

        # Check if session has owner_id field
        # If not, allow access (backward compatibility)
        session_owner_id = status.get("owner_id")
        if session_owner_id is None:
            logger.warning(
                f"Session {session_id} has no owner_id - "
                "allowing access for backward compatibility"
            )
            return True

        # Check if user owns the session
        if session_owner_id != user_id:
            logger.warning(
                f"User {user_id} attempted to access session {session_id} "
                f"owned by {session_owner_id}"
            )
            return False

        return True

    except KeyError:
        # Session not found
        return False
    except Exception as e:
        logger.error(f"Error checking session permission: {e}")
        return False


# ============================================================================
# Message Validation
# ============================================================================


def validate_incoming_message(raw_message: str) -> WSMessageIn | None:
    """Validate and parse incoming WebSocket message.

    Args:
        raw_message: Raw message string from client

    Returns:
        Parsed message object, or None if invalid

    Example:
        >>> message = validate_incoming_message('{"type": "ping", "payload": {}}')
        >>> if message:
        ...     # Process message
        ... else:
        ...     # Invalid message, ignore
    """
    try:
        message = WSMessageIn.parse_raw(raw_message)
        return message
    except Exception as e:
        logger.warning(f"Invalid WebSocket message: {e}")
        return None
