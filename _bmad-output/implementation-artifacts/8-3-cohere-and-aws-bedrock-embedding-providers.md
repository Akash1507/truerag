# Story 8.3: Cohere & AWS Bedrock Embedding Providers

Status: done

## Story

As a Tenant Developer,
I want to configure my agent to use Cohere or AWS Bedrock for embeddings, with hard protection against serving degraded results after a provider switch,
so that I can choose the embedding provider that best fits my quality and cost requirements without risking silent dimension mismatch failures (FR22, FR56).

## Acceptance Criteria

**AC1 — Cohere embedder calls Cohere Embed API and returns vectors**
Given an agent configured with `embedding_provider: cohere`
When `CohereEmbedder.embed(texts)` is called
Then the Cohere Embed API is called; a list of float vectors of consistent dimension is returned; the API key is read from Secrets Manager via `secrets.py`; transient failures retry via `@retry`

**AC2 — Bedrock embedder calls AWS Bedrock embeddings API**
Given an agent configured with `embedding_provider: bedrock`
When `BedrockEmbedder.embed(texts)` is called
Then the AWS Bedrock embeddings API is called via `aioboto3`; AWS credentials are read from Secrets Manager; vectors of consistent dimension are returned

**AC3 — Embedding provider switch blocks queries until reindex**
Given an agent switches `embedding_provider` when existing chunks are already indexed
When the first query executes before a reindex has been triggered
Then HTTP 422 Unprocessable Entity is returned with `ErrorCode.EMBEDDING_MODEL_MISMATCH` — degraded results from dimension-mismatched vectors are never silently returned

**AC4 — Both providers registered and mismatch warning fires**
Given both new embedders registered in `EMBEDDING_REGISTRY`
When an agent switches `embedding_provider` via `PATCH /v1/agents/{agent_id}/config`
Then the mismatch warning from Story 2.5 fires (FR56) and the agent's query path blocks until a reindex completes

## Tasks / Subtasks

- [x] **Task 1: Add Cohere config to `app/core/config.py`** (AC: 1)
  - [x] Add `cohere_api_key_secret_name: str = "truerag/cohere/api_key"` to `Settings`
  - [x] Add `cohere_embedding_model: str = "embed-english-v3.0"` to `Settings`

- [x] **Task 2: Implement `app/providers/embedding/cohere.py`** (AC: 1)
  - [x] Class `CohereEmbedder(EmbeddingProvider)` — implements `embed(texts) -> list[list[float]]`
  - [x] `__init__(self, aws_session: aioboto3.Session | None = None) -> None`: store session and `self.settings = get_settings()`
  - [x] Use `cohere` Python SDK: `import cohere`; async client: `cohere.AsyncClient`
  - [x] `embed(texts)`: fetch API key via `get_secret(settings.cohere_api_key_secret_name)` → create client → call `client.embed(texts=texts, model=settings.cohere_embedding_model, input_type="search_document")` → return `[e for e in response.embeddings]`
  - [x] Apply `@retry(max_attempts=3, backoff_factor=2, retry_on=(cohere.CohereError,))` on the inner call
  - [x] Handle `cohere.CohereError` → raise `ProviderUnavailableError`; close client in `finally`
  - [x] Return type: `list[list[float]]` — each embedding is `list[float]`

- [x] **Task 3: Implement `app/providers/embedding/bedrock.py`** (AC: 2)
  - [x] Class `BedrockEmbedder(EmbeddingProvider)` — implements `embed(texts) -> list[list[float]]`
  - [x] `__init__(self, aws_session: aioboto3.Session | None = None) -> None`: store session
  - [x] Use `aioboto3` — call `session.client("bedrock-runtime")` as async context manager
  - [x] Default model: `amazon.titan-embed-text-v1` (configurable via `Settings.bedrock_embedding_model_id`)
  - [x] Add `bedrock_embedding_model_id: str = "amazon.titan-embed-text-v1"` to config
  - [x] `embed(texts)`: for each text, call `client.invoke_model(modelId=settings.bedrock_embedding_model_id, body=json.dumps({"inputText": text}))` — parse response `body["embedding"]`; collect all into `list[list[float]]`; wrap in `ProviderUnavailableError` on exception
  - [x] `@retry` on transient exceptions: `aioboto3` / `botocore.exceptions.ClientError` with retryable status codes

- [x] **Task 4: Add `EmbeddingModelMismatchError` to `app/core/errors.py`** (AC: 3)
  - [x] Add new `ErrorCode.EMBEDDING_MODEL_MISMATCH` is ALREADY in `app/core/errors.py` — verify
  - [x] Add new exception class:
    ```python
    class EmbeddingModelMismatchError(TrueRAGError):
        def __init__(self, message: str = "Embedding model mismatch — reindex required") -> None:
            super().__init__(code=ErrorCode.EMBEDDING_MODEL_MISMATCH, message=message, http_status=422)
    ```

