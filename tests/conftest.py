"""
Session-wide test database setup.

On session start:
- Overrides MONGODB_DATABASE → truerag_test  (never touches production data)
- Overrides PGVECTOR_DSN    → postgresql://…/truerag_test
- Creates both databases, initialises Beanie, seeds one admin tenant + one agent.

On session end:
- Drops both test databases.

If either database is not reachable the fixture continues silently; pure-unit
tests that mock all DAO/service calls will still pass.  Tests that need a live
database will fail naturally.
"""

import hashlib
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]
import asyncpg  # type: ignore[import-untyped]
import pytest
from beanie import init_beanie
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from unittest.mock import patch

from app.core.config import get_settings
from app.main import create_app
from app.models.agent import AgentDocument
from app.models.conversation import ConversationSession
from app.models.document import DocumentRecord
from app.models.eval import EvalDataset, EvalExperiment
from app.models.ingestion_job import IngestionJob
from app.models.query_cost import QueryCost
from app.models.tenant import TenantDocument

# ── Connection strings (overridable via env for CI) ───────────────────────────

_MONGO_URI = os.getenv("TEST_MONGODB_URI", "mongodb://localhost:27017")
_MONGO_DB = "truerag_test"
_PG_DSN = os.getenv(
    "TEST_PGVECTOR_DSN",
    "postgresql://postgres:postgres@localhost:5432/truerag_test",
)
_PG_ADMIN_DSN = os.getenv(
    "TEST_PG_ADMIN_DSN",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)

_BEANIE_MODELS = [
    TenantDocument,
    AgentDocument,
    DocumentRecord,
    IngestionJob,
    EvalDataset,
    EvalExperiment,
    QueryCost,
    ConversationSession,
]

# ── Session fixture ───────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
async def test_databases() -> AsyncGenerator[dict, None]:
    # Redirect all settings to test databases before any test runs.
    os.environ["MONGODB_URI"] = _MONGO_URI
    os.environ["MONGODB_DATABASE"] = _MONGO_DB
    os.environ["PGVECTOR_DSN"] = _PG_DSN
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()

    motor_client: AsyncIOMotorClient | None = None
    mongo_ok = False

    # ── MongoDB ───────────────────────────────────────────────────────────────
    try:
        motor_client = AsyncIOMotorClient(_MONGO_URI, serverSelectionTimeoutMS=3000)
        await motor_client.admin.command("ping")

        # Always start with an empty test database.
        await motor_client.drop_database(_MONGO_DB)
        mongo_db = motor_client[_MONGO_DB]

        await init_beanie(database=mongo_db, document_models=_BEANIE_MODELS)

        # Indexes that the production lifespan creates.
        await mongo_db["tenants"].create_index([("name", 1)], unique=True)
        await mongo_db["agents"].create_index([("agent_id", 1)], unique=True)
        await mongo_db["agents"].create_index([("tenant_id", 1), ("name", 1)], unique=True)

        mongo_ok = True
    except Exception:
        if motor_client is not None:
            motor_client.close()
            motor_client = None

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    pg_ok = False
    try:
        admin = await asyncpg.connect(_PG_ADMIN_DSN, timeout=3)
        # Terminate any stale connections then recreate the database from scratch.
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'truerag_test' AND pid <> pg_backend_pid()"
        )
        await admin.execute("DROP DATABASE IF EXISTS truerag_test")
        await admin.execute("CREATE DATABASE truerag_test")
        await admin.close()

        conn = await asyncpg.connect(_PG_DSN, timeout=3)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS document_vectors (
                id          TEXT NOT NULL,
                namespace   TEXT NOT NULL,
                embedding   vector,
                metadata    JSONB NOT NULL,
                text        TEXT NOT NULL,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL,
                updated_at  TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (id, namespace)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dv_namespace ON document_vectors (namespace)"
        )
        await conn.close()
        pg_ok = True
    except Exception:
        pass

    # ── Seed ──────────────────────────────────────────────────────────────────
    seed: dict = {"motor_client": motor_client, "mongo_ok": mongo_ok, "pg_ok": pg_ok}

    if mongo_ok:
        now = datetime.now(UTC)

        seed_tenant = TenantDocument(
            tenant_id="seed-tenant-id",
            name="seed-tenant",
            display_name="Seed Tenant",
            api_key_hash=hashlib.sha256(b"seed-api-key").hexdigest(),
            role="admin",
            rate_limit_rpm=1000,
            created_at=now,
        )
        await TenantDocument.insert(seed_tenant)

        seed_agent = AgentDocument(
            agent_id=str(ObjectId()),
            tenant_id="seed-tenant-id",
            name="seed-agent",
            chunking_strategy="fixed_size",
            chunk_size=512,
            chunk_overlap=50,
            vector_store="pgvector",
            embedding_provider="openai",
            llm_provider="anthropic",
            retrieval_mode="dense",
            reranker="none",
            top_k=5,
            semantic_cache_enabled=False,
            faithfulness_threshold=0.6,
            status="active",
            created_at=now,
            updated_at=now,
        )
        await AgentDocument.insert(seed_agent)

        seed["tenant"] = seed_tenant
        seed["agent"] = seed_agent
        seed["api_key"] = "seed-api-key"

    yield seed

    # ── Teardown ──────────────────────────────────────────────────────────────
    if motor_client is not None:
        try:
            await motor_client.drop_database(_MONGO_DB)
        except Exception:
            pass
        motor_client.close()

    if pg_ok:
        try:
            admin = await asyncpg.connect(_PG_ADMIN_DSN, timeout=3)
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'truerag_test' AND pid <> pg_backend_pid()"
            )
            await admin.execute("DROP DATABASE IF EXISTS truerag_test")
            await admin.close()
        except Exception:
            pass

    get_settings.cache_clear()


# ── Per-test app / client fixtures ────────────────────────────────────────────


@pytest.fixture
async def app(test_databases: dict) -> AsyncGenerator[FastAPI, None]:
    """
    FastAPI application wired to the test databases.

    Uses a minimal lifespan that reuses Beanie (already initialised by
    test_databases) and creates fresh Motor + asyncpg connections per test.
    """

    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        motor = AsyncIOMotorClient(_MONGO_URI)
        try:
            pg_pool = await asyncpg.create_pool(_PG_DSN, min_size=1, max_size=3)
        except Exception:
            pg_pool = None
        application.state.motor_client = motor
        application.state.pg_pool = pg_pool
        application.state.aws_session = aioboto3.Session()
        yield
        motor.close()
        if pg_pool is not None:
            await pg_pool.close()

    with patch("app.main.lifespan", _test_lifespan):
        yield create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
