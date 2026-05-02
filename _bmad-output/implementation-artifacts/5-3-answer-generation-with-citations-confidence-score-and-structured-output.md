# Story 5.3: Answer Generation with Citations, Confidence Score & Structured Output

Status: done

## Story

As a Service Consumer,
I want a generated answer with source citations, a confidence score, and optional structured JSON output returned for every query,
So that I can present grounded, verifiable answers to end users with full traceability back to source documents (FR32, FR33, FR34).

## Acceptance Criteria

**AC1 — AnthropicLLMProvider generates answer via registry:**
**Given** retrieved chunks are passed to `app/pipelines/query/generator.py`
**When** `AnthropicLLMProvider.generate(prompt, context)` is called
**Then** the Anthropic API key is read from AWS Secrets Manager via `secrets.py` at call time; a generated answer string is returned; the provider is resolved through `LLM_REGISTRY["anthropic"]` — never directly instantiated

**AC2 — Complete response envelope:**
**Given** generation completes
**When** the query response is assembled
**Then** it contains `answer` (string), `confidence` (float 0.0–1.0 derived from retrieval similarity scores), `citations` (array of `{document_name, chunk_text, page_reference}`), `latency_ms` (integer); HTTP 200 is returned with this exact schema

**AC3 — Structured JSON output mode:**
**Given** a query request with `{"query": "...", "output_format": "json"}`
**When** generation completes
**Then** the `answer` field contains a valid JSON string rather than prose; the full response envelope structure (`answer`, `confidence`, `citations`, `latency_ms`) remains unchanged

**AC4 — Citations grounded in retrieved chunks:**
**Given** `top_k` retrieved chunks
**When** citations are assembled
**Then** every citation references a chunk actually used in the generation context — no hallucinated citations; each citation includes `document_name`, `chunk_text`, and `page_reference`

**AC5 — Retry and error propagation:**
**Given** the Anthropic API call fails with a transient error
**When** the retry decorator handles it
**Then** up to 3 retries with exponential backoff; on exhaustion `ProviderUnavailableError` is raised and HTTP 503 is returned to the caller

## Tasks / Subtasks

- [x] Task 1: Add `anthropic` dependency and `anthropic_api_key_secret_name` setting (AC1)
  - [x] 1.1 Add `"anthropic>=0.30.0"` to `dependencies` in `pyproject.toml`
  - [x] 1.2 Add `anthropic_api_key_secret_name: str = "truerag/anthropic/api_key"` to `Settings` class in `app/core/config.py`

- [x] Task 2: Add `output_format` field to `QueryRequest` model (AC3)
  - [x] 2.1 Add `output_format: Literal["text", "json"] | None = None` to `QueryRequest` in `app/models/query.py`
  - [x] 2.2 Import `Literal` from `typing` in `app/models/query.py`

- [x] Task 3: Implement `AnthropicLLMProvider` (AC1, AC5)
  - [x] 3.1 Create `app/providers/llm/anthropic.py` implementing `LLMProvider.generate(prompt, context) -> str`
  - [x] 3.2 Read API key via `get_secret(settings.anthropic_api_key_secret_name)` at call time — never cached
  - [x] 3.3 Use `@retry(max_attempts=3, backoff_factor=2, retry_on=(anthropic.RateLimitError, anthropic.APITimeoutError, anthropic.InternalServerError))` on inner call method
  - [x] 3.4 Raise `ProviderUnavailableError` on retry exhaustion
  - [x] 3.5 Close `AsyncAnthropic` client in `finally` block

- [x] Task 4: Register provider in `LLM_REGISTRY` (AC1)
  - [x] 4.1 Import `AnthropicLLMProvider` in `app/providers/registry.py`
  - [x] 4.2 Add `"anthropic": AnthropicLLMProvider` to `LLM_REGISTRY`

- [x] Task 5: Create `app/pipelines/query/generator.py` (AC1, AC3, AC4)
  - [x] 5.1 Implement `generate_answer(query, chunks, llm_provider, output_format) -> str`
  - [x] 5.2 Build numbered context string from `chunks[i].text` for each chunk
  - [x] 5.3 Construct system + user prompt; for `output_format="json"` inject JSON-only instruction
  - [x] 5.4 Resolve LLM provider through `LLM_REGISTRY` — never instantiate directly
  - [x] 5.5 Log `generation_complete` structured event with chunk_count and provider

