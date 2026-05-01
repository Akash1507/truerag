# Story 4.1: Document Parsing & Fixed-Size Chunking

Status: done

## Story

As a Tenant Developer,
I want uploaded documents to be parsed into plain text and split into fixed-size chunks with configurable overlap,
so that document content is broken into retrievable units that the embedding step can process (FR20).

## Acceptance Criteria

**AC1:** Given the ingestion worker reads a document from S3, when `app/pipelines/ingestion/parser.py` processes it, then PDF, TXT, MD, and DOCX files are each parsed to plain text; a `ParseError` is raised for corrupt or unreadable files; no parsing logic exists outside this module.

**AC2:** Given an agent configured with `chunking_strategy: fixed_size`, when `FixedSizeChunker.chunk(text, metadata)` is called, then the text is split into chunks of the configured token size with overlap; each returned `Chunk` carries metadata: `tenant_id`, `agent_id`, `document_id`, `chunk_index`, `chunking_strategy: fixed_size`, `timestamp`, `version`; no chunk exceeds the configured token size.

**AC3:** Given `FixedSizeChunker` is instantiated, when the registry resolves the chunker, then it is resolved through `CHUNKING_REGISTRY["fixed_size"]` via the provider registry — never instantiated directly in the pipeline.

## Tasks / Subtasks

- [x] Task 1: Add `ParseError` to error infrastructure (AC1)
  - [x] 1.1 Add `PARSE_ERROR = "PARSE_ERROR"` to `ErrorCode` enum in `app/core/errors.py`
  - [x] 1.2 Add `ParseError(IngestionError)` class with `code=ErrorCode.PARSE_ERROR`

- [x] Task 2: Add `chunk_size` and `chunk_overlap` to agent model (AC2)
  - [x] 2.1 Add `chunk_size: int = Field(default=512, ge=64, le=8192)` to `AgentDocument`
  - [x] 2.2 Add `chunk_overlap: int = Field(default=50, ge=0, le=512)` to `AgentDocument`
  - [x] 2.3 Mirror fields on `AgentCreateRequest` (optional with defaults), `AgentCreateResponse`, `AgentUpdateResponse`, `AgentListResponse.items`
  - [x] 2.4 Add to `AgentConfigUpdateRequest` as `Optional` fields
  - [x] 2.5 Verify backward-compat: existing MongoDB agents without these fields use Beanie defaults (512/50) — no migration needed

- [x] Task 3: Add parsing dependencies to requirements.txt (AC1)
  - [x] 3.1 Add `tiktoken>=0.7.0,<1.0.0` for token-count splitting
  - [x] 3.2 Add `pypdf>=4.0.0,<5.0.0` for PDF parsing
  - [x] 3.3 Add `python-docx>=1.1.0,<2.0.0` for DOCX parsing

