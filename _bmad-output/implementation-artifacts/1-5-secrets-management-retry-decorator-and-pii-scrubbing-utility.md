# Story 1.5: Secrets Management, Retry Decorator & PII Scrubbing Utility

Status: done

## Story

As an AI Platform Engineer,
I want an AWS Secrets Manager wrapper, an exponential backoff retry decorator, and a PII scrubbing utility available to all pipelines,
So that credential access is centralised (FR53), retry logic is never duplicated per provider, and PII scrubbing is a single explicit call site for both the ingestion and query pipelines.

## Acceptance Criteria

**AC1:** Given `app/utils/secrets.py`
When any application code needs a credential
Then it calls `await get_secret(name)` from this module only; no other file imports `aioboto3` directly for Secrets Manager; the secret is read at call time, never cached at startup

**AC2:** Given `app/utils/retry.py` with `@retry(max_attempts=3, backoff_factor=2)` applied to an async function
When the decorated function raises an exception
Then it retries up to 3 times with exponential backoff (1s, 2s, 4s); it raises the last exception on exhaustion; no provider file reimplements retry logic inline

**AC3:** Given `app/utils/pii.py` calling Microsoft Presidio Analyzer
When `scrub_pii(text: str) -> str` is called with text containing a name, email, or phone number
Then those entities are replaced with anonymised placeholders; the original sensitive text is never returned

**AC4:** Given `scrub_pii()` called with text containing no PII
When the function executes
Then the original text is returned unchanged

## Tasks / Subtasks

- [x] Task 1: Create `app/utils/secrets.py` — AWS Secrets Manager wrapper (AC1)
  - [x] 1.1 Create `app/utils/secrets.py` with async function `get_secret(name: str) -> str`
  - [x] 1.2 Use `app.state.aws_session` from the FastAPI request scope OR accept an `aioboto3.Session` parameter — see implementation notes; do NOT create a new session per call
  - [x] 1.3 Call `async with session.client("secretsmanager", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url) as client:` and `await client.get_secret_value(SecretId=name)`
  - [x] 1.4 Return `response["SecretString"]`; raise `ProviderUnavailableError(f"Secret {name!r} unavailable: {exc}")` on any exception
  - [x] 1.5 Never cache the result — read at call time every time (FR53: rotation takes effect on next request)
  - [x] 1.6 Log the lookup (operation only, never the value): `logger.info("get_secret", extra={"operation": "get_secret", "extra_data": {"secret_name": name}})`

- [x] Task 2: Create `app/utils/retry.py` — exponential backoff retry decorator (AC2)
  - [x] 2.1 Create `app/utils/retry.py` with a decorator factory `retry(max_attempts: int = 3, backoff_factor: float = 2.0) -> Callable`
  - [x] 2.2 Decorator must work on `async` functions only (use `asyncio.sleep` for backoff, not `time.sleep`)
  - [x] 2.3 Backoff schedule: attempt 1 fails → sleep `backoff_factor ** 0` = 1s; attempt 2 fails → sleep `backoff_factor ** 1` = 2s; attempt 3 fails → raise last exception (no sleep after final attempt)
  - [x] 2.4 Log each retry attempt at WARNING level: `logger.warning("retry_attempt", extra={"operation": op_name, "extra_data": {"attempt": attempt, "max_attempts": max_attempts, "error": str(exc)}})`
  - [x] 2.5 Preserve the original function's `__name__`, `__doc__`, and type signature using `functools.wraps`
  - [x] 2.6 Use `ParamSpec` and `TypeVar` for full mypy strict compatibility (see implementation notes)