- [x] Task 6: Wire generator into `run_query_pipeline` (AC2, AC3, AC4)
  - [x] 6.1 Add `output_format: str | None = None` parameter to `run_query_pipeline` signature
  - [x] 6.2 After `_execute_retrieval`, call `_execute_generation(scrubbed_query, results, agent, output_format)`
  - [x] 6.3 Compute `confidence` as `mean(result.score for result in results)` clamped to `[0.0, 1.0]`; return `0.0` when `results` is empty
  - [x] 6.4 Build `citations` from actual chunks passed to LLM (same `results` list)
  - [x] 6.5 Return `QueryResponse(answer=answer, confidence=confidence, citations=citations, latency_ms=0)` from `_execute_retrieval` / pass answer into model_copy

- [x] Task 7: Thread `output_format` through `query_service.py` (AC3)
  - [x] 7.1 Pass `output_format=request.output_format` from `handle_query` to `run_query_pipeline`

- [x] Task 8: Tests (AC1–AC5)
  - [x] 8.1 Create `tests/providers/llm/__init__.py` (empty)
  - [x] 8.2 Create `tests/providers/llm/test_anthropic.py` — mock `get_secret` + `AsyncAnthropic`; test normal generation, retry exhaustion → `ProviderUnavailableError`, JSON mode prompt
  - [x] 8.3 Update `tests/pipelines/test_query_pipeline.py` — add tests for answer populated, confidence computed from scores, output_format threaded, empty results → confidence 0.0
  - [x] 8.4 Update `tests/services/test_query_service.py` — assert `output_format` propagated to pipeline call
  - [x] 8.5 Run full suite: `pytest` must pass at ≥225 tests (regression gate)

## Dev Notes

### Critical: `anthropic` Package Not Yet in Dependencies

`pyproject.toml` currently has NO `anthropic` entry. **Must add it before any import or the app will fail to start.**

```toml
# pyproject.toml — add to dependencies list
"anthropic>=0.30.0",
```

Then reinstall: `uv pip install -e .`

---

### Critical: `anthropic_api_key_secret_name` Not in Settings

`app/core/config.py` has `openai_api_key_secret_name` but no Anthropic equivalent. **Must add before implementing the provider.**

```python
# app/core/config.py — add to Settings class alongside openai_api_key_secret_name
anthropic_api_key_secret_name: str = "truerag/anthropic/api_key"
```

---

### Critical: `output_format` Missing from `QueryRequest`

The AC requires `{"query": "...", "output_format": "json"}` but `app/models/query.py` has no such field. **Must add before writing pipeline code.**

```python
# app/models/query.py — final shape
from typing import Annotated, Literal
from pydantic import BaseModel, Field, StringConstraints

class QueryRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    top_k: int | None = Field(default=None, ge=1, le=100)
    filters: dict[str, str] | None = None
    output_format: Literal["text", "json"] | None = None  # ADD THIS

class Citation(BaseModel):
    document_name: str
    chunk_text: str
    page_reference: str | None = None

class QueryResponse(BaseModel):
    answer: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    citations: list[Citation]
    latency_ms: int
```

Do NOT change `Citation` or `QueryResponse` — they are correct from Story 5.1.

---

### `AnthropicLLMProvider` — Follow `OpenAIEmbedder` Pattern Exactly

Mirror `app/providers/embedding/openai.py` structure:

```python
# app/providers/llm/anthropic.py
import aioboto3
import anthropic

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.llm_provider import LLMProvider
from app.models.chunk import Chunk
from app.utils.observability import get_logger
from app.utils.retry import retry
from app.utils.secrets import get_secret

logger = get_logger(__name__)

_TRANSIENT_ERRORS = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
)

MODEL = "claude-haiku-4-5-20251001"


class AnthropicLLMProvider(LLMProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=_TRANSIENT_ERRORS)
    async def _generate_with_retry(
        self, client: anthropic.AsyncAnthropic, prompt: str, system: str
    ) -> str:
        msg = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return str(msg.content[0].text)

    async def generate(self, prompt: str, context: list[Chunk]) -> str:
        api_key = await get_secret(
            self.settings.anthropic_api_key_secret_name,
            session=self.aws_session,
        )
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            return await self._generate_with_retry(client, prompt, system="You are a helpful assistant.")
        except _TRANSIENT_ERRORS as exc:
            raise ProviderUnavailableError(f"Anthropic API exhausted retries: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Anthropic API error: {exc}") from exc
        finally:
            await client.close()
```

**`generate()` signature is locked by the abstract interface:** `LLMProvider.generate(self, prompt: str, context: list[Chunk]) -> str`. Do not change it.

---

