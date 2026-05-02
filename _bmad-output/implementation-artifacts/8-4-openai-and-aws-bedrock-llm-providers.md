# Story 8.4: OpenAI & AWS Bedrock LLM Providers

Status: done

## Story

As a Tenant Developer,
I want to configure my agent to use OpenAI GPT or AWS Bedrock as its LLM provider,
so that I can choose the generation model that best fits my quality, cost, and data residency requirements (FR27).

## Acceptance Criteria

**AC1 — OpenAI LLM provider calls chat completions API**
Given an agent configured with `llm_provider: openai`
When `OpenAILLMProvider.generate(prompt, context)` is called
Then the OpenAI chat completions API is called; the API key is read from Secrets Manager via `secrets.py`; a generated answer string is returned; transient failures retry via `@retry`

**AC2 — Bedrock LLM provider calls AWS Bedrock inference API**
Given an agent configured with `llm_provider: bedrock`
When `BedrockLLMProvider.generate(prompt, context)` is called
Then the AWS Bedrock inference API is called via `aioboto3`; AWS credentials are read from Secrets Manager; a generated answer string is returned

**AC3 — Both providers registered and backend-agnostic test suite passes**
Given both new LLM providers registered in `LLM_REGISTRY`
When the backend-agnostic LLM provider test suite runs
Then all assertions pass with only the provider backend swapped

## Tasks / Subtasks

- [x] **Task 1: Add OpenAI LLM config to `app/core/config.py`** (AC: 1)
  - [x] `openai_api_key_secret_name` ALREADY EXISTS in `Settings` (used by `OpenAIEmbedder`) — reuse it
  - [x] Add `openai_llm_model: str = "gpt-4o-mini"` to `Settings`

- [x] **Task 2: Implement `app/providers/llm/openai.py`** (AC: 1)
  - [x] Class `OpenAILLMProvider(LLMProvider)` — implements `generate(prompt, context) -> str`
  - [x] `__init__(self, aws_session: aioboto3.Session | None = None) -> None`: store session and `self.settings = get_settings()`
  - [x] Use `openai` SDK (already a dependency for `OpenAIEmbedder`) — `from openai import AsyncOpenAI`
  - [x] `generate(prompt, context)`: fetch API key via `get_secret(settings.openai_api_key_secret_name)` → create `AsyncOpenAI(api_key=key)` → call `client.chat.completions.create(model=settings.openai_llm_model, messages=[{"role": "system", "content": "..."}, {"role": "user", "content": full_prompt}])`
  - [x] `full_prompt`: prepend context chunks as formatted text + prompt (same pattern as Anthropic provider)
  - [x] `@retry(max_attempts=3, backoff_factor=2, retry_on=(openai.RateLimitError, openai.APITimeoutError, openai.InternalServerError))` on inner `_generate_with_retry` method
  - [x] Extract text: `response.choices[0].message.content` — raise `ProviderUnavailableError` if None/empty
  - [x] Close client in `finally` block: `await client.close()`
  - [x] Wrap all OpenAI exceptions as `ProviderUnavailableError`

- [x] **Task 3: Add Bedrock LLM config to `app/core/config.py`** (AC: 2)
  - [x] Add `bedrock_llm_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"` to `Settings`
  - [x] Note: Bedrock uses AWS credentials from the execution environment — no API key secret needed beyond what `aioboto3` handles

- [x] **Task 4: Implement `app/providers/llm/bedrock.py`** (AC: 2)
  - [x] Class `BedrockLLMProvider(LLMProvider)` — implements `generate(prompt, context) -> str`
  - [x] `__init__(self, aws_session: aioboto3.Session | None = None) -> None`: store session and `self.settings = get_settings()`
  - [x] Use `aioboto3` — `session.client("bedrock-runtime", region_name=settings.aws_region)` as async context manager
  - [x] `generate(prompt, context)`: build `full_prompt` with context + prompt → call `client.invoke_model(modelId=settings.bedrock_llm_model_id, body=json.dumps({"prompt": full_prompt, "max_tokens": 1024}), contentType="application/json")`
  - [x] Parse response: `body["completion"]` (Anthropic models via Bedrock) or model-specific field — check model family and parse accordingly
  - [x] Wrap `botocore.exceptions.ClientError` as `ProviderUnavailableError` — include status code
  - [x] Apply `@retry` on retryable `ClientError` (throttling, service unavailable)
  - [x] Default to AWS session from constructor; if None, create new `aioboto3.Session()`

