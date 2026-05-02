from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.sparse_retriever import retrieve_sparse


def _make_agent() -> AgentDocument:
    return AgentDocument(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="sparse",
        reranker="none",
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _vector_result(result_id: str, text: str, chunk_index: int) -> VectorResult:
    return VectorResult(
        id=result_id,
        score=0.0,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=chunk_index,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text=text,
    )


@pytest.mark.asyncio
async def test_sparse_retriever_returns_bm25_top_k_order() -> None:
    vector_store = AsyncMock()
    vector_store.query = AsyncMock(
        return_value=[
            _vector_result("c0", "alpha beta alpha", 0),
            _vector_result("c1", "beta gamma", 1),
            _vector_result("c2", "delta epsilon", 2),
        ]
    )
    results = await retrieve_sparse(query="alpha beta", agent=_make_agent(), vector_store=vector_store, top_k=2)

    assert [result.id for result in results] == ["c0", "c1"]
    assert len(results) == 2
    assert 0.0 <= results[0].score <= 1.0
    assert 0.0 <= results[1].score <= 1.0


@pytest.mark.asyncio
async def test_sparse_retriever_empty_corpus_returns_empty_list() -> None:
    vector_store = AsyncMock()
    vector_store.query = AsyncMock(return_value=[])

    results = await retrieve_sparse(query="anything", agent=_make_agent(), vector_store=vector_store, top_k=3)

    assert results == []


@pytest.mark.asyncio
async def test_sparse_retriever_respects_top_k() -> None:
    vector_store = AsyncMock()
    vector_store.query = AsyncMock(
        return_value=[
            _vector_result("c0", "apple banana", 0),
            _vector_result("c1", "apple", 1),
            _vector_result("c2", "banana", 2),
            _vector_result("c3", "pear", 3),
        ]
    )

    results = await retrieve_sparse(query="apple", agent=_make_agent(), vector_store=vector_store, top_k=1)

    assert len(results) == 1