### `LLM_REGISTRY` — Update `app/providers/registry.py`

The registry currently has `LLM_REGISTRY = {}` (empty, comment says "Populated in Epic 5"). Add:

```python
from app.providers.llm.anthropic import AnthropicLLMProvider

LLM_REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicLLMProvider,
}
```

---

### `generator.py` — Prompt Design and Context Assembly

```python
# app/pipelines/query/generator.py
from app.core.errors import ProviderUnavailableError
from app.models.chunk import Chunk
from app.providers.registry import LLM_REGISTRY
from app.utils.observability import get_logger

logger = get_logger(__name__)


def _build_prompt(query: str, chunks: list[Chunk], output_format: str | None) -> tuple[str, str]:
    context_parts = [f"[{i+1}] {chunk.text}" for i, chunk in enumerate(chunks)]
    context_str = "\n\n".join(context_parts)

    system = "You are a helpful assistant. Answer using only the provided context."
    if output_format == "json":
        system += " Return ONLY a valid JSON object with a single key 'answer' containing your response. No prose, no markdown."

    user_prompt = f"Context:\n{context_str}\n\nQuestion: {query}"
    return system, user_prompt


async def generate_answer(
    query: str,
    chunks: list[Chunk],
    llm_provider_name: str,
    output_format: str | None = None,
) -> str:
    provider_cls = LLM_REGISTRY.get(llm_provider_name)
    if not provider_cls:
        raise ProviderUnavailableError(
            f"LLM provider '{llm_provider_name}' not registered"
        )
    provider = provider_cls()
    system, user_prompt = _build_prompt(query, chunks, output_format)
    full_prompt = user_prompt  # system passed separately to provider

    answer = await provider.generate(full_prompt, chunks)

    logger.info(
        "generation_complete",
        extra={
            "operation": "generation",
            "extra_data": {
                "provider": llm_provider_name,
                "chunk_count": len(chunks),
                "output_format": output_format or "text",
            },
        },
    )
    return answer
```

**Note:** The `LLMProvider.generate(prompt, context)` interface passes system instruction via `prompt` or separately depending on implementation. The `AnthropicLLMProvider._generate_with_retry` accepts both `prompt` (user message) and `system` (system message). Design your generator call to accommodate this. One clean approach: encode the full prompt (system + context + question) as a single `prompt` string passed to `generate()`, since the interface only guarantees one `prompt` param.

---

### Pipeline Changes — `app/pipelines/query/pipeline.py`

Add `_execute_generation` step after `_execute_retrieval`. The pipeline currently ends retrieval with `answer=""`, `confidence=0.0`. This story fills them in.

**Confidence formula:** `mean(r.score for r in results)` where `VectorResult.score` is the cosine similarity from pgvector (range 0.0–1.0). When `results` is empty, return `0.0`.

**Key addition to `run_query_pipeline`:**

```python
async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
    output_format: str | None = None,          # ADD
) -> QueryResponse:
    t0 = time.perf_counter()
    scrubbed_query = scrub_pii(query)
    ...
    retrieval_response = await _execute_retrieval(...)
    answer = await _execute_generation(
        scrubbed_query=scrubbed_query,
        results=...,          # VectorResult list from retrieval
        agent=agent,
        output_format=output_format,
    )
    confidence = _compute_confidence(results)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    return QueryResponse(
        answer=answer,
        confidence=confidence,
        citations=retrieval_response.citations,
        latency_ms=latency_ms,
    )
```

**Do not** break the existing `latency_ms` measurement — it already wraps the full pipeline.

---

### `query_service.py` — Thread `output_format`

```python
# app/services/query_service.py — update handle_query call
return await run_query_pipeline(
    query=request.query,
    top_k=request.top_k or agent.top_k,
    agent=agent,
    filters=request.filters,
    output_format=request.output_format,   # ADD
)
```

---

### Test Pattern for `AnthropicLLMProvider`

Mirror the asyncpg pool mock pattern from pgvector tests:

```python
# tests/providers/llm/test_anthropic.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.providers.llm.anthropic import AnthropicLLMProvider
from app.core.errors import ProviderUnavailableError


@pytest.mark.asyncio
async def test_generate_returns_answer():
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text="The answer is 42.")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=fake_message)
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-ant-test")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        provider = AnthropicLLMProvider()
        result = await provider.generate("What is 6*7?", [])
        assert result == "The answer is 42."


@pytest.mark.asyncio
async def test_generate_retry_exhaustion_raises_provider_unavailable():
    import anthropic as anthropic_lib
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic_lib.RateLimitError(
            message="rate limit", response=MagicMock(status_code=429), body={}
        )
    )
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-ant-test")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("asyncio.sleep", AsyncMock()),
    ):
        provider = AnthropicLLMProvider()
        with pytest.raises(ProviderUnavailableError):
            await provider.generate("query", [])
```