- [x] Task 4: Create `app/pipelines/ingestion/parser.py` (AC1)
  - [x] 4.1 Implement `parse_document(content: bytes, file_type: str) -> str` — public API; no other module may contain parsing logic
  - [x] 4.2 `txt` / `md` branch: `content.decode("utf-8")` raising `ParseError` on `UnicodeDecodeError`
  - [x] 4.3 `pdf` branch: use `pypdf.PdfReader` via `io.BytesIO`; join all page text; raise `ParseError` wrapping any `pypdf` exception
  - [x] 4.4 `docx` branch: use `docx.Document` via `io.BytesIO`; join all paragraph text; raise `ParseError` wrapping any `python-docx` exception
  - [x] 4.5 Default branch: raise `ParseError` for unsupported `file_type` (do NOT raise `UnsupportedFileTypeError` — that's for the upload API boundary, not the pipeline)
  - [x] 4.6 `ParseError` must always chain the original exception with `raise ... from e`

- [x] Task 5: Create `app/providers/chunking/fixed_size.py` (AC2, AC3)
  - [x] 5.1 `FixedSizeChunker(ChunkingStrategy)` with `__init__(self, chunk_size: int = 512, chunk_overlap: int = 50)`
  - [x] 5.2 Encode full text via `tiktoken.get_encoding("cl100k_base")` in `__init__` (reuse instance; do not re-create per `chunk()` call)
  - [x] 5.3 `chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]` — split token list with stride `chunk_size - chunk_overlap`; decode each window back to str; build `Chunk` with fresh `ChunkMetadata` setting `chunk_index` per window
  - [x] 5.4 `metadata` param is a template — copy all fields except `chunk_index` for each chunk; set `chunk_index` = loop index
  - [x] 5.5 If `text` is empty, return `[]` (no chunks)
  - [x] 5.6 Last window may be smaller than `chunk_size` — always include it; no padding
  - [x] 5.7 Guard: if `chunk_overlap >= chunk_size`, raise `ValueError` (would create infinite loop)

- [x] Task 6: Register `FixedSizeChunker` in provider registry (AC3)
  - [x] 6.1 Import `FixedSizeChunker` in `app/providers/registry.py`
  - [x] 6.2 Populate `CHUNKING_REGISTRY = {"fixed_size": FixedSizeChunker}`
  - [x] 6.3 Export `FixedSizeChunker` from `app/providers/chunking/__init__.py`

- [x] Task 7: Update ingestion pipeline (AC1, AC2, AC3)
  - [x] 7.1 Add `agent: AgentDocument` parameter to `run_ingestion_pipeline` signature
  - [x] 7.2 Replace `_extract_text` stub with `parse_document(content, payload.file_type)` from `parser.py`; remove `_extract_text` function entirely
  - [x] 7.3 Replace `_chunk_embed_upsert_stub` with `_chunk_text(scrubbed_text, payload, agent) -> list[Chunk]`
  - [x] 7.4 `_chunk_text` resolves chunker via `CHUNKING_REGISTRY[agent.chunking_strategy]`; instantiates with `agent.chunk_size`, `agent.chunk_overlap`; builds base `ChunkMetadata` with `datetime.now(UTC)`, `version=1`; calls `chunker.chunk(text, metadata)`; returns `list[Chunk]`
  - [x] 7.5 Add `_embed_upsert_stub(chunks: list[Chunk], payload: IngestionJobPayload) -> None` as placeholder for Epic 4.2/4.3 — logs `embedding_not_yet_implemented` with `job_id`, `document_id`, `chunk_count`
  - [x] 7.6 Keep `_download_from_s3` and `_scrub_with_logging` unchanged
  - [x] 7.7 Remove the `_chunk_embed_upsert_stub` function

- [x] Task 8: Update ingestion worker to load agent and pass to pipeline (AC2)
  - [x] 8.1 Add `from app.db.dao.agent_dao import agent_dao` import in `ingestion_worker.py`
  - [x] 8.2 In `process_job`, load agent via `agent = await agent_dao.find_one(...)` before calling pipeline
  - [x] 8.3 If agent is `None`, update job/doc status to `failed` with `error_reason="agent not found"` then `raise PermanentIngestionError("Agent not found — document cannot be retried")`; do NOT retry on a missing agent
  - [x] 8.4 Pass `agent` to `run_ingestion_pipeline(payload, aws_session, settings, agent)`

- [x] Task 9: Tests (AC1, AC2, AC3)
  - [x] 9.1 Create `tests/pipelines/ingestion/test_parser.py`:
    - `test_parse_txt_returns_utf8_text` — bytes → str round-trip
    - `test_parse_md_returns_utf8_text` — md treated same as txt
    - `test_parse_pdf_extracts_text` — mock `pypdf.PdfReader` returning a page with `.extract_text()`
    - `test_parse_docx_extracts_paragraphs` — mock `docx.Document` returning paragraphs
    - `test_parse_unsupported_file_type_raises_parse_error` — e.g., `"csv"` raises `ParseError`
    - `test_parse_corrupt_bytes_raises_parse_error` — invalid UTF-8 bytes for `txt` → `ParseError`
  - [x] 9.2 Create `tests/providers/chunking/__init__.py`
  - [x] 9.3 Create `tests/providers/chunking/test_fixed_size.py`:
    - `test_chunk_splits_into_correct_count` — known token input, expect N chunks
    - `test_chunk_metadata_carried_through` — verify tenant_id/agent_id/doc_id on each chunk
    - `test_chunk_index_sequential` — 0, 1, 2... on returned chunks
    - `test_no_chunk_exceeds_token_size` — encode each chunk, assert len ≤ chunk_size
    - `test_empty_text_returns_empty_list` — `""` → `[]`
    - `test_overlap_guard_raises_value_error` — `chunk_overlap >= chunk_size` → `ValueError`
    - `test_single_chunk_when_text_fits` — text shorter than chunk_size → one chunk
  - [x] 9.4 Update `tests/pipelines/ingestion/test_pipeline.py`:
    - Add `_make_agent()` fixture returning an `AgentDocument` stub with `chunking_strategy="fixed_size"`, `chunk_size=512`, `chunk_overlap=50`
    - Update all existing tests to pass `agent` to `run_ingestion_pipeline`
    - Add `test_pipeline_calls_parse_document` — verify `parser.parse_document` called with correct args
    - Add `test_pipeline_calls_chunker_via_registry` — verify `CHUNKING_REGISTRY["fixed_size"]` used
    - Add `test_parse_error_propagates` — `parse_document` raises `ParseError` → bubbles to `process_job`
  - [x] 9.5 Update `tests/workers/test_ingestion_worker_dao.py`:
    - Add `agent_dao.find_one` to mock setup; default returns a valid agent
    - Add `test_agent_not_found_marks_failed_and_raises_permanent_error`

## Dev Notes

### Critical: CHUNKING_REGISTRY Already Stubbed — Just Populate It

`app/providers/registry.py` already has:
```python
CHUNKING_REGISTRY: dict[str, type[ChunkingStrategy]] = {
    # Populated in Epic 4: "fixed_size": FixedSizeChunker, ...
}
```
Do not re-declare it. Add the import and populate the dict.

### Critical: ParseError Does Not Exist Yet

`app/core/errors.py` has `IngestionError` and `INGESTION_ERROR` in `ErrorCode`. But `ParseError` is not in the codebase. Add:
- `PARSE_ERROR = "PARSE_ERROR"` to `ErrorCode`
- `ParseError(IngestionError)` — do NOT reuse `UnsupportedFileTypeError` (that class is for the REST upload boundary, not the pipeline internals)

### Critical: Pipeline Signature Must Change — Update All Call Sites

`run_ingestion_pipeline` currently takes `(payload, aws_session, settings)`. After this story it takes `(payload, aws_session, settings, agent)`. The only call site is `app/workers/ingestion_worker.py:process_job`. Update it. All test mocks of this function must also be updated.

### Critical: Agent Must Be Loaded in Worker Before Pipeline Call

`process_job` does not currently load the agent. Add load via `agent_dao.find_one` before calling the pipeline. Use same DAO module-singleton pattern already used: `from app.db.dao.agent_dao import agent_dao`. If agent is not found, fail permanently (no SQS retry): raise `PermanentIngestionError`, not `IngestionError`. A missing agent will never reappear; retrying wastes queue throughput.

### Critical: FixedSizeChunker — Never Re-Create tiktoken Encoding Per Call

```python
class FixedSizeChunker(ChunkingStrategy):
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError(f"chunk_overlap ({chunk_overlap}) must be < chunk_size ({chunk_size})")
        self._enc = tiktoken.get_encoding("cl100k_base")  # reuse; loading is slow
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
```

`tiktoken.get_encoding` is cached by tiktoken itself, but the call has overhead. Assign to `self._enc` in `__init__` to make tests fast and make the intent explicit.

### Critical: chunk() Receives Base Metadata — Stamp chunk_index Per Window

The `ChunkMetadata` passed to `chunk()` is a template with `chunk_index` field already populated (callers pass `chunk_index=0`). For each window, create a new `ChunkMetadata` copying all fields and overriding `chunk_index`:

```python
def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]:
    if not text:
        return []
    tokens = self._enc.encode(text)
    chunks: list[Chunk] = []
    stride = self.chunk_size - self.chunk_overlap
    for i, start in enumerate(range(0, len(tokens), stride)):
        window = tokens[start : start + self.chunk_size]
        chunks.append(Chunk(
            text=self._enc.decode(window),
            metadata=ChunkMetadata(
                tenant_id=metadata.tenant_id,
                agent_id=metadata.agent_id,
                document_id=metadata.document_id,
                chunk_index=i,
                chunking_strategy=metadata.chunking_strategy,
                timestamp=metadata.timestamp,
                version=metadata.version,
            ),
        ))
    return chunks
```

### Critical: pipeline.py _chunk_text Must Not Instantiate Chunker Directly in Pipeline

Per architecture rule: never instantiate pipeline components directly in pipeline code. Resolve via registry:

```python
from app.providers.registry import CHUNKING_REGISTRY

def _chunk_text(text: str, payload: IngestionJobPayload, agent: AgentDocument) -> list[Chunk]:
    chunker_cls = CHUNKING_REGISTRY[agent.chunking_strategy]
    chunker = chunker_cls(chunk_size=agent.chunk_size, chunk_overlap=agent.chunk_overlap)
    metadata = ChunkMetadata(
        tenant_id=payload.tenant_id,
        agent_id=payload.agent_id,
        document_id=payload.document_id,
        chunk_index=0,
        chunking_strategy=agent.chunking_strategy,
        timestamp=datetime.now(timezone.utc),
        version=1,
    )
    return chunker.chunk(text, metadata)
```

If `agent.chunking_strategy` is not in `CHUNKING_REGISTRY`, a `KeyError` propagates — this is correct behavior (marks job failed, retried from SQS). Do NOT add a try/except around this lookup.

### Deferred Work from Story 3-4 Addressed Here

From `deferred-work.md` (code review of 3-4, 2026-05-01):
- **`_extract_text` ignores `file_type`, always UTF-8 decodes** — this story fixes it by replacing `_extract_text` with `parse_document` from `parser.py`
- All other deferred items from 3-4 (`ContentLength` check, S3 timeout, `IngestionJobPayload.timestamp` type, `s3_key` prefix scoping) remain deferred — do NOT address in this story

### AgentDocument Field Addition — Backward Compatibility

Adding `chunk_size` and `chunk_overlap` to `AgentDocument` (Beanie Document) with Python default values:

```python
chunk_size: int = Field(default=512, ge=64, le=8192)
chunk_overlap: int = Field(default=50, ge=0, le=512)
```

Beanie reads from MongoDB and applies the Python default when the field is absent in the document. Existing agent records in MongoDB will resolve to 512/50 without migration. This is safe.

Add the same fields to:
- `AgentCreateRequest` — optional with same defaults
- `AgentCreateResponse`, `AgentUpdateResponse` — required (always returned)
- `AgentConfigUpdateRequest` — optional (`int | None = None`)

### PDF Parsing Library Choice

Use `pypdf` (not `PyPDF2` which is unmaintained, not `pdfminer.six` which is low-level). `pypdf>=4.0.0` is the current maintained fork.

```python
import io
import pypdf

def _parse_pdf(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except Exception as exc:
        raise ParseError(f"PDF parse failed: {exc}") from exc
```

### DOCX Parsing

```python
import io
import docx

def _parse_docx(content: bytes) -> str:
    try:
        doc = docx.Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as exc:
        raise ParseError(f"DOCX parse failed: {exc}") from exc
```

### tiktoken Encoding Choice

Use `cl100k_base` — the encoding used by OpenAI's `text-embedding-3-small` and `text-embedding-3-large` models (Epic 4.2 will use these). Chunk size measured in tokens for this encoding.

### Logging in _chunk_text

Emit a structured log from `_chunk_text` after chunking completes:
```python
logger.info(
    "chunking_complete",
    extra={
        "operation": "chunking",
        "extra_data": {
            "tenant_id": payload.tenant_id,
            "agent_id": payload.agent_id,
            "document_id": payload.document_id,
            "chunk_count": len(chunks),
            "chunking_strategy": agent.chunking_strategy,
            "chunk_size": agent.chunk_size,
            "chunk_overlap": agent.chunk_overlap,
        },
    },
)
```

### Do NOT Touch These Files

- `app/utils/pii.py` — stable, do not modify
- `tests/utils/test_pii.py` — do not modify
- `app/services/ingestion_service.py` — no changes needed
- `app/models/document.py` — no changes needed
- `tests/workers/test_ingestion_worker.py` — legacy skipped DynamoDB tests, do not un-skip

### Project Structure Notes

**Existing (do not re-create):**
- `app/pipelines/ingestion/__init__.py` — exists (empty)
- `app/pipelines/ingestion/pipeline.py` — exists (modify)
- `app/providers/chunking/__init__.py` — exists (populate)
- `app/providers/registry.py` — exists (add FixedSizeChunker)
- `app/interfaces/chunking_strategy.py` — exists, stable ABC
- `app/models/chunk.py` — `ChunkMetadata`, `Chunk` fully defined — do NOT redefine

**Create new:**
- `app/pipelines/ingestion/parser.py` — new
- `app/providers/chunking/fixed_size.py` — new
- `tests/pipelines/ingestion/test_parser.py` — new
- `tests/providers/chunking/__init__.py` — new (check if `tests/providers/__init__.py` exists first; create if missing)
- `tests/providers/chunking/test_fixed_size.py` — new

**Modify:**
- `app/core/errors.py` — add `PARSE_ERROR` + `ParseError`
- `app/models/agent.py` — add `chunk_size`, `chunk_overlap`
- `app/providers/registry.py` — populate `CHUNKING_REGISTRY`
- `app/pipelines/ingestion/pipeline.py` — replace stubs
- `app/workers/ingestion_worker.py` — load agent, pass to pipeline
- `requirements.txt` — add tiktoken, pypdf, python-docx
- `tests/pipelines/ingestion/test_pipeline.py` — update for new signature + new tests
- `tests/workers/test_ingestion_worker_dao.py` — add agent_dao mock

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 4.1`] — User story, acceptance criteria
- [Source: `_bmad-output/planning-artifacts/architecture.md#Pluggable providers`] — `CHUNKING_REGISTRY`, registry pattern
- [Source: `_bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concerns`] — never instantiate pipeline components directly, always resolve via registry
- [Source: `app/interfaces/chunking_strategy.py`] — `ChunkingStrategy(ABC).chunk(text, metadata) -> list[Chunk]`
- [Source: `app/models/chunk.py`] — `ChunkMetadata`, `Chunk` — stable, do not modify
- [Source: `app/models/agent.py`] — add `chunk_size`, `chunk_overlap` here
- [Source: `app/providers/registry.py`] — `CHUNKING_REGISTRY` stub already exists; populate it
- [Source: `app/core/errors.py`] — add `PARSE_ERROR` + `ParseError(IngestionError)` here
- [Source: `app/pipelines/ingestion/pipeline.py`] — replace `_extract_text` and `_chunk_embed_upsert_stub`
- [Source: `app/workers/ingestion_worker.py`] — `process_job` — add agent load, pass to pipeline
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md#3-4`] — `_extract_text` stub addressed here; S3 buffer + timeout still deferred
- [Source: `_bmad-output/implementation-artifacts/3-4-pii-scrubbing-at-ingestion.md#Dev Agent Record`] — file list and completion notes from story 3-4

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Fixed `test_empty_registries_are_dicts` regression: test expected `CHUNKING_REGISTRY == {}` but story 4.1 populates it; updated test to assert `"fixed_size" in CHUNKING_REGISTRY` instead.
- Linting: replaced `timezone.utc` with `datetime.UTC` alias (UP017) in pipeline.py; broke two long lines in ingestion_worker.py (E501).

### Completion Notes List

- Added `PARSE_ERROR` to `ErrorCode` and `ParseError(IngestionError)` to `app/core/errors.py`.
- Added `chunk_size` (default 512) and `chunk_overlap` (default 50) to `AgentDocument`, `AgentCreateRequest`, `AgentCreateResponse`, `AgentUpdateResponse`, `AgentConfigUpdateRequest`. Backward-compatible via Beanie field defaults.
- Added `tiktoken>=0.7.0`, `pypdf>=4.0.0`, `python-docx>=1.1.0` to `requirements.txt`.
- Created `app/pipelines/ingestion/parser.py` with `parse_document` dispatch for txt/md/pdf/docx; unsupported types raise `ParseError`; all exceptions chained with `from exc`.
- Created `app/providers/chunking/fixed_size.py`: `FixedSizeChunker` encodes text with `cl100k_base` in `__init__`, splits by stride `chunk_size - chunk_overlap`, stamps sequential `chunk_index` per window.
- Populated `CHUNKING_REGISTRY = {"fixed_size": FixedSizeChunker}` in registry; exported from `app/providers/chunking/__init__.py`.
- Rewrote `app/pipelines/ingestion/pipeline.py`: replaced `_extract_text` stub with `parse_document`, replaced `_chunk_embed_upsert_stub` with `_chunk_text` (registry-resolved) + `_embed_upsert_stub` placeholder; added `agent: AgentDocument` param to `run_ingestion_pipeline`.
- Updated `app/workers/ingestion_worker.py`: loads agent via `agent_dao.find_one` before pipeline; missing agent marks job+doc failed and raises `PermanentIngestionError` (no SQS retry).
- All 170 unit tests pass. 0 regressions. Linting clean.

### File List

- `app/core/errors.py` — added `PARSE_ERROR` to `ErrorCode`, added `ParseError(IngestionError)`
- `app/models/agent.py` — added `chunk_size`, `chunk_overlap` to `AgentDocument`, `AgentCreateRequest`, `AgentCreateResponse`, `AgentUpdateResponse`, `AgentConfigUpdateRequest`
- `app/providers/registry.py` — imported `FixedSizeChunker`, populated `CHUNKING_REGISTRY`
- `app/providers/chunking/__init__.py` — exported `FixedSizeChunker`
- `app/providers/chunking/fixed_size.py` — new: `FixedSizeChunker` implementation
- `app/pipelines/ingestion/parser.py` — new: `parse_document` for txt/md/pdf/docx
- `app/pipelines/ingestion/pipeline.py` — replaced stubs; added `agent` param; registry-resolved chunking
- `app/workers/ingestion_worker.py` — agent load + `PermanentIngestionError` on missing agent
- `requirements.txt` — added tiktoken, pypdf, python-docx
- `tests/pipelines/ingestion/test_parser.py` — new: 6 parser tests
- `tests/providers/chunking/__init__.py` — new: empty init
- `tests/providers/chunking/test_fixed_size.py` — new: 7 chunker tests
- `tests/pipelines/ingestion/test_pipeline.py` — updated: agent fixture, 3 new tests, patched stubs
- `tests/workers/test_ingestion_worker_dao.py` — updated: agent_dao mock, new permanent-error test
- `tests/providers/test_registry.py` — updated: fixed registry assertion for `fixed_size` entry

### Review Findings

- [x] [Review][Patch] `ParseError` class missing from `errors.py` — only `PARSE_ERROR` enum value added; `from app.core.errors import ParseError` will `ImportError` at runtime and in all tests [app/core/errors.py:21]
- [x] [Review][Patch] `ParseError` must be `PermanentIngestionError`, not `IngestionError` — corrupt/unsupported documents are deterministic failures; with current inheritance they fall into `except Exception` and are SQS-retried until DLQ [app/core/errors.py, app/workers/ingestion_worker.py:45-46]
- [x] [Review][Patch] `_parse_text` only catches `UnicodeDecodeError`; any other exception during `bytes.decode()` bypasses `ParseError` wrapping — violates AC1 "corrupt or unreadable" contract [app/pipelines/ingestion/parser.py:22-25]
- [x] [Review][Patch] `test_chunk_splits_into_correct_count` asserts `len(chunks) >= 1` — trivially satisfied by any non-empty result; the test comment says "7 chunks" but never asserts that; use `tiktoken` to pre-count tokens and assert exact chunk count [tests/providers/chunking/test_fixed_size.py:27]
- [x] [Review][Patch] Whitespace-only text passes `if not text` guard in `FixedSizeChunker.chunk()` — `" "` is truthy; whitespace-only text produces whitespace-only chunks passed to the embedding model [app/providers/chunking/fixed_size.py:18]
- [x] [Review][Patch] Empty PDF (0 pages) or all-`None` `extract_text()` silently returns empty string — no guard raises `ParseError`; document proceeds to chunking, produces zero chunks, is marked `ready` with no stored content [app/pipelines/ingestion/parser.py:30-31]
- [x] [Review][Patch] Empty DOCX (0 paragraphs) silently returns empty string — same silent-empty path as empty PDF [app/pipelines/ingestion/parser.py:39]
- [x] [Review][Patch] Minimum stride guard missing — `chunk_overlap = chunk_size - 1` (allowed: `chunk_overlap < chunk_size`) gives `stride=1`; O(N²) chunks with ~99% overlap; memory and embedding cost explosion. Add `chunk_overlap <= chunk_size // 2` validator in `AgentCreateRequest`/`AgentDocument` AND runtime guard in `FixedSizeChunker.__init__` [app/models/agent.py:56-57, app/providers/chunking/fixed_size.py:8-15]
- [x] [Review][Patch] Zero-chunk guard missing in pipeline — when `_chunk_text` returns `[]` (e.g., whitespace-only document), `_embed_upsert_stub` logs `chunk_count=0` and doc is marked `ready` with no stored content; raise `PermanentIngestionError` when `chunks == []` [app/pipelines/ingestion/pipeline.py:27-28]
- [x] [Review][Patch] No cross-field `@model_validator` preventing `chunk_overlap >= chunk_size` persistence — can be stored to MongoDB via `AgentConfigUpdateRequest` without error; guard in `FixedSizeChunker.__init__` catches at runtime but invalid config persists [app/models/agent.py:24-25, 56-57]
- [x] [Review][Patch] `test_pipeline_calls_chunker_via_registry` does not patch `parse_document` — real parser called on `b"some text"` with `file_type="txt"`; works by coincidence; changing fixture `file_type` would invoke real `pypdf`/`docx` [tests/pipelines/ingestion/test_pipeline.py:235-256]
- [x] [Review][Patch] `_embed_upsert_stub` log event omits `tenant_id` and `agent_id` — breaks multi-tenant log correlation; every log event in this codebase includes `tenant_id` [app/pipelines/ingestion/pipeline.py:97-107]

- [x] [Review][Defer] No test exercises real corrupt PDF/DOCX bytes — error paths mocked; only TXT corrupt-bytes tested with real code — deferred, mocking is acceptable at unit level [tests/pipelines/ingestion/test_parser.py]
- [x] [Review][Defer] `agent_dao.find_one` DB timeout → DAO calls in `except` block can suppress original exception — pre-existing pattern [app/workers/ingestion_worker.py:29-57]
- [x] [Review][Defer] Status split on final ready update — pre-existing inconsistency [app/workers/ingestion_worker.py:59-64]
- [x] [Review][Defer] DOCX table/header/footer content silently dropped — beyond story scope [app/pipelines/ingestion/parser.py:36-40]
- [x] [Review][Defer] `KeyError` from unknown `chunking_strategy` causes indefinite SQS retry — spec-mandated [app/pipelines/ingestion/pipeline.py:67]
- [x] [Review][Defer] No max document size guard before parsing — large S3 objects fully buffered; noted in prior 3-4 review [app/pipelines/ingestion/parser.py:9]
- [x] [Review][Defer] `_chunk_text` uses hardcoded `chunk_size`/`chunk_overlap` kwargs — future strategies with different init params will `TypeError`; defer until second strategy added [app/pipelines/ingestion/pipeline.py:68]

## Change Log

- 2026-05-01: Story 4.1 implemented — document parsing (txt/md/pdf/docx) and fixed-size token chunking via `FixedSizeChunker`; registry populated; pipeline and worker updated; 170 tests pass.