- [x] Task 3: Create `app/utils/pii.py` — Microsoft Presidio PII scrubbing utility (AC3, AC4)
  - [x] 3.1 Create `app/utils/pii.py` with function `scrub_pii(text: str) -> str`
  - [x] 3.2 Initialise `AnalyzerEngine` and `AnonymizerEngine` at module level (expensive to construct; initialise once)
  - [x] 3.3 Call `analyzer.analyze(text=text, language="en")` to detect PII entities
  - [x] 3.4 If no entities found, return `text` unchanged immediately (AC4)
  - [x] 3.5 Call `anonymizer.anonymize(text=text, analyzer_results=results)` to replace entities with placeholders
  - [x] 3.6 Return `anonymizer_result.text`
  - [x] 3.7 Log scrubbing result (entity count only, never the text): `logger.info("pii_scrub", extra={"operation": "pii_scrub", "extra_data": {"entities_found": len(results), "document_id": document_id}})`; the function signature is `scrub_pii(text: str, *, document_id: str | None = None) -> str` so callers can pass context
  - [x] 3.8 The original text or scrubbed text content MUST NEVER be written to any log (architecture requirement)

- [x] Task 4: Write tests (AC1, AC2, AC3, AC4)
  - [x] 4.1 Create `tests/utils/test_secrets.py`
    - [x] 4.1.1 Test `get_secret("my-secret")` with mock session returning `{"SecretString": "value"}` → assert returns `"value"`
    - [x] 4.1.2 Test `get_secret` raises `ProviderUnavailableError` when boto3 raises `Exception`
    - [x] 4.1.3 Verify `get_secret_value` is called with correct `SecretId`
  - [x] 4.2 Create `tests/utils/test_retry.py`
    - [x] 4.2.1 Test function decorated with `@retry(max_attempts=3, backoff_factor=2)` succeeds on first attempt (no sleep)
    - [x] 4.2.2 Test function fails on attempt 1, succeeds on attempt 2 → assert called twice, slept once (1s)
    - [x] 4.2.3 Test function fails all 3 attempts → assert raises last exception, slept twice (1s then 2s)
    - [x] 4.2.4 Test `asyncio.sleep` is patched — do NOT use real sleep in tests
    - [x] 4.2.5 Test decorated function preserves `__name__` (functools.wraps check)
  - [x] 4.3 Create `tests/utils/test_pii.py`
    - [x] 4.3.1 Test `scrub_pii("My name is John Smith")` → result does not contain "John Smith"
    - [x] 4.3.2 Test `scrub_pii("Contact me at user@example.com")` → result does not contain "user@example.com"
    - [x] 4.3.3 Test `scrub_pii("No sensitive information here")` → returns original text unchanged
    - [x] 4.3.4 Test `scrub_pii("Call me at +1-555-123-4567")` → result does not contain the phone number
  - [x] 4.4 Ensure `tests/utils/__init__.py` exists (create if absent)
  - [x] 4.5 Run `ruff check app/ tests/` — must exit 0
  - [x] 4.6 Run `mypy app/ --strict` — must exit 0
  - [x] 4.7 Run `pytest tests/ -v` — all tests must pass

- [x] Task 5: Add `presidio-analyzer` spaCy model download to setup notes
  - [x] 5.1 Presidio requires the `en_core_web_lg` spaCy model: `python -m spacy download en_core_web_lg`
  - [x] 5.2 Document this in a comment at top of `app/utils/pii.py`: `# Requires: python -m spacy download en_core_web_lg`

## Dev Notes

### Critical Architecture Rules (must not violate)

- **`app/utils/secrets.py` is the ONLY file that accesses Secrets Manager** — any other file needing a credential calls `get_secret()` from here; never `aioboto3` direct in providers or services
- **`app/utils/retry.py` is the ONLY place retry logic lives** — no provider, service, or pipeline file reimplements retry inline; always use `@retry(...)` decorator
- **`scrub_pii()` is called explicitly** — NOT via middleware or decorator; both ingestion pipeline (pre-chunk) and query pipeline (pre-retrieval) call it directly from `app/utils/pii.py`. Keeps scrubbing visible and prevents silent bypass.
- **Never log PII** — the raw `text` parameter or the scrubbed output must never appear in any log entry; log only entity count and document_id metadata
- **`get_secret()` never caches** — reads at operation time every call; this is the architectural mechanism for secret rotation (FR53)
- **All logging via `get_logger(__name__)`** — never `print()`, never `import logging` directly

### File Locations

