## Deferred from: code review of 4-1-document-parsing-and-fixed-size-chunking.md (2026-05-01)

- **DOCX table/header/footer content silently dropped** (`parser.py:36-40`) — `doc.paragraphs` does not iterate tables, headers, or footers; significant DOCX content can be missing without error. Extend DOCX extraction to include table cell text when DOCX parsing is hardened.
- **`KeyError` from unknown `chunking_strategy` causes indefinite SQS retry** (`pipeline.py:67`) — spec explicitly allows this; a permanently-absent strategy will retry until DLQ. Consider `PermanentIngestionError` for unregistered strategies if this causes operational issues.
- **`process_job` marks `processing` before agent check** (`ingestion_worker.py:21-27`) — pre-existing; if initial DAO update fails, document stuck in `queued`. Wrap pre-pipeline status updates in the same try/except when `process_job` error handling is revisited (also noted in 3-4 review).
- **No explicit cross-tenant assertion after `agent_dao.find_one`** (`ingestion_worker.py:30-31`) — relies entirely on DAO query predicate; add explicit `assert agent.tenant_id == payload.tenant_id` as defense-in-depth when DAO security hardening is done.
- **No max document size guard before parsing** (`parser.py:9`) — large S3 objects fully buffered into memory; OOM risk under concurrency (also noted in 3-4 review as `ContentLength` guard).
- **Pre-try DAO calls in `process_job` can raise unhandled exceptions** (`ingestion_worker.py:21-27`) — pre-existing; document stuck in prior state if initial status write fails (also noted in 3-4 review).
- **Status split risk on final ready update** (`ingestion_worker.py:59-64`) — `ingestion_job_dao.update(ready)` success then `document_dao.update(ready)` failure leaves collections inconsistent; wrap in try/except when `process_job` error handling is revisited.
- **DAO call in `except` block can suppress original exception** (`ingestion_worker.py:47-57`) — if failure-status DAO update throws, original exception lost from logs; nest inner try/except around DAO calls in error handler.
- **Null bytes in TXT files silently decoded** (`parser.py:22`) — `content.decode("utf-8")` succeeds with null bytes; may corrupt downstream tokenizer. Strip null bytes or raise `ParseError` when text pre-processing is standardized.
- **Encrypted/scanned PDF produces opaque `ParseError`** (`parser.py:28-33`) — AC1 satisfied but encrypted PDFs and scanned PDFs are indistinguishable; add specific detection when PDF parsing is hardened.
- **`_chunk_text` uses hardcoded `chunk_size`/`chunk_overlap` kwargs** (`pipeline.py:68`) — future chunking strategies with different init params will `TypeError`; define a factory interface when the second strategy is added.
- **`chunk_size=0` bypass via direct `FixedSizeChunker` instantiation** (`fixed_size.py:8`) — Pydantic guards protect production path; add defensive `chunk_size > 0` in `__init__` when `ChunkingStrategy` base class is hardened.

## Deferred from: code review of 3-4-pii-scrubbing-at-ingestion.md (2026-05-01)

