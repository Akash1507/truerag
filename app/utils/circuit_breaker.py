import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

from app.core.errors import CircuitOpenError

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 60,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._trial_in_progress = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        await self._before_call()
        try:
            result = await fn(*args, **kwargs)
        except CircuitOpenError:
            raise
        except Exception:
            await self._on_failure()
            raise
        await self._on_success()
        return result

    async def _before_call(self) -> None:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._opened_at is None:
                    self._opened_at = time.monotonic()
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.recovery_timeout_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._trial_in_progress = False
                else:
                    raise CircuitOpenError()

            if self._state == CircuitState.HALF_OPEN:
                if self._trial_in_progress:
                    raise CircuitOpenError()
                self._trial_in_progress = True

    async def _on_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None
            self._trial_in_progress = False

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._state == CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
            self._trial_in_progress = False
