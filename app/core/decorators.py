import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar, cast

from loguru import logger

from app.core.errors import InvalidCursorError, TrueRAGError

P = ParamSpec("P")
R = TypeVar("R")
AsyncFn = Callable[P, Awaitable[R]]


def service_method(operation: str) -> Callable[[AsyncFn[P, R]], AsyncFn[P, R]]:
    """Decorate async service methods with consistent logging and error translation."""

    def decorator(fn: AsyncFn[P, R]) -> AsyncFn[P, R]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound_logger = logger.bind(operation=operation)
            try:
                result = await fn(*args, **kwargs)
                bound_logger.debug(f"{operation}_ok")
                return result
            except TrueRAGError as exc:
                bound_logger.warning(
                    f"{operation}_truerag_error",
                    extra={"extra_data": {"error_code": exc.code.value if hasattr(exc, 'code') else None, "error": str(exc)}},
                )
                raise
            except ValueError as exc:
                bound_logger.warning(f"{operation}_invalid_cursor | {exc}")
                raise InvalidCursorError(str(exc)) from exc
            except Exception as exc:
                bound_logger.exception(f"{operation}_unhandled | {exc}")
                raise

        return cast(AsyncFn[P, R], wrapper)

    return decorator
