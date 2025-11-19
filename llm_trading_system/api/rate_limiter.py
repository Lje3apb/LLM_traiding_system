"""Rate limiter singleton for the API.

This module provides a shared rate limiter instance that can be used
across all route modules without causing circular imports.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Create a single shared rate limiter instance
# Use os.devnull to prevent .env reading and avoid Windows encoding issues
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    config_filename=os.devnull,  # Prevents .env reading (cross-platform fix)
    default_limits=["1000/hour"],  # Global fallback
)
