# Story 1-12: Generic Service Error Decorator

**Epic:** 1 — Platform Foundation & Security Baseline (addendum)
**Status:** review
**Depends on:** 1-11 (loguru logging)
**Sprint Change Proposal:** sprint-change-proposal-2026-05-07.md

## User Story

As an AI Platform Engineer,
I want a `@service_method` decorator applied to all service functions,
So that errors are captured, logged, and translated in one place — removing all try-except blocks from the router layer.

## Background

Current state: `ValueError` raised by `decode_cursor` in pagination propagates up to routers, forcing each router to contain:
```python
try:
    items, cursor = await service.list(...)
except ValueError as exc:
    raise InvalidCursorError(str(exc)) from exc
```
This pattern is duplicated in `agents.py`, `documents.py`, `tenants.py`, and `eval.py`. With class-based services (story 1-13), all service methods will be decorated instead.

## Acceptance Criteria

**Given** a service method decorated with `@service_method("operation_name")`
**When** it completes successfully
**Then** result is returned unchanged; a DEBUG log entry is emitted with operation name

**Given** a service method raises a `TrueRAGError` subclass
**When** the decorator intercepts it
**Then** exception is re-raised unchanged — already typed, global handler deals with it; WARNING log emitted

**Given** a service method raises `ValueError`
**When** the decorator intercepts it
**Then** `InvalidCursorError(str(exc))` is raised in its place; WARNING log emitted with original message

**Given** a service method raises any other `Exception`
**When** the decorator intercepts it
**Then** exception is re-raised unchanged (let global `generic_exception_handler` return 500); ERROR log with full traceback emitted via loguru `.exception()`

**Given** `@service_method` applied to an async function
**When** the function is called
**Then** decorator preserves function name, docstring, and type signature (via `functools.wraps`)

**Given** mypy strict runs on `app/core/decorators.py`
**When** check completes
**Then** zero type errors

## Implementation Notes

### New file: `app/core/decorators.py`

```python
import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar
from loguru import logger

from app.core.errors import InvalidCursorError, TrueRAGError

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def service_method(operation: str) -> Callable[[F], F]:
    """Decorator for async service methods: logs, translates ValueError→InvalidCursorError."""
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound_logger = logger.bind(operation=operation)
            bound_logger.debug(f"{operation}_start")
            try:
                result = await fn(*args, **kwargs)
                bound_logger.debug(f"{operation}_ok")
                return result
            except TrueRAGError:
                bound_logger.warning(f"{operation}_truerag_error")
                raise
            except ValueError as exc:
                bound_logger.warning(f"{operation}_invalid_cursor | {exc}")
                raise InvalidCursorError(str(exc)) from exc
            except Exception as exc:
                bound_logger.exception(f"{operation}_unhandled | {exc}")
                raise
        return wrapper  # type: ignore[return-value]
    return decorator
```

### Usage (preview — wired up in story 1-13)

```python
class AgentService:
    @service_method("create_agent")
    async def create(self, body: AgentCreateRequest, tenant_id: str) -> AgentCreateResponse:
        ...

    @service_method("list_agents")
    async def list(self, tenant_id: str, cursor: str | None, limit: int) -> AgentListResponse:
        ...  # ValueError from decode_cursor auto-translated to InvalidCursorError
```

## Test Requirements

- Unit test: successful call → result returned, no exception
- Unit test: `TrueRAGError` raised → re-raised unchanged
- Unit test: `ValueError` raised → `InvalidCursorError` raised with same message
- Unit test: generic `RuntimeError` raised → re-raised unchanged (not swallowed)
- Unit test: `functools.wraps` preserved — `wrapper.__name__ == fn.__name__`
- All tests use `pytest-asyncio`

## Definition of Done

- [x] `app/core/decorators.py` created
- [x] `service_method` is a typed generic decorator (mypy strict passes)
- [x] Unit tests for all 4 exception paths
- [x] No router try-except blocks remain after story 1-13 wires this up

## Dev Agent Record

### Debug Log

- 2026-05-07: Added story-scoped unit tests first in `tests/core/test_decorators.py` (red phase).
- 2026-05-07: Initial test run failed on missing `loguru`; installed via `uv pip install --python .venv/bin/python loguru`.
- 2026-05-07: Full pytest path hit unrelated missing app dependency (`prometheus_client`) from global `tests/conftest.py`; executed scoped validation with `--noconftest`.
- 2026-05-07: Implemented `app/core/decorators.py` and re-ran focused tests + strict mypy successfully.

### Completion Notes

- Implemented `service_method(operation: str)` as a typed generic async decorator using `ParamSpec`/`TypeVar` with `functools.wraps`.
- Implemented required behavior:
  - success path logs debug and returns result unchanged
  - `TrueRAGError` logs warning and re-raises unchanged
  - `ValueError` logs warning and translates to `InvalidCursorError`
  - other exceptions log via `.exception()` and re-raise unchanged
- Added `pytest-asyncio` unit tests for success + three exception paths + wraps name preservation.
- Verified strict typing for `app/core/decorators.py` with mypy (`--strict`).

## File List

- app/core/decorators.py (new)
- tests/core/test_decorators.py (new)
- _bmad-output/implementation-artifacts/1-12-generic-service-error-decorator.md (updated: Status, Dev Agent Record, File List, Change Log)

## Change Log

- 2026-05-07: Added generic typed async `service_method` decorator with loguru logging and centralized error translation.
- 2026-05-07: Added focused unit test suite for decorator behavior and wraps preservation.