---

### Test Pattern for Pipeline Generation Step

```python
# tests/pipelines/test_query_pipeline.py — add to existing file
@pytest.mark.asyncio
async def test_pipeline_answer_populated_from_llm(mock_vector_results):
    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": AsyncMock(...)}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": AsyncMock(...)}),
        patch("app.pipelines.query.pipeline.generate_answer", AsyncMock(return_value="Generated answer")),
    ):
        response = await run_query_pipeline(query="test", top_k=3, agent=_make_agent())
        assert response.answer == "Generated answer"
        assert 0.0 <= response.confidence <= 1.0
        assert len(response.citations) > 0


@pytest.mark.asyncio
async def test_pipeline_confidence_zero_when_no_results():
    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {...}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {...}),
        patch("app.pipelines.query.pipeline.generate_answer", AsyncMock(return_value="")),
    ):
        # mock vector store returns empty list
        response = await run_query_pipeline(query="test", top_k=3, agent=_make_agent())
        assert response.confidence == 0.0
```

---

### Architecture Guardrails — DO NOT VIOLATE

| Rule | What it means here |
|------|--------------------|
| Never bypass provider registry | Resolve `AnthropicLLMProvider` via `LLM_REGISTRY["anthropic"]` — never `AnthropicLLMProvider()` directly in service/pipeline code |
| Never call Secrets Manager directly | Always `get_secret(settings.anthropic_api_key_secret_name)` via `app/utils/secrets.py` |
| Never cache secrets at startup | Read API key inside `generate()` on every call — never in `__init__` |
| Never implement retry inline | Always use `@retry` from `app/utils/retry.py` |
| Never use `print()` or stdlib `logging` | Always `get_logger(__name__)` from `app/utils/observability.py` |
| Never hardcode error strings | Use `ProviderUnavailableError` from `app/core/errors.py` |

---

### Current Pipeline State (after Story 5.2)

`app/pipelines/query/pipeline.py` currently:
- Scrubs PII with `scrub_pii(query)`
- Embeds query via `EMBEDDING_REGISTRY`
- Queries pgvector via `VECTOR_STORE_REGISTRY` with namespace `{tenant_id}_{agent_id}`
- Maps `VectorResult` → `Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)`
- Returns stub: `answer=""`, `confidence=0.0`, real `citations`, `latency_ms` from timing

This story: replaces stub `answer` and `confidence` with real values.

---

### `VectorResult` Schema (for confidence and citation mapping)

```python
class VectorResult(BaseModel):
    id: str
    score: float          # cosine similarity 0.0–1.0 from pgvector
    metadata: ChunkMetadata
    text: str
```

Confidence = `mean([r.score for r in results])` clamped to `[0.0, 1.0]`. Empty results → `0.0`.

Citations remain mapped from `results` (same as 5.2): `document_name=result.metadata.document_id`, `chunk_text=result.text`, `page_reference=None`.

---

### `Chunk` vs `VectorResult` — Interface Boundary

`LLMProvider.generate(prompt: str, context: list[Chunk]) -> str` takes `list[Chunk]`.
`_execute_retrieval` returns `list[VectorResult]`.

Convert before calling `generate`:
```python
chunks = [Chunk(text=r.text, metadata=r.metadata) for r in results]
```

Do this conversion in `generator.py` or in the pipeline step — not in `AnthropicLLMProvider.generate()`.

---

### `agent.llm_provider` Field

`AgentDocument` already has a `llm_provider` field (set during Epic 2 agent creation). Use `agent.llm_provider` as the registry key in `generator.py`:

```python
provider_cls = LLM_REGISTRY.get(agent.llm_provider)
```

Pass `agent.llm_provider` from `pipeline.py` to `generate_answer()`.

---

### Regression Gate

Current passing: `225 passed, 9 skipped`. Do not reduce this count. All prior query route, service, and pipeline tests must still pass. The stub `answer=""` tests from 5.1/5.2 may need updating to mock the new `generate_answer` call — patch it at pipeline level rather than changing test assertions about stub values.

### Project Structure Notes

