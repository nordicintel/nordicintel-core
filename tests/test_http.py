import httpx
import pytest

from nordicintel_core.errors import UpstreamResponseError
from nordicintel_core.http import HttpClient


class Clock:
    def __init__(self) -> None:
        self.value = 0.0
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.value += delay


@pytest.mark.asyncio
async def test_retry_safe_request_honors_retry_after() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"ok": True})

    clock = Clock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = HttpClient(raw, clock=clock, sleep=clock.sleep, random_value=lambda: 1.0)
        response = await client.request("POST", "https://example.test/data", retry_safe=True)

    assert response.status_code == 200
    assert attempts == 2
    assert clock.delays == [2.0]


@pytest.mark.asyncio
async def test_unsafe_request_is_not_retried_or_leaked() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="secret response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = HttpClient(raw)
        with pytest.raises(UpstreamResponseError) as caught:
            await client.request(
                "POST",
                "https://user:password@example.test/data?token=secret",
                content="secret body",
            )

    assert caught.value.status_code == 503
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_minimum_interval_uses_injected_clock() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    clock = Clock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = HttpClient(raw, minimum_interval_seconds=1, clock=clock, sleep=clock.sleep)
        await client.request("GET", "https://example.test/one")
        await client.request("GET", "https://example.test/two")

    assert clock.delays == [1.0]
