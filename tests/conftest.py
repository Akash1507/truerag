import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app.main import create_app
from app.models.agent import AgentDocument
from app.models.document import DocumentRecord
from app.models.eval import EvalDataset, EvalExperiment
from app.models.ingestion_job import IngestionJob
from app.models.tenant import TenantDocument


@pytest.fixture
def app() -> FastAPI:
    with patch("app.main.init_beanie", AsyncMock(return_value=None)):
        return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_beanie_collection_access() -> object:
    with patch.object(TenantDocument, "get_pymongo_collection", return_value=object()), patch.object(
        AgentDocument, "get_pymongo_collection", return_value=object()
    ), patch.object(DocumentRecord, "get_pymongo_collection", return_value=object()), patch.object(
        IngestionJob, "get_pymongo_collection", return_value=object()
    ), patch.object(EvalDataset, "get_pymongo_collection", return_value=object()), patch.object(
        EvalExperiment, "get_pymongo_collection", return_value=object()
    ):
        yield