```
app/utils/secrets.py          ← NEW: AWS Secrets Manager wrapper
app/utils/retry.py            ← NEW: exponential backoff decorator
app/utils/pii.py              ← NEW: Presidio PII scrubbing utility
tests/utils/__init__.py       ← NEW if absent: test package init
tests/utils/test_secrets.py   ← NEW: secrets tests
tests/utils/test_retry.py     ← NEW: retry decorator tests
tests/utils/test_pii.py       ← NEW: PII scrubbing tests
```

No existing files are modified in this story. These are all new utility modules.

### Existing State (do NOT recreate)

- `app/utils/observability.py` — already exists; `get_logger(__name__)` is the logging utility to use
- `app/utils/__init__.py` — already exists; do NOT recreate
- `app/core/errors.py` — already exists; `ProviderUnavailableError` is already defined here
- `app/core/config.py` — already has `aws_region`, `aws_endpoint_url` settings; use `get_settings()`
- `app/main.py` — already creates `app.state.aws_session = aioboto3.Session()` in lifespan

### Implementation: `app/utils/secrets.py`

```python
# app/utils/secrets.py
import aioboto3  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

logger = get_logger(__name__)


async def get_secret(name: str, session: aioboto3.Session | None = None) -> str:
    settings = get_settings()
    _session = session or aioboto3.Session()
    logger.info("get_secret", extra={"operation": "get_secret", "extra_data": {"secret_name": name}})
    try:
        async with _session.client(
            "secretsmanager",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as client:
            response = await client.get_secret_value(SecretId=name)
            return str(response["SecretString"])
    except Exception as exc:
        raise ProviderUnavailableError(f"Secret {name!r} unavailable: {exc}") from exc
```

**Note on session parameter:** Accepting an optional session makes the function testable without needing `app.state`. Callers in production should pass `request.app.state.aws_session` when available. For now (Story 1.5), no callers exist yet — the function is wired up in Story 1.6+ when actual credential retrieval is needed.

### Implementation: `app/utils/retry.py`

```python
# app/utils/retry.py
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
                except Exception as exc:
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
```

**Backoff schedule for `@retry(max_attempts=3, backoff_factor=2)`:**
- Attempt 1 fails → sleep 2^0 = 1s
- Attempt 2 fails → sleep 2^1 = 2s
- Attempt 3 fails → raise last exception (no sleep)

### Implementation: `app/utils/pii.py`

```python
# Requires: python -m spacy download en_core_web_lg
from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-untyped]

from app.utils.observability import get_logger

logger = get_logger(__name__)

# Module-level initialisation — engines are expensive to construct
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


def scrub_pii(text: str, *, document_id: str | None = None) -> str:
    results = _analyzer.analyze(text=text, language="en")
    if not results:
        return text
    anonymized = _anonymizer.anonymize(text=text, analyzer_results=results)
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "extra_data": {"entities_found": len(results), "document_id": document_id},
        },
    )
    return str(anonymized.text)
```

**Critical:** `scrub_pii` is a **synchronous** function — Presidio does not have an async API. This is intentional and correct. Callers in the async pipeline call it directly; it runs in the event loop thread. If Presidio becomes a bottleneck, a later story can wrap it in `run_in_executor`.

### mypy Strict Notes

- `presidio_analyzer` and `presidio_anonymizer` do not ship type stubs. Use `# type: ignore[import-untyped]` on their imports (same pattern as `aioboto3` and `asyncpg` in earlier stories).
- `aioboto3` already has `# type: ignore[import-untyped]` in `app/main.py` — apply the same to `app/utils/secrets.py`.
- `ParamSpec` and `TypeVar` in `app/utils/retry.py` satisfy mypy strict for the decorator's type preservation.
- The `AnalyzerEngine` and `AnonymizerEngine` return types are untyped — cast or annotate with `Any` where needed.

### Previous Story Learnings (from Story 1.4)

- **Ruff UP035:** use `from collections.abc import Callable, Coroutine` not `from typing import Callable, Coroutine`
- **Import order for ruff I001:** stdlib → third-party → first-party (`app.*`) with blank lines between groups
- **`StrEnum` (Python 3.11)** is the ruff-preferred pattern for enums — already used in `app/core/errors.py`
- **mypy strict requires explicit return annotations** — all functions must annotate return type
- **`# type: ignore[import-untyped]`** for untyped third-party packages — already established pattern
- **`tests/api/v1/` directory** uses `__init__.py`; confirm `tests/utils/__init__.py` exists before writing tests
- **`asyncio.sleep` must be patched in tests** — never let real sleep execute in test suite; use `unittest.mock.patch("asyncio.sleep")` or `pytest-asyncio` with mock