- [x] **Task 5: Block queries when `embedding_provider` has been changed without reindex** (AC: 3, 4)
  - [x] In `app/services/agent_service.py`, the mismatch warning for `embedding_provider` change already fires (story 2.5)
  - [x] Add a new flag on `AgentDocument`: `embedding_provider_mismatch: bool = False` — set to `True` when `embedding_provider` changes while docs exist
  - [x] In `app/models/agent.py`, add `embedding_provider_mismatch: bool = False` field to `AgentDocument`
  - [x] In `app/services/agent_service.py`, when `embedding_provider` changes with existing docs: set `update_dict["embedding_provider_mismatch"] = True`
  - [x] In `app/services/agent_service.py`, when a reindex completes (story 4.6 code path): set `embedding_provider_mismatch = False` — find the reindex trigger in `app/api/v1/documents.py` or `ingestion_service.py` and add the reset
  - [x] In `app/pipelines/query/pipeline.py` or `app/services/query_service.py`, check before retrieval: `if agent.embedding_provider_mismatch: raise EmbeddingModelMismatchError()`
  - [x] Map `EmbeddingModelMismatchError` in `app/core/exception_handlers.py` (already handles `TrueRAGError` subclasses via `http_status`)

- [x] **Task 6: Register both providers in `app/providers/registry.py`** (AC: 4)
  - [x] Import `CohereEmbedder`, `BedrockEmbedder`
  - [x] Add `"cohere": CohereEmbedder` and `"bedrock": BedrockEmbedder` to `EMBEDDING_REGISTRY`

- [x] **Task 7: Write unit tests** (AC: 1, 2, 3)
  - [x] `tests/providers/test_cohere_embedder.py`:
    - Mock `cohere.AsyncClient.embed` — verify called with correct texts and model
    - Test retry on `CohereError` — mock raises error once, succeeds second time
    - Test `ProviderUnavailableError` raised after exhausted retries
  - [x] `tests/providers/test_bedrock_embedder.py`:
    - Mock `aioboto3.Session.client` as async context manager
    - Verify `invoke_model` called with correct `modelId` and body
    - Test `ProviderUnavailableError` on exception
  - [x] `tests/services/test_query_service.py` or `tests/pipelines/test_query_pipeline.py`:
    - Test query blocked with 422 when `embedding_provider_mismatch=True`
    - Test query succeeds when `embedding_provider_mismatch=False`

- [x] **Task 8: Add ADR for new embedding providers** (AC: 1, 2)
  - [x] Create `docs/adrs/adr-013-cohere-bedrock-embedding-providers.md`
  - [x] Document: mismatch detection mechanism and query-blocking design

- [x] **Task 9: Run regression tests** (AC: 4)
  - [x] `pytest tests/ -x -v --ignore=tests/integration`
  - [x] `mypy --strict app/providers/embedding/cohere.py app/providers/embedding/bedrock.py`

## Dev Notes

### Existing Patterns — Follow Exactly

**OpenAI embedder reference** (`app/providers/embedding/openai.py`):
```python
class OpenAIEmbedder(EmbeddingProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=(...))
    async def _embed_with_retry(self, client, texts): ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        api_key = await get_secret(self.settings.openai_api_key_secret_name, session=self.aws_session)
        client = AsyncOpenAI(api_key=api_key)
        try:
            return await self._embed_with_retry(client, texts)
        except ...: raise ProviderUnavailableError(...)
        finally: await client.close()
```
Follow this exact pattern — `__init__` takes `aws_session`, get_secret at embed-time, retry decorator on inner method, close client in finally.

**Abstract EmbeddingProvider interface** (locked):
```python
async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

**Retry decorator usage** (`app/utils/retry.py`):
```python
from app.utils.retry import retry
@retry(max_attempts=3, backoff_factor=2, retry_on=(ExceptionType1, ExceptionType2))
async def _embed_with_retry(self, ...): ...
```

**Secrets access** (always at operation time, never at init):
```python
api_key = await get_secret(self.settings.cohere_api_key_secret_name, session=self.aws_session)
```

### VALID_EMBEDDING_PROVIDERS already includes "cohere" and "bedrock"
`app/models/agent.py` has `VALID_EMBEDDING_PROVIDERS: frozenset[str] = frozenset({"openai", "cohere", "bedrock"})` — no change needed.

### Mismatch Detection — Current State

Story 2.5 (`app/services/agent_service.py` around line 194) already:
1. Detects when `embedding_provider` changes on a PATCH request while docs exist
2. Appends a human-readable warning to the response

What story 8.3 adds:
- The `embedding_provider_mismatch: bool` flag on `AgentDocument` (persisted in MongoDB)
- Setting it to `True` on provider change with existing docs
- Resetting it to `False` when reindex completes (developer-triggered reindex in story 4.6)
- Query-time check that raises `EmbeddingModelMismatchError` (HTTP 422)

### Reindex Reset Point

Find where reindex completes in `app/api/v1/documents.py` (the endpoint for developer-triggered reindex). After the reindex SQS message is enqueued and confirmed, set `embedding_provider_mismatch = False` on the agent. Or better: in `app/workers/ingestion_worker.py` after a successful full reindex job, reset the flag.

### Cohere SDK

```python
import cohere
client = cohere.AsyncClient(api_key=api_key)
response = await client.embed(texts=texts, model=model, input_type="search_document")
embeddings = response.embeddings  # list[list[float]]
```

Add `cohere>=4.0.0` to `requirements.txt`.

### Bedrock Embedding

```python
import json
import aioboto3
session = aioboto3.Session()
async with session.client("bedrock-runtime", region_name=settings.aws_region) as client:
    for text in texts:
        response = await client.invoke_model(
            modelId=settings.bedrock_embedding_model_id,
            body=json.dumps({"inputText": text}),
            contentType="application/json",
            accept="application/json",
        )
        body = json.loads(await response["body"].read())
        vectors.append(body["embedding"])