- [x] **Task 5: Register both providers in `app/providers/registry.py`** (AC: 3)
  - [x] Import `OpenAILLMProvider` from `app.providers.llm.openai`
  - [x] Import `BedrockLLMProvider` from `app.providers.llm.bedrock`
  - [x] Add `"openai": OpenAILLMProvider` to `LLM_REGISTRY`
  - [x] Add `"bedrock": BedrockLLMProvider` to `LLM_REGISTRY`

- [x] **Task 6: Write backend-agnostic LLM provider test suite** (AC: 3)
  - [x] Create or extend `tests/providers/test_llm_provider_contract.py`
  - [x] Parametrize over `AnthropicLLMProvider`, `OpenAILLMProvider`, `BedrockLLMProvider` (all with mocked backends)
  - [x] Contract tests:
    - `generate(prompt, context=[])` → returns non-empty string
    - `generate(prompt, context=[chunk])` → returns non-empty string
    - On simulated transient error → raises `ProviderUnavailableError`
  - [x] Mock clients: patch `openai.AsyncOpenAI`, `anthropic.AsyncAnthropic`, `aioboto3.Session.client`
  - [x] Unit test: `test_openai_llm_calls_chat_completions` — verify correct model, message format
  - [x] Unit test: `test_bedrock_llm_calls_invoke_model` — verify correct `modelId`, body format
  - [x] Unit test: `test_openai_llm_retries_on_rate_limit` — assert retry called 3x
  - [x] Unit test: `test_bedrock_llm_wraps_client_error` — `ClientError` → `ProviderUnavailableError`

- [x] **Task 7: Add ADR for new LLM providers** (AC: 1, 2)
  - [x] Create `docs/adrs/adr-014-openai-bedrock-llm-providers.md`
  - [x] Document: model selection, context injection pattern, Bedrock model ID conventions

- [x] **Task 8: Run regression tests** (AC: 3)
  - [x] `pytest tests/ -x -v --ignore=tests/integration`
  - [x] `mypy --strict app/providers/llm/openai.py app/providers/llm/bedrock.py`

## Dev Notes

### Existing Patterns — Follow Exactly

**Anthropic LLM provider reference** (`app/providers/llm/anthropic.py`):
```python
class AnthropicLLMProvider(LLMProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=_TRANSIENT_ERRORS)
    async def _generate_with_retry(self, client, prompt, system): ...

    async def generate(self, prompt: str, context: list[Chunk]) -> str:
        api_key = await get_secret(self.settings.anthropic_api_key_secret_name, session=self.aws_session)
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            return await self._generate_with_retry(client, prompt, system)
        except ...: raise ProviderUnavailableError(...)
        finally: await client.close()
```
Follow this exact structure for `OpenAILLMProvider`. The `context: list[Chunk]` param is part of the interface — use it to build the context-enriched prompt or ignore if not needed for your model call.

**Abstract LLMProvider interface** (locked):
```python
async def generate(self, prompt: str, context: list[Chunk]) -> str: ...
```

**Context injection pattern** (from Anthropic provider):
The `context` param (`list[Chunk]`) carries retrieved chunks from retrieval. The `generate_answer` function in `app/pipelines/query/generator.py` assembles the full prompt with context before calling `generate()`. Check `generator.py` — it may already inject context into `prompt` before passing to `generate()`. If so, `OpenAILLMProvider.generate()` can treat `context` as auxiliary and just use `prompt`.

Check `app/pipelines/query/generator.py` before implementing to avoid double-injecting context.

**Existing OpenAI dependency**: `openai` package already in `requirements.txt` (used by `OpenAIEmbedder`) — do NOT add it again.

### VALID_LLM_PROVIDERS already includes "openai" and "bedrock"
`app/models/agent.py` has `VALID_LLM_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "bedrock"})` — no change needed.

### OpenAI vs Anthropic API Pattern Difference

Anthropic:
```python
message = await client.messages.create(model=..., system=..., messages=[{"role": "user", ...}])
text = message.content[0].text
```

OpenAI:
```python
response = await client.chat.completions.create(model=..., messages=[{"role": "system", ...}, {"role": "user", ...}])
text = response.choices[0].message.content
```