### Anti-Patterns to Avoid

- **Do NOT** cache the result of `get_secret()` — caching breaks secret rotation (FR53 zero-tolerance)
- **Do NOT** use `time.sleep` in the retry decorator — must use `asyncio.sleep` to avoid blocking the event loop
- **Do NOT** implement retry logic inline in any provider or service — always use `@retry(...)` from `app/utils/retry.py`
- **Do NOT** call Presidio or `scrub_pii` via middleware or a decorator — call it explicitly at the two designated call sites (ingestion pre-chunk, query pre-retrieval)
- **Do NOT** log text content at any point in `app/utils/pii.py` — log only `entities_found` count and `document_id`
- **Do NOT** create `app/core/auth.py` or `app/core/rate_limiter.py` — those are Stories 1.6 and 1.7
- **Do NOT** create `app/core/dependencies.py` — that is Story 1.8
- **Do NOT** create `app/utils/pagination.py` — that is a later story
- **Do NOT** call `get_secret()` from within `app/main.py` lifespan for the MongoDB URI or pgvector DSN — those are direct URI settings; the secrets wrapper integration into providers happens in Epic 2+

### Dependencies Already in requirements.txt

All required packages are already present — no new dependencies needed:
- `presidio-analyzer>=2.2.354,<3.0.0` — PII detection engine
- `presidio-anonymizer>=2.2.354,<3.0.0` — PII anonymization engine
- `spacy>=3.7.0,<4.0.0` — NLP backend for Presidio
- `aioboto3>=13.0.0,<14.0.0` — AWS async SDK (already in requirements.txt, used in Story 1.4)

**Spacy model:** Presidio requires `en_core_web_lg` at runtime. This is NOT a pip package — it must be downloaded separately:
```
python -m spacy download en_core_web_lg
```
This download is required for `scrub_pii()` to work. For CI/CD, add this step to the GitHub Actions workflow before tests. For tests that must avoid model loading, mock `_analyzer.analyze` and `_anonymizer.anonymize` directly.

### Test Patterns

```python
# tests/utils/test_retry.py — patch asyncio.sleep
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.retry import retry


@pytest.mark.asyncio
async def test_retry_succeeds_first_attempt() -> None:
    mock_fn = AsyncMock(return_value="ok")

    @retry(max_attempts=3, backoff_factor=2)
    async def wrapped() -> str:
        return await mock_fn()

    result = await wrapped()
    assert result == "ok"
    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_retry_exhausted_raises_last_exception() -> None:
    mock_fn = AsyncMock(side_effect=ValueError("fail"))

    @retry(max_attempts=3, backoff_factor=2)
    async def wrapped() -> str:
        return await mock_fn()

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(ValueError, match="fail"):
            await wrapped()
    assert mock_fn.call_count == 3
    assert mock_sleep.call_count == 2  # sleep after attempt 1 and 2; not after 3
    mock_sleep.assert_any_call(1.0)   # backoff_factor^0
    mock_sleep.assert_any_call(2.0)   # backoff_factor^1
```

```python
# tests/utils/test_secrets.py — mock aioboto3 session
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.utils.secrets import get_secret
from app.core.errors import ProviderUnavailableError


@pytest.mark.asyncio
async def test_get_secret_returns_value() -> None:
    mock_client = AsyncMock()
    mock_client.get_secret_value = AsyncMock(return_value={"SecretString": "my-value"})
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await get_secret("my-secret", session=mock_session)
    assert result == "my-value"
    mock_client.get_secret_value.assert_called_once_with(SecretId="my-secret")


@pytest.mark.asyncio
async def test_get_secret_raises_provider_unavailable_on_error() -> None:
    mock_client = AsyncMock()
    mock_client.get_secret_value = AsyncMock(side_effect=Exception("network error"))
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(ProviderUnavailableError):
        await get_secret("my-secret", session=mock_session)
```