- **S3 object fully buffered with no size guard** (`pipeline.py:35`) — `response["Body"].read()` loads the entire S3 object into memory; a large file will OOM the worker. Add `ContentLength` check or streaming with a ceiling when a max-file-size config is defined.
- **`_extract_text` ignores `file_type`, always UTF-8 decodes** (`pipeline.py:38-40`) — intentional stub; PDF/DOCX bytes produce garbage/replacement-char text. Epic 4 replaces with real parsers; at that point enforce branching on `file_type`.
- **`IngestionJobPayload.timestamp` is a raw `str` — no format enforcement** (`ingestion_job.py:17`) — spec-compliant as-is; tighten to `datetime` or add a validator when payload schema is formalized.
- **PII scrub log omits `s3_key` and `job_id`** (`pipeline.py:47-58`) — makes S3-level incident triage harder; add to `extra_data` when log schema is standardized.
- **`_download_from_s3` has no request timeout** (`pipeline.py:29-35`) — a stalled S3 endpoint blocks the worker event loop until SQS visibility timeout expires and re-enqueues; set `connect_timeout` / `read_timeout` on the aioboto3 client when global AWS client config is introduced.
- **`_get_engines()` lazy-init failure propagates as raw `Exception`** (`pii.py`) — pre-existing: if the spaCy model is missing, `OSError`/`ImportError` bubbles up unclassified rather than as `ProviderUnavailableError`; fix in `pii.py` when engine initialization is hardened.
- **`payload.s3_key` used verbatim in S3 `get_object` — no tenant namespace check** (`pipeline.py:34`) — a crafted SQS message can read any bucket object; enforce `s3_key` prefix scoping (`{tenant_id}/{agent_id}/`) in the SQS consumer (story 3-2) when SQS message validation is tightened.
- **DAO status-update calls sit before `try` block in `process_job`** (`ingestion_worker.py`) — pre-existing: a DAO failure during the `processing` status write leaves the document stuck in `queued` with no `failed` marker; wrap pre-pipeline DAO calls in the same try/except when `process_job` error handling is revisited.

## Deferred from: code review of 1-10-beanie-odm-dao-layer-and-dynamodb-removal.md (2026-05-01)

- **No unique constraint on `job_id` in `IngestionJob`** — simple index only; concurrent uploads with same `job_id` could create duplicates. UUID generation makes collision negligible; revisit if job_id generation changes.
- **DAO singletons instantiated at module import before `init_beanie()`** — all four DAO singleton objects (`tenant_dao`, `agent_dao`, `document_dao`, `ingestion_job_dao`) are module-level globals created before `lifespan` runs `init_beanie()`. Works correctly in practice but provides no runtime guard if a startup hook or test fixture invokes a DAO method early. Pre-existing design; add explicit init-guard if BeanieNotInitialized errors appear in logs.
- **`BaseDAO.update()` silent no-op when no document matches** — `find(...).update({'$set': ...})` silently does nothing if the query matches zero documents. Common MongoDB convention; callers currently do not check the return value. Harden when DAO update semantics need explicit not-found signaling.
- **Tenant delete ordering — agents deleted before tenant record with no multi-doc transaction** — `delete_tenant` deletes agents first, then the tenant; a crash between steps leaves agents gone but tenant present. Requires MongoDB multi-document transactions (Driver 4.x) to fix atomically; defer until transaction support is added.
- **S3 delete failure after vector namespace deletion in `delete_agent`** — `delete_agent` deletes the vector namespace before S3 objects; if S3 `delete_objects` fails, MongoDB records are never cleaned and vector data is already gone. Requires a compensating-transaction design; defer with the broader cross-resource consistency initiative.
- **`delete_one` non-atomic (find then delete)** — `BaseDAO.delete_one` runs a `find_one` followed by a separate delete; concurrent request can delete the document between the two calls causing a silent no-op. Fix with `FindOne().delete()` Beanie atomic API; defer until DAO atomicity is revisited.
- **Orphaned `IngestionJob` if `document.job_id` explicitly cleared post-creation** — `delete_agent` collects `job_ids` from `d.job_id for d in docs`; if any document had its `job_id` set to `None` after the job was created, the corresponding `IngestionJob` is never deleted. Hypothetical path not in current code; add belt-and-suspenders cleanup by `document_id` if this pattern emerges.

## Deferred from: code review of 3-3-ingestion-status-polling-and-document-listing.md (2026-04-30)

