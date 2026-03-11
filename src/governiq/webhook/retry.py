"""Reusable async retry utility with exponential backoff and jitter.

All webhook retry sites delegate to this instead of duplicating logic.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable_statuses: tuple[int, ...] = (401, 502, 503, 504),
    on_retry: Callable[[int, float, Exception | int], None] | None = None,
    **kwargs: Any,
) -> T:
    """Call *func* with retries on transient HTTP errors.

    Args:
        func: Async callable to invoke.
        max_retries: Maximum retry attempts (total calls = max_retries + 1).
        base_delay: Initial delay in seconds.
        max_delay: Cap on computed delay.
        jitter: Add random jitter to prevent thundering herd.
        retryable_statuses: HTTP status codes that trigger a retry.
        on_retry: Optional callback(attempt, delay, cause) for logging.

    Raises the last exception if all attempts fail.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code not in retryable_statuses:
                raise
            if attempt >= max_retries:
                raise
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise

        # Compute delay with exponential backoff + optional jitter
        delay = min(base_delay * (2 ** attempt), max_delay)
        if jitter:
            delay += random.uniform(0, 0.5 * delay)

        if on_retry:
            cause = (
                last_exc.response.status_code
                if isinstance(last_exc, httpx.HTTPStatusError)
                else last_exc
            )
            on_retry(attempt + 1, delay, cause)

        await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    assert last_exc is not None  # noqa: S101
    raise last_exc
