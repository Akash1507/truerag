import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import stream_query_pipeline


def _make_agent() -> AgentDocument:
    return AgentDocument.model_construct(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        query_rewrite=False,
        hallucination_check_enabled=False,
        context_window_tokens=8192,
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        embedding_provider_mismatch=False,
        faithfulness_threshold=0.6,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _result() -> VectorResult:
    return VectorResult(
        id="chunk-1",
        score=0.9,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text="chunk text",
    )


def _parse(chunk: str) -> str | dict[str, object]:
    assert chunk.startswith("data: ")
    payload = chunk[len("data: ") :].strip()
    if payload == "[DONE]":
        return payload
    return json.loads(payload)


async def _token_stream():
    yield "hello "
    yield "world"


@pytest.mark.asyncio
async def test_stream_query_pipeline_emits_tokens_done_and_done_marker() -> None:
    agent = _make_agent()

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline._execute_retrieval", AsyncMock(return_value=[_result()])),
        patch("app.pipelines.query.pipeline._execute_rerank", AsyncMock(return_value=[_result()])),
        patch("app.pipelines.query.pipeline._stream_generation", return_value=_token_stream()),
    ):
        chunks = [
            event
            async for event in stream_query_pipeline(
                query="raw query",
                top_k=5,
                agent=agent,
                filters=None,
                request_id="req-1",
            )
        ]

    parsed = [_parse(chunk) for chunk in chunks]
    assert parsed[0] == {"type": "token", "token": "hello "}
    assert parsed[1] == {"type": "token", "token": "world"}
    assert isinstance(parsed[2], dict)
    assert parsed[2]["type"] == "done"
    assert parsed[2]["confidence"] == 0.9
    assert parsed[2]["citations"] == [
        {"document_name": "doc-1", "chunk_text": "chunk text"}
    ]
    assert parsed[3] == "[DONE]"


@pytest.mark.asyncio
async def test_stream_query_pipeline_emits_error_event_then_done_on_exception() -> None:
    agent = _make_agent()

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        chunks = [
            event
            async for event in stream_query_pipeline(
                query="raw query",
                top_k=5,
                agent=agent,
                filters=None,
                request_id="req-2",
            )
        ]

    parsed = [_parse(chunk) for chunk in chunks]
    assert parsed[0] == {"type": "error", "message": "boom"}
    assert parsed[1] == "[DONE]"