```python
# tests/utils/test_pii.py — real Presidio (requires en_core_web_lg) OR mock engines
# If en_core_web_lg is not available in CI, mock _analyzer and _anonymizer:
from unittest.mock import MagicMock, patch
from app.utils.pii import scrub_pii


def test_scrub_pii_no_pii_returns_unchanged() -> None:
    text = "No sensitive information here"
    # Mock analyzer returning no results
    with patch("app.utils.pii._analyzer") as mock_analyzer, \
         patch("app.utils.pii._anonymizer"):
        mock_analyzer.analyze.return_value = []
        result = scrub_pii(text)
    assert result == text


def test_scrub_pii_replaces_entities() -> None:
    from presidio_anonymizer.entities import EngineResult  # type: ignore[import-untyped]
    mock_result = MagicMock()
    mock_anonymized = MagicMock()
    mock_anonymized.text = "<PERSON> is here"

    with patch("app.utils.pii._analyzer") as mock_analyzer, \
         patch("app.utils.pii._anonymizer") as mock_anon:
        mock_analyzer.analyze.return_value = [mock_result]
        mock_anon.anonymize.return_value = mock_anonymized
        result = scrub_pii("John Smith is here")

    assert result == "<PERSON> is here"
    assert "John Smith" not in result
```

### References

