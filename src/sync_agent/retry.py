"""Retry utility with exponential backoff and jitter for HTTP calls."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# HTTP status codes that are safe to retry
RETRYABLE_STATUSES = {
    429,  # Too Many Requests (rate limit)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}


def exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> float:
    """Calculate delay with exponential backoff and optional jitter.

    Args:
        attempt: Current attempt number (0-indexed).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay in seconds.
        jitter: Whether to add random jitter.

    Returns:
        Delay in seconds to wait before next attempt.
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        delay *= 0.5 + random.random() * 0.5  # 50-100% of delay
    return delay


def is_retryable_error(exc: Exception) -> bool:
    """Check if an exception is safe to retry."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUSES
    if isinstance(exc, httpx.TransportError):
        return True
    return False


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> Callable[[F], F]:
    """Decorator for retrying functions that make HTTP calls.

    Args:
        max_attempts: Maximum number of attempts (including first).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay in seconds.
        jitter: Whether to add random jitter.

    Usage:
        @retry(max_attempts=3)
        def fetch_data():
            return client.get("/api/data")
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if not is_retryable_error(exc):
                        raise
                    if attempt < max_attempts - 1:
                        delay = exponential_backoff(
                            attempt, base_delay, max_delay, jitter
                        )
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt + 1,
                            max_attempts,
                            func.__name__,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d retries failed for %s: %s",
                            max_attempts,
                            func.__name__,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


class AsyncRetryClient:
    """HTTPX client wrapper with automatic retry logic.

    Usage:
        client = AsyncRetryClient(base_url="...", token="...")
        resp = client.get("/api/v1/user/repos")
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ):
        headers = {"Content-Type": "application/json"}
        if token:
            # Support both 'token' and 'Bearer' auth
            if token.startswith("ghp_") or token.startswith("github_pat_"):
                headers["Authorization"] = f"Bearer {token}"
            else:
                headers["Authorization"] = f"token {token}"
        headers["User-Agent"] = "sync-agent/0.1"

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._token = token
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay

    def _do_request(self, method: str, path: str, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                resp = self._client.request(method, path, **kwargs)
                if resp.status_code in RETRYABLE_STATUSES:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                # Return JSON if present, else raw content
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return resp.json()
                return resp.content
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code not in RETRYABLE_STATUSES:
                    raise
                if attempt < self._max_attempts - 1:
                    delay = exponential_backoff(
                        attempt, self._base_delay, self._max_delay
                    )
                    logger.warning(
                        "HTTP %d on %s %s, retry %d/%d in %.1fs",
                        exc.response.status_code,
                        method.upper(),
                        path,
                        attempt + 1,
                        self._max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < self._max_attempts - 1:
                    delay = exponential_backoff(
                        attempt, self._base_delay, self._max_delay
                    )
                    logger.warning(
                        "%s on %s %s, retry %d/%d in %.1fs",
                        type(exc).__name__,
                        method.upper(),
                        path,
                        attempt + 1,
                        self._max_attempts,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise

        raise last_exc  # type: ignore[misc]

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._do_request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._do_request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._do_request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()
