# Story 1.9: Semantic Cache Stub

Status: done

## Story

As an AI Platform Engineer,
I want a `semantic_cache.py` module with a no-op `invalidate(agent_id)` method available from the start of the project,
So that Stories 4.6 (reindex) and 6.1 (golden dataset) can call cache invalidation without forward-coupling to Epic 8, and the real implementation in Epic 8 is a drop-in replacement with no changes to call sites.

## Acceptance Criteria

**AC1:** Given `app/utils/semantic_cache.py` exists after Epic 1 is complete
When its interface is inspected
Then it exposes at minimum `async def invalidate(agent_id: str) -> None` — calling this method is a silent no-op; it does not raise, does not write to any store, and does not log

**AC2:** Given `app/utils/semantic_cache.py` is imported and called by `ingestion_service.py` or `eval_service.py` before Epic 8 is implemented
When `invalidate(agent_id)` is called
Then the call completes without error and has no side effects; no conditional `if semantic_cache_enabled` guard is needed at the call site

**AC3:** Given Epic 8 implements real semantic cache functionality
When `app/utils/semantic_cache.py` is updated to a real implementation
Then all existing call sites in Stories 4.6 and 6.1 continue to work without modification — the stub and real implementation share the same method signature

**AC4:** Given mypy strict type checking runs on `app/utils/semantic_cache.py`
When the check completes
Then the module passes with zero errors; the stub is fully typed

## Tasks / Subtasks

- [x] Task 1: Create semantic cache stub module (AC1, AC2, AC3, AC4)
  - [x] 1.1 Create `app/utils/semantic_cache.py` — module-level `async def invalidate(agent_id: str) -> None` function that is a pure no-op
  - [x] 1.2 Ensure no logging, no side effects, no imports of external libraries — `pass` body only
  - [x] 1.3 Verify the function signature matches exactly what future callers in Stories 4.6 and 6.1 will use: `await semantic_cache.invalidate(agent_id)`

- [x] Task 2: Write tests (AC1–AC4)
  - [x] 2.1 Create `tests/utils/test_semantic_cache.py` — verify `invalidate()` is awaitable, returns `None`, and accepts `agent_id: str`
  - [x] 2.2 Verify calling `invalidate()` raises no exceptions (empty string, normal id, special chars)
  - [x] 2.3 Run `ruff check app/utils/semantic_cache.py tests/utils/test_semantic_cache.py` — must exit 0
  - [x] 2.4 Run `mypy app/utils/semantic_cache.py --strict` — must exit 0
  - [x] 2.5 Run `pytest tests/ -v` — all existing 112+ tests must pass; no regressions

## Dev Notes

### Critical Architecture Rules (must not violate)

- **`app/utils/semantic_cache.py` is a MODULE-LEVEL function** — NOT a class, NOT an instance method; callers use `from app.utils import semantic_cache` then `await semantic_cache.invalidate(agent_id)` — the module IS the interface
- **Zero logging** — the epics spec is explicit: "does not log"; do NOT import `get_logger` or call `structlog`/`logging` anywhere in this file
- **Zero side effects** — no writes, no reads, no network calls, no state mutation; the body is literally `pass`
- **Method signature is LOCKED** — `async def invalidate(agent_id: str) -> None` — Epic 8 drops in a real implementation at this exact path; any signature deviation breaks Stories 4.6 and 6.1 call sites
- **Do NOT create a class** — previous stories use `from app.utils.pii import scrub_pii` (module-level function) pattern; follow the same pattern here
- **Do NOT add `enabled` flag or guard** — the whole point is eliminating `if semantic_cache_enabled` conditionals; the stub IS always enabled (no-op)
- **Do NOT import from `app/providers/cache/`** — that path is for Epic 8's real pgvector implementation; the stub in `app/utils/` is self-contained
- **`app/providers/cache/semantic_cache.py` is different** — architecture reserves that path for the real pgvector-backed implementation in Epic 8; the stub lives only in `app/utils/semantic_cache.py`