```
app/
  core/
    config.py                    ← ADD anthropic_api_key_secret_name
  models/
    query.py                     ← ADD output_format to QueryRequest
  providers/
    llm/
      __init__.py                (exists, empty)
      anthropic.py               ← CREATE
    registry.py                  ← ADD AnthropicLLMProvider to LLM_REGISTRY
  pipelines/
    query/
      __init__.py                (exists, empty)
      pipeline.py                ← MODIFY: add generation step, confidence, output_format param
      generator.py               ← CREATE
  services/
    query_service.py             ← MODIFY: thread output_format

tests/
  providers/
    llm/
      __init__.py                ← CREATE (empty)
      test_anthropic.py          ← CREATE
  pipelines/
    test_query_pipeline.py       ← MODIFY: add generation tests
  services/
    test_query_service.py        ← MODIFY: assert output_format propagation

pyproject.toml                   ← ADD anthropic>=0.30.0
```

### References

- [Source: epics.md#Epic 5 Story 5.3] — user story, acceptance criteria, technical requirements
- [Source: architecture.md#Technical Constraints] — Anthropic as pluggable LLM provider; secrets read at operation time; never bypass registry
- [Source: architecture.md#Enforcement Guidelines] — all enforcement rules; `LLMProvider` covered explicitly
- [Source: app/interfaces/llm_provider.py] — `LLMProvider.generate(prompt: str, context: list[Chunk]) -> str` locked signature
- [Source: app/providers/registry.py] — `LLM_REGISTRY` currently empty; `EMBEDDING_REGISTRY`, `VECTOR_STORE_REGISTRY` for lookup pattern
- [Source: app/providers/embedding/openai.py] — `OpenAIEmbedder` — exact pattern to mirror for `AnthropicLLMProvider`
- [Source: app/pipelines/query/pipeline.py] — current pipeline state after Story 5.2; `_execute_retrieval` returns `QueryResponse` with stub answer
- [Source: app/models/query.py] — current `QueryRequest` (no output_format), `QueryResponse`, `Citation` shapes
- [Source: app/models/chunk.py] — `VectorResult.score`, `Chunk` schema, `ChunkMetadata`
- [Source: app/utils/secrets.py] — `get_secret(name, session)` signature
- [Source: app/utils/retry.py] — `@retry(max_attempts, backoff_factor, retry_on)` decorator
- [Source: app/core/errors.py] — `ProviderUnavailableError` (HTTP 503)
- [Source: app/core/config.py] — `Settings.openai_api_key_secret_name` pattern; add `anthropic_api_key_secret_name`
- [Source: pyproject.toml] — `anthropic` not yet in deps; must add `anthropic>=0.30.0`
- [Source: 5-2 story completion notes] — `225 passed, 9 skipped` regression baseline; `VectorResult → Citation` mapping pattern

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex)

### Debug Log References

(none)

### Completion Notes List

- Added Anthropic provider dependency and settings key for runtime Secrets Manager lookup.
- Implemented `AnthropicLLMProvider` with retry/backoff on transient Anthropic errors and `ProviderUnavailableError` propagation on exhaustion/failure.
- Registered `"anthropic"` in `LLM_REGISTRY`.
- Added query generation module to build grounded prompts, support JSON output mode, resolve provider via registry, and log generation telemetry.
- Updated query pipeline to run retrieval + generation, compute confidence from retrieval scores, preserve citation grounding, and thread `output_format`.
- Updated query service to pass `output_format` from request to pipeline.
- Added/updated tests for Anthropic provider behavior, pipeline generation/confidence/output_format behavior, and service output_format propagation.
- Full suite result: `236 passed, 9 skipped`.

### File List

- pyproject.toml
- app/core/config.py
- app/models/query.py
- app/providers/registry.py
- app/providers/llm/anthropic.py
- app/pipelines/query/generator.py
- app/pipelines/query/pipeline.py
- app/services/query_service.py
- tests/providers/llm/__init__.py
- tests/providers/llm/test_anthropic.py
- tests/pipelines/test_query_generator.py
- tests/pipelines/test_query_pipeline.py
- tests/services/test_query_service.py
- tests/core/test_dependencies.py
- tests/providers/test_registry.py

### Review Findings

- [x] [Review][Patch] JSON output mode is not enforced or validated [app/pipelines/query/generator.py:17]
- [x] [Review][Patch] Empty retrieval still calls the LLM with no grounding context [app/pipelines/query/pipeline.py:38]
- [x] [Review][Patch] Pipeline type annotations contradict the actual return values [app/pipelines/query/pipeline.py:16]
- [x] [Review][Patch] Anthropic response parsing assumes a first text block always exists [app/providers/llm/anthropic.py:27]
