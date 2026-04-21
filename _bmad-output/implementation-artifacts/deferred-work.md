## Deferred from: code review of 1-9-semantic-cache-stub.md (2026-04-22)

- **`agent_id` format contract not documented** — stub accepts any `str` including empty string, URL-like strings, etc.; Epic 8's real pgvector implementation must define and validate allowed format (max length, charset) at the boundary to avoid injection or key-collision bugs.
- **`None` agent_id not tested or guarded** — Python callers can pass `None` at runtime despite `str` hint; stub's no-op body makes it harmless now, but Epic 8's real implementation should add `if not agent_id: raise ValueError` or equivalent validation to prevent unbounded/invalid cache invalidation queries.

## Deferred from: code review of 1-8-abstract-interfaces-and-provider-registry.md (2026-04-20)

- **`get_*()` bare `cls()` call** — future concrete providers with required init params (API key, DSN, etc.) will raise `TypeError` at request time; Story 2+ resolves via config injection pattern.
- **Registry mutable globals** — no runtime write protection; any module can corrupt `RERANKER_REGISTRY` etc.; mypy strict enforces `type[T]` statically; revisit if plugin loading is ever dynamic.
- **`PassthroughReranker.rerank()` ignores `top_k` with no guard for `top_k <= 0`** — pure passthrough by spec design; concrete rerankers (Epic 7) define their own `top_k` semantics and guards.
- **Interface contracts for empty inputs** (`chunk("")`, `embed([])`, `upsert([])`) — unspecified at the ABC level; concrete providers (Epics 4–5) define and test their own behavior.
- **`VectorRecord.vector` no `min_length=1`; `VectorResult.score` no finite-float validation** — provider-specific constraints; Epic 4 adds concrete models with field validators.

## Deferred from: code review of 1-7-per-tenant-rate-limiting.md (2026-04-20)

- **Cross-replica rate limiting** — `_counters` is process-local; with N replicas a tenant may issue up to N×rpm requests before being rate-limited across all replicas. Explicitly accepted per ADR 007; Redis-backed global enforcement deferred to v2.
- **Fixed-window 2× boundary burst** — a tenant can exhaust the limit at the end of window T and immediately send another full limit at the start of window T+1, allowing up to 2× limit in any 60-second span. Inherent fixed-window limitation; sliding window deferred to v2.
- **`_counters` dict grows without bound** — no eviction policy; stale entries for inactive tenants are never removed. Negligible at v1 scale (≤50 tenants); eviction handled naturally in v2 Redis migration.
- **Auth timing oracle** — missing key (no DB query, fast path) vs invalid key (DB query, slow path) produces observable timing difference. Architectural tradeoff; mitigating with dummy queries adds latency on every unauthenticated request.

## Deferred from: code review of 1-6-api-key-authentication-and-cross-tenant-access-control.md (2026-04-20)

- **Rate limiting not enforced** — `TenantDocument.rate_limit_rpm` is stored and deserialized but never read or enforced in `AuthMiddleware`; rate limiting is Story 1.7 scope.
- **No API key revocation field** — No `is_active` flag or similar on `TenantDocument`; compromised keys can only be invalidated by deleting the tenant document. Future story concern.
- **SHA-256 without HMAC salt** — `_hash_api_key` uses bare SHA-256 with no server-side secret; an exfiltrated `tenants` collection enables offline brute-force against common key patterns. Per architecture decision D6; revisit if threat model requires stronger key storage.
- **`motor_client` not guarded at request time** — `request.app.state.motor_client` is accessed without a `hasattr` guard; misconfigured deployment raises an unstructured `AttributeError` → 500. Startup lifespan is expected to prevent this in practice.
- **`TenantDocument.created_at` accepts naive datetimes** — Pydantic does not enforce timezone-awareness; naive datetimes from MongoDB could cause silent comparison bugs if expiry logic is added later.

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
