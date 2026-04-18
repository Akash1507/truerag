## Deferred from: code review of 1-5-secrets-management-retry-decorator-and-pii-scrubbing-utility.md (2026-04-19)

- **Thread-safe lazy init of PII engines** (`pii.py:16-18`) — TOCTOU race if `_get_engines()` is called concurrently from a thread pool executor; acceptable under asyncio single-threaded model but will need a `threading.Lock` if PII scrubbing is ever moved to `run_in_executor`.
- **No jitter in retry backoff** (`retry.py`) — All concurrent callers retry at exactly the same wall-clock time; add jitter when retry is used on shared downstream services.
- **No `max_delay` cap** (`retry.py`) — `backoff_factor ** (attempt - 1)` is unbounded; add a `max_delay` parameter to prevent multi-hour sleeps from misconfiguration.
- **Hardcoded `language="en"` in PII scrubbing** (`pii.py:26`) — Non-English text silently processed with incorrect NER model; expose as parameter when multilingual support is needed.
- **Empty secret name not validated** (`secrets.py`) — `get_secret("")` passes empty string to AWS; add `if not name: raise ValueError` when secrets are exposed to external input.
- **Negative `backoff_factor` not validated** (`retry.py`) — `asyncio.sleep(-n)` is silently clamped to 0 by CPython; add validation when retry is used in untrusted configuration contexts.
- **`backoff_factor=0` produces 1.0 sleep** (`retry.py`) — `0**0=1` in Python; document or guard this edge case.
- **`anonymized.text` could be `None`** (`pii.py:37`) — `str(None)` = `"None"` is silently returned; add `None` check if Presidio API stability is ever a concern.
- **New `aioboto3.Session()` per call (resource concern)** (`secrets.py:12`) — By design for Story 1.5 (no callers yet); Story 1.6+ callers should always pass `request.app.state.aws_session` to avoid per-call session construction.

## Deferred from: code review of 1-2-core-configuration-and-structured-logging.md (2026-04-18)

- Clarify which settings are required for startup validation — AC1 and Task 5.1 require a missing required setting to raise a startup `ValidationError`, but `Settings` currently gives every field a default in `app/core/config.py`, `get_settings()` can never fail for missing env, and `tests/core/test_config.py` codifies that behavior with `test_missing_field_uses_default`. The story’s own sample `Settings` class also assigns defaults to every field, so the intended required field set is ambiguous. Reason: i will review it later.
