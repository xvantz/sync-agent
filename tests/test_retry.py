"""Tests for retry.py — exponential backoff and AsyncRetryClient."""

from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
import pytest

from sync_agent.retry import (
    AsyncRetryClient,
    exponential_backoff,
    is_retryable_error,
    retry,
)


class TestExponentialBackoff:
    def test_increases_with_attempts(self) -> None:
        delays = [exponential_backoff(i, jitter=False) for i in range(5)]
        assert delays[0] == 1.0
        assert delays[1] >= 2.0
        assert delays[2] >= 4.0
        assert delays[3] >= 8.0
        assert delays[4] >= 16.0

    def test_capped_at_max(self) -> None:
        delay = exponential_backoff(10, base_delay=1.0, max_delay=30.0, jitter=False)
        assert delay == 30.0

    def test_jitter_adds_variation(self) -> None:
        delays = [exponential_backoff(2, jitter=True) for _ in range(50)]
        # Should not all be the same value
        assert len(set(delays)) > 1


class TestIsRetryableError:
    def test_timeout_is_retryable(self) -> None:
        assert is_retryable_error(httpx.TimeoutException("timeout")) is True

    def test_network_error_is_retryable(self) -> None:
        assert is_retryable_error(httpx.NetworkError("network")) is True

    def test_429_is_retryable(self) -> None:
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(429, request=request)
        assert is_retryable_error(
            httpx.HTTPStatusError("too many", request=request, response=response)
        ) is True

    def test_500_is_retryable(self) -> None:
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request)
        assert is_retryable_error(
            httpx.HTTPStatusError("error", request=request, response=response)
        ) is True

    def test_404_is_not_retryable(self) -> None:
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(404, request=request)
        assert is_retryable_error(
            httpx.HTTPStatusError("not found", request=request, response=response)
        ) is False

    def test_403_is_not_retryable(self) -> None:
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(403, request=request)
        assert is_retryable_error(
            httpx.HTTPStatusError("forbidden", request=request, response=response)
        ) is False


class TestRetryDecorator:
    def test_success_on_first_try(self) -> None:
        fn = Mock(return_value="ok")

        @retry(max_attempts=3)
        def wrapped() -> str:
            return fn()

        result = wrapped()
        assert result == "ok"
        assert fn.call_count == 1

    def test_retries_on_failure_then_succeeds(self) -> None:
        fn = Mock(side_effect=[httpx.TimeoutException("timeout"), "ok"])

        @retry(max_attempts=3, base_delay=0.01)
        def wrapped() -> str:
            return fn()

        result = wrapped()
        assert result == "ok"
        assert fn.call_count == 2

    def test_raises_after_all_retries(self) -> None:
        fn = Mock(side_effect=httpx.TimeoutException("timeout"))

        @retry(max_attempts=3, base_delay=0.01)
        def wrapped() -> str:
            return fn()

        with pytest.raises(httpx.TimeoutException):
            wrapped()
        assert fn.call_count == 3

    def test_non_retryable_error_raises_immediately(self) -> None:
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(403, request=request)
        fn = Mock(
            side_effect=httpx.HTTPStatusError(
                "forbidden", request=request, response=response
            )
        )

        @retry(max_attempts=3, base_delay=0.01)
        def wrapped() -> str:
            return fn()

        with pytest.raises(httpx.HTTPStatusError):
            wrapped()
        assert fn.call_count == 1


class TestAsyncRetryClient:
    def test_get_retries_on_503(self) -> None:
        client = AsyncRetryClient(
            "http://localhost:2000", "token", max_attempts=3, base_delay=0.01
        )

        # Mock: first two return 503, third succeeds
        responses = [
            Mock(status_code=503, headers={"content-type": "application/json"}, json=lambda: {}),
            Mock(status_code=503, headers={"content-type": "application/json"}, json=lambda: {}),
            Mock(
                status_code=200,
                headers={"content-type": "application/json"},
                json=lambda: {"status": "ok"},
            ),
        ]
        client._client.request = Mock(side_effect=responses)

        result = client.get("/api/v1/user/repos")
        assert result == {"status": "ok"}
        assert client._client.request.call_count == 3

    def test_get_retries_on_timeout(self) -> None:
        client = AsyncRetryClient(
            "http://localhost:2000", "token", max_attempts=2, base_delay=0.01
        )

        responses = [
            httpx.TimeoutException("timeout"),
            Mock(
                status_code=200,
                headers={"content-type": "application/json"},
                json=lambda: {"ok": True},
            ),
        ]
        client._client.request = Mock(side_effect=responses)

        result = client.get("/api/v1/user/repos")
        assert result == {"ok": True}
        assert client._client.request.call_count == 2

    def test_raises_on_404_no_retry(self) -> None:
        client = AsyncRetryClient(
            "http://localhost:2000", "token", max_attempts=3, base_delay=0.01
        )

        request = httpx.Request("GET", "http://localhost:2000/test")
        response = httpx.Response(404, request=request)
        client._client.request = Mock(
            side_effect=httpx.HTTPStatusError(
                "not found", request=request, response=response
            )
        )

        with pytest.raises(httpx.HTTPStatusError):
            client.get("/test")
        assert client._client.request.call_count == 1

    def test_close(self) -> None:
        client = AsyncRetryClient(
            "http://localhost:2000", "token", max_attempts=3, base_delay=0.01
        )
        client._client.close = Mock()
        client.close()
        client._client.close.assert_called_once()