### Implementation: `app/utils/semantic_cache.py`

```python
async def invalidate(agent_id: str) -> None:
    """No-op stub. Epic 8 replaces this body with pgvector cache invalidation.

    Call sites: await semantic_cache.invalidate(agent_id)
    """
    pass
```

> **That is the entire file.** No imports, no class, no logger. One function, one `pass`.

### Test Implementation: `tests/utils/test_semantic_cache.py`

```python
import pytest

from app.utils import semantic_cache


@pytest.mark.asyncio
async def test_invalidate_returns_none() -> None:
    result = await semantic_cache.invalidate("tenant-1_agent-abc")
    assert result is None


@pytest.mark.asyncio
async def test_invalidate_empty_string() -> None:
    await semantic_cache.invalidate("")  # must not raise


@pytest.mark.asyncio
async def test_invalidate_is_no_op() -> None:
    # Call twice — still no error, no state side effect
    await semantic_cache.invalidate("agent-1")
    await semantic_cache.invalidate("agent-1")
```

> **Note on import pattern:** Import the module `semantic_cache`, not the function, to match how callers will use it: `import semantic_cache; await semantic_cache.invalidate(id)`. Tests exercise the module-as-namespace pattern that callers in Stories 4.6 and 6.1 will rely on.

### File Location

```
app/utils/semantic_cache.py          ← NEW: no-op invalidate stub
tests/utils/test_semantic_cache.py   ← NEW: async no-op tests
```

### Existing utils Pattern Reference

All existing utils follow module-level function pattern:
- `app/utils/pii.py` → `scrub_pii(text)` — called as `pii.scrub_pii(text)`
- `app/utils/retry.py` → `retry_with_backoff(...)` decorator
- `app/utils/observability.py` → `get_logger(__name__)` factory
- `app/utils/secrets.py` → `get_secret(name)` — called as `secrets.get_secret(name)`

`semantic_cache.invalidate(agent_id)` follows the exact same pattern — module-as-namespace.

### No New Dependencies Required

