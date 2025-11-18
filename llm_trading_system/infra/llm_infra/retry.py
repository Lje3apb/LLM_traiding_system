"""Retry policies with exponential backoff for LLM API calls."""

import logging
import time
import asyncio
from typing import TypeVar, Callable, Any, Optional
from functools import wraps
import requests

logger = logging.getLogger(__name__)
T = TypeVar("T")


class RetryPolicy:
    """Synchronous retry policy with exponential backoff."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ):
        """Initialize retry policy.

        Args:
            max_retries: Maximum number of retry attempts.
            base_delay: Initial delay in seconds.
            max_delay: Maximum delay in seconds.
            exponential_base: Base for exponential backoff calculation.
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to add retry logic to a function.

        Args:
            func: Function to wrap with retry logic.

        Returns:
            Wrapped function with retry behavior.
        """

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(self.max_retries + 1):
                try:
                    if attempt > 0:
                        logger.debug("Retry attempt %d/%d for %s", attempt, self.max_retries, func.__name__)
                    return func(*args, **kwargs)

                except (
                    requests.RequestException,  # Network errors (timeout, connection, HTTP)
                    TimeoutError,               # Timeout errors
                    ConnectionError,            # Connection errors
                    OSError,                    # Network-related OS errors
                ) as e:
                    last_exception = e
                    if attempt < self.max_retries:
                        delay = min(
                            self.base_delay * (self.exponential_base**attempt),
                            self.max_delay,
                        )
                        logger.warning(
                            "Attempt %d failed with %s: %s. Retrying in %.1fs...",
                            attempt + 1,
                            type(e).__name__,
                            str(e),
                            delay
                        )
                        time.sleep(delay)
                    else:
                        logger.error("All %d retry attempts failed for %s", self.max_retries + 1, func.__name__)

                except Exception as e:
                    # Don't retry on programming errors - fail fast
                    logger.error("Non-retryable error in %s: %s: %s", func.__name__, type(e).__name__, str(e))
                    raise

            # If we get here, all retries were exhausted
            if last_exception:
                raise last_exception

            # This should never happen
            raise RuntimeError("Retry loop exhausted without exception or return")

        return wrapper


class AsyncRetryPolicy:
    """Asynchronous retry policy with exponential backoff."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ):
        """Initialize async retry policy.

        Args:
            max_retries: Maximum number of retry attempts.
            base_delay: Initial delay in seconds.
            max_delay: Maximum delay in seconds.
            exponential_base: Base for exponential backoff calculation.
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to add async retry logic to a coroutine.

        Args:
            func: Async function to wrap with retry logic.

        Returns:
            Wrapped async function with retry behavior.
        """

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(self.max_retries + 1):
                try:
                    if attempt > 0:
                        logger.debug("Async retry attempt %d/%d for %s", attempt, self.max_retries, func.__name__)
                    return await func(*args, **kwargs)

                except (
                    requests.RequestException,  # Network errors (timeout, connection, HTTP)
                    TimeoutError,               # Timeout errors
                    ConnectionError,            # Connection errors
                    OSError,                    # Network-related OS errors
                ) as e:
                    last_exception = e
                    if attempt < self.max_retries:
                        delay = min(
                            self.base_delay * (self.exponential_base**attempt),
                            self.max_delay,
                        )
                        logger.warning(
                            "Async attempt %d failed with %s: %s. Retrying in %.1fs...",
                            attempt + 1,
                            type(e).__name__,
                            str(e),
                            delay
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("All %d async retry attempts failed for %s", self.max_retries + 1, func.__name__)

                except Exception as e:
                    # Don't retry on programming errors - fail fast
                    logger.error("Non-retryable async error in %s: %s: %s", func.__name__, type(e).__name__, str(e))
                    raise

            # If we get here, all retries were exhausted
            if last_exception:
                raise last_exception

            # This should never happen
            raise RuntimeError("Async retry loop exhausted without exception or return")

        return wrapper
