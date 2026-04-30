from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.document import DocumentStatusResponse, DocumentUploadResponse
from app.models.tenant import TenantDocument


def _tenant() -> TenantDocument:
    return TenantDocument(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_upload_document_route_uses_service() -> None:
    app = create_app()
    app.state.aws_session = MagicMock()
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.documents.ingestion_service.upload_document",
        AsyncMock(return_value=DocumentUploadResponse(job_id="job-1", document_id="doc-1")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/agents/agent-1/documents",
                files={"file": ("report.pdf", BytesIO(b"pdf"), "application/pdf")},
                headers={"X-API-Key": "key"},
            )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_get_document_status_route_uses_service() -> None:
    app = create_app()
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.documents.ingestion_service.get_document_status",
        AsyncMock(return_value=DocumentStatusResponse(document_id="doc-1", status="ready")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/agents/agent-1/documents/doc-1/status",
                headers={"X-API-Key": "key"},
            )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