Zero new imports needed in the stub:
- No `asyncpg` (Epic 8's pgvector implementation adds this)
- No `aioboto3` (Secrets Manager, already in `app/utils/secrets.py`)
- No `structlog` (observability, already in `app/utils/observability.py`)
- `async def` is pure Python syntax — no third-party libraries needed

### pytest-asyncio Setup

`tests/utils/test_semantic_cache.py` uses `@pytest.mark.asyncio`. Verify `pytest-asyncio` is already in dev dependencies (it is — it's used in existing async tests). No new test dependencies.

Check `conftest.py` for asyncio mode setting — existing tests use `pytest.ini` or `pyproject.toml` asyncio_mode setting. Match whatever is already configured (likely `asyncio_mode = "auto"` or explicit marks).

### Caller Pattern (Forward Reference — Do NOT implement now)

Stories 4.6 and 6.1 will call:
```python
from app.utils import semantic_cache

# inside async service function:
await semantic_cache.invalidate(agent_id)
```

This is the signature the stub MUST support without modification from call sites.

### mypy Strict Notes

- `async def invalidate(agent_id: str) -> None` — fully typed, no `Any`, no missing annotations
- `pass` body — mypy infers `-> None` correctly for empty async functions
- No imports means no import-level mypy issues
- Run: `mypy app/utils/semantic_cache.py --strict` — must exit 0

### Ruff Notes

- No unused imports (nothing to import)
- `pass` in an empty async function body is acceptable; ruff does NOT flag it
- Run: `ruff check app/utils/semantic_cache.py tests/utils/test_semantic_cache.py`

### Previous Story Learnings (from Stories 1.7–1.8)

- **Use `from datetime import UTC`** — not needed here but noted for reference
- **Use built-in generics**: `list[X]`, `dict[K,V]` — not needed here
- **Use `X | None`** — not needed here
- **Never `print()` or `import logging`** — use `get_logger()` from `app/utils/observability.py`; but for this story, NO logging at all (spec says "does not log")
- **ruff I001 import order:** stdlib → third-party → first-party — not applicable (no imports in this file)
- **`# type: ignore[abstract]`** — not needed here (no ABCs)
- **112 passing tests as baseline** — after this story all 112+ must still pass

### Cross-Story Impact: Where `invalidate` Will Be Called

These future stories depend on this stub being in place (do NOT implement their logic now — just confirm the stub unblocks them):

- **Story 4.6** (developer-triggered full reindex): `ingestion_service.py` calls `await semantic_cache.invalidate(agent_id)` at reindex start
- **Story 6.1** (golden dataset management): `eval_service.py` calls `await semantic_cache.invalidate(agent_id)` when dataset is replaced

Architecture note (architecture.md line 785): "ingestion_service.py must call `semantic_cache.invalidate(agent_id)` at two explicit points — on document ingestion completion and on document deletion."

### File Structure After This Story

```
app/utils/
├── __init__.py
├── observability.py
├── pii.py
├── retry.py
├── secrets.py
└── semantic_cache.py   ← NEW (this story)

tests/utils/
├── __init__.py
├── test_observability.py
├── test_pii.py
├── test_retry.py
├── test_secrets.py
└── test_semantic_cache.py  ← NEW (this story)
```

### Epic 1 Completion Context

This is the LAST story in Epic 1 (Platform Foundation & Security Baseline). After this story:
- Epic 1 status remains `in-progress` until explicitly set to `done` by the team
- No epic retrospective is mandatory (`epic-1-retrospective: optional`)
- Epic 2 stories remain in `backlog` — next is 2-1-tenant-registration-and-api-key-issuance

### References

- [Source: epics.md#Story 1.9] — User story statement and 4 acceptance criteria
- [Source: architecture.md#D5] — Semantic cache implementation decision: pgvector table, TTL via `created_at`, invalidate on document update by deleting all rows for `agent_id`
- [Source: architecture.md#Project Structure line 623] — `app/utils/` is correct home for this stub
- [Source: architecture.md line 785] — Ingestion service must call `semantic_cache.invalidate(agent_id)` at two explicit points
- [Source: story 1.8 dev notes] — ruff/mypy patterns, test patterns, 112 test baseline

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Completion Notes List

- Created `app/utils/semantic_cache.py` — single module-level `async def invalidate(agent_id: str) -> None` with `pass` body; zero imports, zero logging, zero side effects
- Created `tests/utils/test_semantic_cache.py` — 4 async tests covering: returns None, empty string, repeated calls (no-op), special chars
- `ruff check` exits 0 on both files
- `mypy --strict` exits 0 on `app/utils/semantic_cache.py`
- Full test suite: 116 passed (112 baseline + 4 new); zero regressions
- Method signature `async def invalidate(agent_id: str) -> None` is locked and matches what Stories 4.6 and 6.1 will call

### File List

- app/utils/semantic_cache.py (new)
- tests/utils/test_semantic_cache.py (new)

### Change Log

- 2026-04-22: Implemented Story 1.9 — added `app/utils/semantic_cache.py` no-op stub and 4 async tests; all 116 tests pass, ruff and mypy strict clean
- 2026-04-22: Code review complete — 0 decision-needed, 0 patch, 2 deferred, 7 dismissed

### Review Findings

- [x] [Review][Defer] `agent_id` format contract not documented on stub signature [app/utils/semantic_cache.py:1] — deferred, pre-existing; Epic 8 implementors should define and validate allowed format (max length, charset) when real pgvector logic is added
- [x] [Review][Defer] No test or guard for `None` agent_id — forward-compatibility gap for Epic 8 [tests/utils/test_semantic_cache.py] — deferred, pre-existing; stub's no-op body makes `None` harmless now, but real implementation must add validation
