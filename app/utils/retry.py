import asyncio
import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

from app.utils.observability import get_logger

logger = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: Exception = RuntimeError("No attempts made")
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        sleep_s = backoff_factor ** (attempt - 1)
                        logger.warning(
                            "retry_attempt",
                            extra={
                                "operation": func.__name__,
                                "extra_data": {
                                    "attempt": attempt,
                                    "max_attempts": max_attempts,
                                    "sleep_s": sleep_s,
                                    "error": str(exc),
                                },
                            },
                        )
                        await asyncio.sleep(sleep_s)
            raise last_exc

        return wrapper

    return decorator