```

No extra dependency — `aioboto3` already in `requirements.txt`.

### Architecture Guardrails

- NEVER call Secrets Manager directly — use `app/utils/secrets.py`
- NEVER silently return dimension-mismatched vectors — must raise `EmbeddingModelMismatchError`
- NEVER use `datetime.utcnow()` — use `datetime.now(UTC)`
- NEVER add routes to `main.py`
- Provider init must accept `aws_session: aioboto3.Session | None = None` for test mocking

### Project Structure

```
app/
  core/
    config.py                     MODIFY: add cohere_api_key_secret_name, cohere_embedding_model,
                                          bedrock_embedding_model_id
    errors.py                     MODIFY: add EmbeddingModelMismatchError class
  models/
    agent.py                      MODIFY: add embedding_provider_mismatch: bool = False field
  services/
    agent_service.py              MODIFY: set embedding_provider_mismatch=True on provider change
  pipelines/query/
    pipeline.py                   MODIFY: check embedding_provider_mismatch before retrieval
  providers/
    registry.py                   MODIFY: import + register CohereEmbedder, BedrockEmbedder
    embedding/
      cohere.py                   NEW: CohereEmbedder
      bedrock.py                  NEW: BedrockEmbedder
      __init__.py                 MODIFY: export new embedders

tests/providers/
  test_cohere_embedder.py         NEW: unit tests with mocked cohere client
  test_bedrock_embedder.py        NEW: unit tests with mocked aioboto3

docs/adrs/
  adr-013-cohere-bedrock-embedding-providers.md  NEW

requirements.txt                  MODIFY: add cohere>=4.0.0
```

### References

- Abstract interface: `app/interfaces/embedding_provider.py`
- Reference implementation: `app/providers/embedding/openai.py`
- Registry: `app/providers/registry.py`
- Config: `app/core/config.py`
- Secrets: `app/utils/secrets.py`
- Retry: `app/utils/retry.py`
- Errors: `app/core/errors.py` — `ErrorCode.EMBEDDING_MODEL_MISMATCH`, `ProviderUnavailableError`
- Agent model: `app/models/agent.py`
- Agent service (mismatch detection): `app/services/agent_service.py` ~line 194
- Query pipeline (where to add check): `app/pipelines/query/pipeline.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References
- `.venv/bin/pytest -q tests/providers/test_cohere_embedder.py tests/providers/test_bedrock_embedder.py tests/pipelines/test_query_pipeline.py tests/services/test_agent_service_dao.py tests/services/test_ingestion_service_dao.py tests/providers/test_registry.py tests/core/test_errors.py`
- `.venv/bin/mypy --strict app/providers/embedding/cohere.py app/providers/embedding/bedrock.py`
- `.venv/bin/pytest tests/ -x -v --ignore=tests/integration`

### Completion Notes List
- Added `CohereEmbedder` and `BedrockEmbedder` providers with retry behavior, provider error wrapping, and registry integration.
- Added `EmbeddingModelMismatchError`, persisted `embedding_provider_mismatch` state, and query-path blocking with HTTP 422 semantics when mismatch is active.
- Wired mismatch flag lifecycle: set on embedding provider change with existing docs and reset on successful reindex enqueue.
- Added dedicated unit tests for both providers and mismatch blocking behavior; regression and strict typing checks pass.

### File List
- app/core/config.py
- app/core/errors.py
- app/models/agent.py
- app/pipelines/query/pipeline.py
- app/providers/embedding/__init__.py
- app/providers/embedding/cohere.py
- app/providers/embedding/bedrock.py
- app/providers/registry.py
- app/services/agent_service.py
- app/services/ingestion_service.py
- tests/providers/test_cohere_embedder.py
- tests/providers/test_bedrock_embedder.py
- tests/pipelines/test_query_pipeline.py
- tests/services/test_agent_service_dao.py
- tests/services/test_ingestion_service_dao.py
- tests/providers/test_registry.py
- tests/core/test_errors.py
- tests/core/test_dependencies.py
- pyproject.toml
- docs/adrs/adr-013-cohere-bedrock-embedding-providers.md

### Change Log
- 2026-05-03: Implemented Story 8.3 with Cohere and Bedrock embedders, embedding provider mismatch guardrail, query blocking until reindex, and full test/regression validation.