### Bedrock Model Body Format

For `anthropic.claude-3-haiku-20240307-v1:0` via Bedrock (different from direct Anthropic API):
```json
{
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "<prompt>"}]
}
```
Response: `{"content": [{"text": "..."}]}`

For Amazon Titan models:
```json
{"inputText": "...", "textGenerationConfig": {"maxTokenCount": 1024}}
```
Response: `{"results": [{"outputText": "..."}]}`

Default to Anthropic Claude via Bedrock for consistency with existing provider. The `bedrock_llm_model_id` setting controls which model to use.

### Bedrock Retry Pattern

```python
import botocore.exceptions
BEDROCK_RETRYABLE = ("ThrottlingException", "ServiceUnavailableException")

@retry(max_attempts=3, backoff_factor=2, retry_on=(botocore.exceptions.ClientError,))
async def _generate_with_retry(self, session, prompt): ...
```
Check error code in the except: `e.response["Error"]["Code"] in BEDROCK_RETRYABLE`.

### Architecture Guardrails

- NEVER call Secrets Manager directly — use `app/utils/secrets.py`
- NEVER use `print()` or stdlib `logging` — use `get_logger(__name__)`
- NEVER raise raw exceptions from providers — wrap in `ProviderUnavailableError`
- NEVER add `# type: ignore` in `app/providers/` — fix the type issue
- Provider init MUST accept `aws_session: aioboto3.Session | None = None` — needed for test mocking of aioboto3

### Project Structure

```
app/
  core/
    config.py                    MODIFY: add openai_llm_model, bedrock_llm_model_id
  providers/
    registry.py                  MODIFY: import + register OpenAILLMProvider, BedrockLLMProvider
    llm/
      openai.py                  NEW: OpenAILLMProvider
      bedrock.py                 NEW: BedrockLLMProvider
      __init__.py                MODIFY: export new providers

tests/providers/
  test_llm_provider_contract.py  NEW (or extend existing): parametrized contract suite

docs/adrs/
  adr-014-openai-bedrock-llm-providers.md  NEW
```

### References

- Abstract interface: `app/interfaces/llm_provider.py`
- Reference implementation: `app/providers/llm/anthropic.py`
- Registry: `app/providers/registry.py`
- Config: `app/core/config.py`
- Secrets: `app/utils/secrets.py`
- Retry: `app/utils/retry.py`
- Errors: `app/core/errors.py` — `ProviderUnavailableError`
- Models: `app/models/chunk.py` — `Chunk`
- Generator (context injection): `app/pipelines/query/generator.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References
- `.venv/bin/pytest -q tests/providers/test_llm_provider_contract.py`
- `.venv/bin/pytest -q tests/providers/llm/test_anthropic.py tests/providers/test_llm_provider_contract.py tests/providers/test_registry.py tests/core/test_dependencies.py`
- `.venv/bin/mypy --strict app/providers/llm/openai.py app/providers/llm/bedrock.py`
- `.venv/bin/pytest tests/ -x -v --ignore=tests/integration`

### Completion Notes List
- Added `OpenAILLMProvider` with OpenAI chat completions integration, transient retry behavior, and normalized provider error handling.
- Added `BedrockLLMProvider` with Bedrock runtime invocation, Anthropic-style payload parsing, retryable `ClientError` handling, and normalized provider errors.
- Added config fields `openai_llm_model` and `bedrock_llm_model_id`, and registered `openai`/`bedrock` in `LLM_REGISTRY`.
- Added backend-agnostic LLM provider contract tests covering Anthropic/OpenAI/Bedrock and provider-specific behavior checks.
- Added ADR documenting model selection and Bedrock payload conventions.

### File List
- app/core/config.py
- app/providers/llm/openai.py
- app/providers/llm/bedrock.py
- app/providers/llm/__init__.py
- app/providers/registry.py
- tests/providers/test_llm_provider_contract.py
- tests/providers/test_registry.py
- tests/core/test_dependencies.py
- docs/adrs/adr-014-openai-bedrock-llm-providers.md
- _bmad-output/implementation-artifacts/sprint-status.yaml

### Change Log
- 2026-05-03: Implemented Story 8.4 OpenAI and Bedrock LLM providers with registry/config integration, contract tests, ADR, and full regression validation.