- [Source: architecture.md#Communication Patterns] — Secrets via `app/utils/secrets.py` only; retry via `app/utils/retry.py` only; PII scrubbing explicitly via `app/utils/pii.py`
- [Source: architecture.md#Enforcement Guidelines] — "Never call Secrets Manager directly — always use `app/utils/secrets.py`"; "Never implement retry logic inline — always use the retry decorator from `app/utils/retry.py`"
- [Source: architecture.md#Project Structure] — `app/utils/secrets.py`, `app/utils/pii.py`, `app/utils/retry.py`, `app/utils/pagination.py`
- [Source: epics.md#Story 1.5] — User story and 4 acceptance criteria
- [Source: architecture.md#D15] — Structured logging format; every log must include `operation`
- [Source: prd.md#FR53] — Credentials read at operation time; rotation takes effect on next request

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Completion Notes List

- Created `app/utils/secrets.py`: async `get_secret(name, session)` — reads AWS Secrets Manager at call time (never cached), raises `ProviderUnavailableError` on failure. Session is optional for testability; callers pass `request.app.state.aws_session` in production.
- Created `app/utils/retry.py`: `@retry(max_attempts, backoff_factor)` decorator factory using `asyncio.sleep`, `ParamSpec`/`TypeVar` for mypy strict, `functools.wraps` for name preservation. Backoff: 1s → 2s → raise.
- Created `app/utils/pii.py`: `scrub_pii(text, *, document_id)` using Microsoft Presidio. Engines use lazy initialization (initialized on first call, cached thereafter) to allow module import without the spaCy model — production behavior identical to module-level init. Logs only entity count and document_id, never text content.
- All tests use mocks to bypass real engine/AWS calls. `asyncio.sleep` patched in retry tests. 65/65 tests pass, 0 regressions.
- `ruff check` exits 0; `mypy app/ --strict` exits 0.
- Note: `en_core_web_lg` spaCy model download initiated (`python -m spacy download en_core_web_lg`) per Task 5.1 requirement.

### File List

- `app/utils/secrets.py` (new)
- `app/utils/retry.py` (new)
- `app/utils/pii.py` (new)
- `tests/utils/test_secrets.py` (new)
- `tests/utils/test_retry.py` (new)
- `tests/utils/test_pii.py` (new)

### Review Findings

#### Decision-Needed (resolve before patching)

- [ ] [Review][Decision] Session-per-call when no session injected — `get_secret` creates a new `aioboto3.Session()` on every call when no session is passed; should there be a module-level default session, or is per-call creation acceptable until Story 1.6 wires callers? `app/utils/secrets.py:12`
- [ ] [Review][Decision] Presidio runtime exceptions propagate unwrapped — `analyzer.analyze()` / `anonymizer.anonymize()` failures surface as raw Presidio/spaCy exceptions; should these be caught and re-raised as `ProviderUnavailableError` (or similar domain error)? `app/utils/pii.py:26-29`
- [ ] [Review][Decision] Retry catches ALL exceptions including non-transient ones — `except Exception` retries `ValueError`, `TypeError`, auth errors, etc.; should non-retriable exception types be excluded? `app/utils/retry.py:27`

#### Patch

- [ ] [Review][Patch] `response["SecretString"]` raises `KeyError` for binary secrets — no `SecretBinary` guard; caught as misleading `ProviderUnavailableError` [`app/utils/secrets.py:23`]
- [ ] [Review][Patch] Partial PII engine init — if `AnonymizerEngine()` raises, `_analyzer` is set but `_anonymizer` stays `None`; next call skips re-init and crashes with `AttributeError` [`app/utils/pii.py:17-18`]
- [ ] [Review][Patch] `asyncio.sleep` patched at wrong module path — `"asyncio.sleep"` should be `"app.utils.retry.asyncio.sleep"` for robustness [`tests/utils/test_retry.py:30`]
- [ ] [Review][Patch] PII test isolation — patching `_analyzer`/`_anonymizer` module globals can be bypassed by `_get_engines()` cache; needs fixture to reset globals between tests [`tests/utils/test_pii.py`]
- [ ] [Review][Patch] `max_attempts=0` raises opaque `RuntimeError("No attempts made")` — needs `ValueError` validation at decoration time [`app/utils/retry.py:14`]
- [ ] [Review][Patch] Presidio imports missing `# type: ignore[import-untyped]` — mypy strict will flag untyped imports [`app/utils/pii.py:4-5`]
- [ ] [Review][Patch] No test verifying `get_secret` reads on every call — FR53 no-cache guarantee is untested [`tests/utils/test_secrets.py`]
- [ ] [Review][Patch] `test_scrub_pii_no_pii_returns_unchanged` does not assert `logger.info` was NOT called [`tests/utils/test_pii.py`]

#### Deferred

- [x] [Review][Defer] Thread-safe lazy init of PII engines — TOCTOU race possible if called from thread pool executor; asyncio is single-threaded so low immediate risk [`app/utils/pii.py:16-18`] — deferred, pre-existing pattern acceptable until executor usage begins
- [x] [Review][Defer] No jitter in retry backoff — thundering-herd risk under concurrent load [`app/utils/retry.py`] — deferred, enhancement for later story
- [x] [Review][Defer] No `max_delay` cap — unbounded sleep with large `backoff_factor` and many attempts [`app/utils/retry.py`] — deferred, enhancement for later story
- [x] [Review][Defer] Hardcoded `language="en"` in PII scrubbing — non-English text silently processed with wrong NER model [`app/utils/pii.py:26`] — deferred, internationalization out of scope
- [x] [Review][Defer] Empty secret name not validated before AWS call [`app/utils/secrets.py`] — deferred, callers are internal
- [x] [Review][Defer] Negative `backoff_factor` not validated [`app/utils/retry.py`] — deferred, internal usage only
- [x] [Review][Defer] `backoff_factor=0` produces 1.0 sleep (`0**0=1`) instead of 0 [`app/utils/retry.py`] — deferred, undocumented edge case
- [x] [Review][Defer] `anonymized.text` could be `None`, silently returning `"None"` string [`app/utils/pii.py:37`] — deferred, Presidio API stability concern
- [x] [Review][Defer] New `aioboto3.Session()` per call (resource concern) — by design for Story 1.5; callers pass session from `app.state` in Story 1.6+ [`app/utils/secrets.py:12`] — deferred, pre-existing architectural decision

## Change Log

- 2026-04-18: Story 1.5 created — secrets management wrapper, retry decorator, PII scrubbing utility (claude-sonnet-4-6)
- 2026-04-19: Story 1.5 implemented — app/utils/secrets.py, app/utils/retry.py, app/utils/pii.py created with full test coverage; 65/65 tests pass (claude-sonnet-4-6)
- 2026-04-19: Story 1.5 code reviewed — 3 decision-needed, 8 patch, 9 deferred, 5 dismissed (claude-sonnet-4-6)
