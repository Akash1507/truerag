# Story 4.2: OpenAI Embedding Generation

Status: done

## Story

As a Tenant Developer,
I want each chunk embedded into a dense vector using the OpenAI embeddings API,
so that chunks are represented as vectors ready for similarity search in the vector store.

## Acceptance Criteria

**AC1:** Given an agent configured with `embedding_provider: openai`, when `OpenAIEmbedder.embed(texts)` is called with a list of chunk texts, then the OpenAI embeddings API is called; a list of float vectors of consistent dimension is returned, one per input text; the API key is read from AWS Secrets Manager via `secrets.py` at call time — never from an environment variable or cached value.

**AC2:** Given the OpenAI API call fails with a transient error (rate limit, timeout), when the retry decorator handles it, then the call is retried up to 3 times with exponential backoff via `@retry` from `app/utils/retry.py`; on exhaustion `ProviderUnavailableError` is raised.

**AC3:** Given `OpenAIEmbedder` is instantiated, when the registry resolves the embedder, then it is resolved through `EMBEDDING_REGISTRY["openai"]` via the provider registry — never directly instantiated in the pipeline.

**AC4:** Given chunks are embedded successfully, when the ingestion pipeline completes embedding, the vectors are attached to the chunks and passed to the next stage (`_embed_upsert_stub` placeholder must be updated to handle vectors).

## Dev Agent Guardrails

### Technical Requirements

1. Use the `openai` Python SDK (`openai>=1.0.0`).
2. The embedding model used should be `text-embedding-3-small`.
3. Secret name for the API key in Secrets Manager should be defined as a constant or passed via configuration. For this project, assume the secret name is `"truerag/openai/api_key"` (or verify against `settings.openai_api_key_secret_name` if you choose to add it to settings). We'll add `openai_api_key_secret_name: str = "truerag/openai/api_key"` to `app/core/config.py`.
4. Ensure you use the `AsyncOpenAI` client.
5. In `app/pipelines/ingestion/pipeline.py`, you need to resolve the embedder via `EMBEDDING_REGISTRY[agent.embedding_provider]`. Pass the AWS session to it if it needs to fetch the secret. However, `EmbeddingProvider.embed` signature is `embed(self, texts: list[str]) -> list[list[float]]`, so the secret retrieval should happen inside `embed()` or the embedder class must have a way to access the session. It's recommended to pass `aws_session` to the `__init__` of `OpenAIEmbedder`.

### Architecture Compliance

