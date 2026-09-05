"""Injected asynchronous HTTP transport with bounded retry and rate limiting."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover - exercised by packaging smoke tests
    raise ImportError(
        "HTTP support requires the 'http' extra: pip install 'nordicintel-core[http]'"
    ) from exc

from nordicintel_core.errors import UpstreamResponseError, UpstreamTransportError

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounds for one explicitly retry-safe upstream operation."""

    max_attempts: int = 4
    max_elapsed_seconds: float = 120.0
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 15.0
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.max_elapsed_seconds < 0 or self.base_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be below base_delay_seconds")


class HttpClient:
    """A non-owning wrapper around an application-managed ``httpx.AsyncClient``."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        minimum_interval_seconds: float = 0.0,
        retry_policy: RetryPolicy | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        self._client = client
        self._minimum_interval = minimum_interval_seconds
        self._policy = retry_policy or RetryPolicy()
        self._clock = clock
        self._sleep = sleep
        self._random = random_value
        self._rate_lock = asyncio.Lock()
        self._last_started: float | None = None

    async def _rate_limit(self) -> None:
        async with self._rate_lock:
            now = self._clock()
            if self._last_started is not None:
                delay = self._minimum_interval - (now - self._last_started)
                if delay > 0:
                    await self._sleep(delay)
            self._last_started = self._clock()

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    try:
                        parsed = parsedate_to_datetime(retry_after)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=UTC)
                        return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        pass
        ceiling = min(
            self._policy.max_delay_seconds,
            self._policy.base_delay_seconds * (2 ** (attempt - 1)),
        )
        return ceiling * self._random()

    async def request(
        self,
        method: str,
        url: str,
        *,
        retry_safe: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a request and return only successful upstream responses.

        Cancellation is intentionally not caught. URLs, bodies, headers, and credentials are never
        copied into the raised exceptions.
        """
        started = self._clock()
        attempt = 0
        while True:
            attempt += 1
            await self._rate_limit()
            response: httpx.Response | None = None
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.is_success:
                    return response
                should_retry = response.status_code in self._policy.retry_statuses
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                should_retry = True
                if not retry_safe or not self._can_retry(attempt, started, 0.0):
                    raise UpstreamTransportError(
                        "Upstream request failed", code="upstream_transport"
                    ) from exc

            if not retry_safe or not should_retry:
                raise UpstreamResponseError(
                    "Upstream returned an unsuccessful response",
                    code="upstream_response",
                    status_code=response.status_code if response is not None else None,
                )

            delay = self._retry_delay(response, attempt)
            if not self._can_retry(attempt, started, delay):
                if response is None:
                    raise UpstreamTransportError(
                        "Upstream retry budget was exhausted", code="upstream_transport"
                    )
                raise UpstreamResponseError(
                    "Upstream retry budget was exhausted",
                    code="upstream_response",
                    status_code=response.status_code,
                )
            await self._sleep(delay)

    def _can_retry(self, attempt: int, started: float, delay: float) -> bool:
        return (
            attempt < self._policy.max_attempts
            and self._clock() - started + delay <= self._policy.max_elapsed_seconds
        )