- **403 vs 404 differential leaks document existence to cross-tenant caller** — `get_document_status` returns 403 when doc exists but wrong tenant, 404 when doc absent; leaks document existence. Spec-mandated behavior consistent with agent_service pattern; revisit in a future security hardening pass if tenant isolation needs to be opaque.
- **No compound MongoDB index `(tenant_id, agent_id, _id)` for cursor pagination** — `list_documents` cursor query `{"agent_id": ..., "tenant_id": ..., "_id": {"$gt": oid}}` will full-scan at scale without a compound index. Add `create_index([("tenant_id", 1), ("agent_id", 1), ("_id", 1)])` when MongoDB index management is formalized.
- **DynamoDB client opened per-request with no connection reuse** — `async with aws_session.client("dynamodb", ...)` in `get_document_status` creates a new connection per status poll. Established pattern across codebase; refactor when AWS client pooling strategy is addressed globally.
- **MongoDB document fields accessed via `doc["key"]` without `.get()` guards** — `doc["tenant_id"]`, `doc["agent_id"]`, `doc["status"]`, `doc["file_type"]`, etc. accessed without defensive `.get()` on lines 203, 220, 269–278. Pre-existing invariant that upload_document always sets these fields; add `.get()` guards when schema validation is added to the documents collection.
- **Cursor tamper protection absent** — a valid ObjectId from another collection can be used as a cursor to seek to an arbitrary position. Pre-existing design decision (no HMAC); harden when cursor-signing is standardized across the API.

## Deferred from: code review of 2-2-tenant-listing-and-deletion.md (2026-04-23)

- **`VECTOR_STORE_REGISTRY` empty — `delete_tenant` returns 503 for tenants with agents** — intentional by spec (Dev Notes explicitly acknowledge this); registry is populated in Epic 4; no agents exist until Story 2.3 so the path is not exercised yet.
- **Unsigned cursor allows position-based tenant enumeration** — authenticated callers can construct any valid ObjectId cursor string to seek to an arbitrary page; spec does not require HMAC-signed cursors; harden in a future security pass if cursor opacity becomes a requirement.
- **Open tenant registration — no admin gate on `POST /v1/tenants`** — v1 bootstrap model; admin-auth controls (bootstrap token, IP allowlist) deferred to post-v1 hardening.

## Deferred from: code review of 2-1-tenant-registration-and-api-key-issuance.md (2026-04-22)

- **Unauthenticated `POST /v1/tenants` has no secondary rate limit** — known bootstrap design tradeoff; anonymous callers can flood tenant creation; revisit when an admin-auth or network-layer control is added.
- **`TenantDocument.rate_limit_rpm: int | None`** — pre-existing nullable declaration; service always stores an `int` so the `None` branch is dead code; tighten to `int` with a non-None default when the model is next touched.
- **`insert_one` mutates `doc` dict in-place (adds `_id`); no `extra="ignore"` on `TenantDocument`** — latent fragility; if `model_validate(stored_doc)` is ever called on a document containing `_id`, Pydantic's default behavior (ignore extra) protects now but is undocumented; add `extra="ignore"` to `TenantDocument.model_config` for explicitness.
- **Two identity fields (`_id` MongoDB-auto + `tenant_id` app-generated str)** — documented architectural decision in Dev Notes; `tenant_id` has no unique index at the DB level; add `create_index([("tenant_id", 1)], unique=True)` when MongoDB index management is formalized.
- **MongoDB connection failure during `create_tenant` returns generic 500 instead of `PROVIDER_UNAVAILABLE`** — auth.py already uses `PROVIDER_UNAVAILABLE` for its DB errors; align `tenant_service.py` to wrap motor exceptions similarly when error-handling patterns are standardized.

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
- **No test exercises real corrupt PDF/DOCX bytes** (`test_parser.py`) — error paths mocked; only TXT corrupt-bytes tested with real code.
- **`agent_dao.find_one` DB timeout → DAO calls in `except` block can suppress original exception** (`ingestion_worker.py:29-57`) — pre-existing pattern.
- **Status split on final ready update** (`ingestion_worker.py:59-64`) — pre-existing inconsistency.
- **DOCX table/header/footer content silently dropped** (`parser.py:36-40`) — beyond story scope.
- **`KeyError` from unknown `chunking_strategy` causes indefinite SQS retry** (`pipeline.py:67`) — spec-mandated.
- **No max document size guard before parsing** (`parser.py:9`) — large S3 objects fully buffered; noted in prior 3-4 review.
- **`_chunk_text` uses hardcoded `chunk_size`/`chunk_overlap` kwargs** (`pipeline.py:68`) — future strategies with different init params will `TypeError`; defer until second strategy added.
