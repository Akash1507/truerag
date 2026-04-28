import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app

FAKE_API_KEY = "test-doc-key"
FAKE_CALLER = {
    "tenant_id": "caller-tenant-id",
    "name": "caller",
    "api_key_hash": hashlib.sha256(FAKE_API_KEY.encode()).hexdigest(),
    "rate_limit_rpm": 60,
    "created_at": datetime.now(UTC),
}

FAKE_AGENT_DOC = {
    "agent_id": "507f1f77bcf86cd799439011",
    "tenant_id": FAKE_CALLER["tenant_id"],
    "name": "my-rag-agent",
    "chunking_strategy": "fixed_size",
    "vector_store": "pgvector",
    "embedding_provider": "openai",
    "llm_provider": "anthropic",
    "retrieval_mode": "dense",
    "reranker": "none",
    "top_k": 10,
    "semantic_cache_enabled": False,
    "semantic_cache_threshold": None,
    "status": "active",
    "created_at": datetime.now(UTC),
    "updated_at": datetime.now(UTC),
    "_id": ObjectId("507f1f77bcf86cd799439011"),
}

WRONG_TENANT_AGENT_DOC = {
    **FAKE_AGENT_DOC,
    "tenant_id": "other-tenant-id",
}


def _make_aws_mock(
    s3_put_side_effect: Exception | None = None,
    sqs_send_side_effect: Exception | None = None,
    dynamo_put_side_effect: Exception | None = None,
) -> MagicMock:
    def make_cm(mock_client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_s3 = AsyncMock()
    mock_s3.put_object = AsyncMock(side_effect=s3_put_side_effect)
    mock_s3.delete_object = AsyncMock(return_value={})

    mock_sqs = AsyncMock()
    mock_sqs.send_message = AsyncMock(side_effect=sqs_send_side_effect)

    mock_dynamo = AsyncMock()
    mock_dynamo.put_item = AsyncMock(side_effect=dynamo_put_side_effect)
    mock_dynamo.update_item = AsyncMock(return_value={})

    def client_factory(service: str, **kwargs: Any) -> MagicMock:
        if service == "s3":
            return make_cm(mock_s3)
        if service == "sqs":
            return make_cm(mock_sqs)
        return make_cm(mock_dynamo)

    mock_session = MagicMock()
    mock_session.client = MagicMock(side_effect=client_factory)
    return mock_session


def _make_app(
    agents_find_one_return: dict | None = FAKE_AGENT_DOC,
    aws_mock: MagicMock | None = None,
) -> FastAPI:
    app = create_app()

    mock_tenants = MagicMock()
    mock_tenants.find_one = AsyncMock(return_value=FAKE_CALLER)

    mock_agents = MagicMock()
    mock_agents.find_one = AsyncMock(return_value=agents_find_one_return)

    mock_documents = MagicMock()
    mock_documents.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))
    mock_documents.update_one = AsyncMock(return_value=MagicMock())
    mock_documents.find_one = AsyncMock(return_value=None)
    mock_documents.delete_one = AsyncMock(return_value=MagicMock())
    mock_documents.delete_many = AsyncMock(return_value=MagicMock())

    def get_collection(name: str) -> MagicMock:
        if name == "agents":
            return mock_agents
        if name == "documents":
            return mock_documents
        return mock_tenants

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=get_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = aws_mock or _make_aws_mock()
    return app


@pytest.mark.asyncio
async def test_upload_document_202_success() -> None:
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert body["document_id"]


@pytest.mark.asyncio
async def test_upload_document_403_wrong_tenant() -> None:
    app = _make_app(agents_find_one_return=WRONG_TENANT_AGENT_DOC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    mock_documents = app.state.motor_client[None]["documents"]
    mock_documents.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_upload_document_404_agent_not_found() -> None:
    app = _make_app(agents_find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_upload_document_400_unsupported_type() -> None:
    aws_mock = _make_aws_mock()
    app = _make_app(aws_mock=aws_mock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.xlsx", b"XLSX content", "application/vnd.ms-excel")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    s3_mock = aws_mock.client("s3").__aenter__.return_value
    s3_mock.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_upload_document_500_sqs_failure() -> None:
    aws_mock = _make_aws_mock(sqs_send_side_effect=RuntimeError("queue error"))
    app = _make_app(aws_mock=aws_mock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INGESTION_ERROR"
    mock_documents = app.state.motor_client[None]["documents"]
    mock_documents.update_one.assert_called_once()
    call_args = mock_documents.update_one.call_args
    assert call_args[0][1]["$set"]["status"] == "failed"


@pytest.mark.asyncio
async def test_upload_document_401_no_api_key() -> None:
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_document_500_mongo_failure_compensates_s3() -> None:
    aws_mock = _make_aws_mock()
    app = _make_app(aws_mock=aws_mock)
    mock_documents = app.state.motor_client[None]["documents"]
    mock_documents.insert_one = AsyncMock(side_effect=RuntimeError("mongo down"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 500
    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.delete_object.assert_called_once()


@pytest.mark.asyncio
async def test_upload_document_500_dynamo_put_failure_compensates_s3_and_mongo() -> None:
    aws_mock = _make_aws_mock(dynamo_put_side_effect=RuntimeError("dynamo down"))
    app = _make_app(aws_mock=aws_mock)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 500
    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.delete_object.assert_called_once()
    mock_documents = app.state.motor_client[None]["documents"]
    mock_documents.delete_one.assert_called_once()


@pytest.mark.asyncio
async def test_upload_document_413_file_too_large() -> None:
    app = _make_app()
    big_content = b"x" * (50 * 1024 * 1024 + 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
            files={"file": ("big.pdf", big_content, "application/pdf")},
            headers={"X-API-Key": FAKE_API_KEY},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "INGESTION_ERROR"