1. **Registry Pattern**: Do not instantiate `OpenAIEmbedder` directly in `pipeline.py`. Use `EMBEDDING_REGISTRY`.
2. **Secrets**: Use `app/utils/secrets.py:get_secret(name, session)` to get the API key.
3. **Retry Decorator**: Use `@retry(max_attempts=3, backoff_factor=2, retry_on=(openai.RateLimitError, openai.APITimeoutError, openai.InternalServerError))` from `app/utils/retry.py`. (You'll need to import these errors from `openai`). Note that `@retry` should catch exceptions and if exhausted, you should explicitly wrap the last exception in a `ProviderUnavailableError`. Wait, the `retry` decorator raises the original exception on exhaustion. You might need to wrap `embed` logic in a try-except to raise `ProviderUnavailableError` after the retry decorator exhausts.
4. **Error Handling**: Use `ProviderUnavailableError` from `app/core/errors.py`.

### Library & Framework Requirements

- `openai>=1.0.0` to be added to `requirements.txt`.
- `AsyncOpenAI` client from `openai`.

### File Structure Requirements

- **Create:** `app/providers/embedding/openai.py` for the `OpenAIEmbedder` implementation.
- **Create:** `tests/providers/embedding/test_openai.py` for unit tests.
- **Update:** `app/providers/registry.py` to add `OpenAIEmbedder` to `EMBEDDING_REGISTRY`.
- **Update:** `app/core/config.py` to add `openai_api_key_secret_name` to `Settings`.
- **Update:** `app/pipelines/ingestion/pipeline.py` to resolve embedder and generate vectors.
- **Update:** `app/interfaces/embedding_provider.py` is stable, do not modify.

### Testing Requirements

- Mock `get_secret` to return a fake API key.
- Mock `AsyncOpenAI.embeddings.create` to return mock embedding responses.
- Test successful embedding returning `list[list[float]]`.
- Test transient error (e.g., rate limit) retries 3 times before raising `ProviderUnavailableError`.
- Test that `get_secret` is called inside the embed method (or properly configured) and not cached globally.

## Tasks/Subtasks

- [x] Task 1: Update `app/core/config.py` to add `openai_api_key_secret_name` to `Settings`
- [x] Task 2: Create `app/providers/embedding/openai.py` with `OpenAIEmbedder` implementation
- [x] Task 3: Update `app/providers/registry.py` to register `OpenAIEmbedder`
- [x] Task 4: Update `app/pipelines/ingestion/pipeline.py` to use the embedder
- [x] Task 5: Verify implementation with tests (AC1-AC4)

## Dev Agent Record

### Implementation Plan
- Added `openai_api_key_secret_name` to `Settings` in `app/core/config.py`.
- Implemented `OpenAIEmbedder` in `app/providers/embedding/openai.py` with:
    - `AsyncOpenAI` client.
    - `@retry` decorator for transient errors.
    - `get_secret` for fetching API key at call time.
    - `ProviderUnavailableError` wrapping on exhaustion.
- Updated `Chunk` model to include `vector` field.
- Registered `OpenAIEmbedder` in `app/providers/registry.py`.
- Updated `app/pipelines/ingestion/pipeline.py` to:
    - Resolve embedder from registry.
    - Generate embeddings and attach them to chunks.
    - Pass chunks to the next stage (now `_upsert_to_vector_store_stub`).
- Added unit tests in `tests/providers/embedding/test_openai.py`.
- Updated pipeline tests in `tests/pipelines/ingestion/test_pipeline.py`.

### Debug Log
- 2026-05-01: Implementation complete. All tests passed (4 unit tests, 8 pipeline tests).
- 2026-05-01: Resolved `ModuleNotFoundError` by installing `openai` into the venv via `uv`.
- 2026-05-01: Fixed pipeline tests after renaming `_embed_upsert_stub` and adding `_generate_embeddings`.

### Completion Notes
- Story 4.2 implemented successfully.
- OpenAI embedding generation is now part of the ingestion pipeline.
- Secrets are handled securely via AWS Secrets Manager.
- Robust retry logic is in place.

## File List
- `app/core/config.py`
- `app/models/chunk.py`
- `app/providers/embedding/openai.py`
- `app/providers/registry.py`
- `app/pipelines/ingestion/pipeline.py`
- `requirements.txt`
- `tests/providers/embedding/test_openai.py`
- `tests/pipelines/ingestion/test_pipeline.py`

## Change Log
- 2026-05-01: Initialized implementation.
- 2026-05-01: Completed implementation and testing.

## Previous Story Intelligence

In story 4.1 (`4-1-document-parsing-and-fixed-size-chunking`), we implemented `FixedSizeChunker` and updated `pipeline.py`.
- **Registry Lookup**: `chunker_cls = CHUNKING_REGISTRY[agent.chunking_strategy]` was used. Apply the same pattern for `embedding_provider`.
- **Pipeline Signatures**: `run_ingestion_pipeline` now receives `agent: AgentDocument` and `aws_session: aioboto3.Session`. Use this `aws_session` to pass to the embedder (e.g., via `__init__` when instantiating from registry) so it can retrieve secrets.

## Latest Tech Information

The `openai` SDK >= 1.0.0 uses a completely new client-based architecture.
```python
from openai import AsyncOpenAI
import openai

# Instantiate client
client = AsyncOpenAI(api_key=api_key)

# Create embeddings
response = await client.embeddings.create(
    input=texts,
    model="text-embedding-3-small"
)

# Extract vectors
embeddings = [item.embedding for item in response.data]
```

## Completion Note
Ultimate context engine analysis completed - comprehensive developer guide created.

### Review Findings
- [ ] [Review][Decision] Inefficient Secrets Retrieval — AWS Secrets Manager API is called for every batch, which could cause throttling. However, caching the secret violates AC1. Need a decision on whether to allow a short-lived cache or accept the throttling risk.
- [x] [Review][Patch] Unhandled Large Batch Size [app/pipelines/ingestion/pipeline.py:107]
- [x] [Review][Patch] Missing Provider Registry Validation [app/pipelines/ingestion/pipeline.py:104]

