"""Retry policies with exponential backoff for LLM API calls."""

import time
import asyncio
from typing import TypeVar, Callable, Any
from functools import wraps

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
            last_exception = None
            for attempt in range(self.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < self.max_retries:
                        delay = min(
                            self.base_delay * (self.exponential_base**attempt),
                            self.max_delay,
                        )
                        time.sleep(delay)
                    else:
                        break
            raise last_exception  # type: ignore

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
            last_exception = None
            for attempt in range(self.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < self.max_retries:
                        delay = min(
                            self.base_delay * (self.exponential_base**attempt),
                            self.max_delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        break
            raise last_exception  # type: ignore

        return wrapper
