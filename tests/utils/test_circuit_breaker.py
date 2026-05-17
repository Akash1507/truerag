import asyncio

import pytest

from app.core.errors import CircuitOpenError
from app.utils.circuit_breaker import CircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold_and_blocks_calls() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)

    async def _fail() -> str:
        raise RuntimeError("boom")

    async def _ok() -> str:
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    with pytest.raises(RuntimeError):
        await breaker.call(_fail)

    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.call(_ok)


@pytest.mark.asyncio
async def test_half_open_success_closes_circuit() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0)

    async def _fail() -> str:
        raise RuntimeError("boom")

    async def _ok() -> str:
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.call(_fail)

    result = await breaker.call(_ok)

    assert result == "ok"
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_reopens_and_resets_timer() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.01)

    async def _fail() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(_fail)

    opened_at_first = breaker._opened_at
    assert opened_at_first is not None

    await asyncio.sleep(0.02)
    with pytest.raises(RuntimeError):
        await breaker.call(_fail)

    opened_at_second = breaker._opened_at
    assert opened_at_second is not None
    assert opened_at_second > opened_at_first
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await breaker.call(_fail)
