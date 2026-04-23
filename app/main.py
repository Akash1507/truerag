from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aioboto3  # type: ignore[import-untyped]
import asyncpg  # type: ignore[import-untyped]
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from app.api.v1 import router as v1_router
from app.core.auth import AuthMiddleware
from app.core.config import get_settings
from app.core.errors import TrueRAGError
from app.core.exception_handlers import generic_exception_handler, truerag_exception_handler
from app.core.middleware import RequestIDMiddleware
from app.core.rate_limiter import RateLimiterMiddleware
from app.utils.observability import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info("startup", extra={"operation": "app_startup"})

    # MongoDB
    try:
        motor_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)  # type: ignore[type-arg]
        await motor_client.admin.command("ping")
        application.state.motor_client = motor_client
        db = motor_client[settings.mongodb_database]
        await db["tenants"].create_index([("name", 1)], unique=True)
        logger.info("mongodb_connected", extra={"operation": "app_startup"})
    except Exception as exc:
        logger.error(
            "mongodb_failed",
            extra={"operation": "app_startup", "extra_data": {"error": str(exc)}},
        )
        raise RuntimeError(f"MongoDB connection failed: {exc}") from exc

    # pgvector
    try:
        pg_pool = await asyncpg.create_pool(settings.pgvector_dsn, min_size=2, max_size=10)
        try:
            await pg_pool.fetchval("SELECT 1")
        except Exception:
            await pg_pool.close()
            raise
        application.state.pg_pool = pg_pool
        logger.info("pgvector_connected", extra={"operation": "app_startup"})
    except Exception as exc:
        motor_client.close()
        logger.error(
            "pgvector_failed",
            extra={"operation": "app_startup", "extra_data": {"error": str(exc)}},
        )
        raise RuntimeError(f"pgvector connection failed: {exc}") from exc

    # AWS (lightweight — no network I/O at session creation)
    application.state.aws_session = aioboto3.Session()
    logger.info("aws_session_created", extra={"operation": "app_startup"})

    yield

    # Shutdown
    try:
        motor_client.close()
    except Exception as exc:
        logger.warning(
            "mongodb_close_error",
            extra={"operation": "app_shutdown", "extra_data": {"error": str(exc)}},
        )
    try:
        await pg_pool.close()
    except Exception as exc:
        logger.warning(
            "pgvector_close_error",
            extra={"operation": "app_shutdown", "extra_data": {"error": str(exc)}},
        )
    logger.info("shutdown", extra={"operation": "app_shutdown"})


def create_app() -> FastAPI:
    application = FastAPI(
        title="TrueRAG",
        version="0.1.0",
        description="Production-grade open-source RAG Engine",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.add_middleware(RateLimiterMiddleware)  # innermost — runs after auth sets tenant
    application.add_middleware(AuthMiddleware)          # middle — runs after request ID set
    application.add_middleware(RequestIDMiddleware)     # outermost — runs first
    application.add_exception_handler(TrueRAGError, truerag_exception_handler)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, generic_exception_handler)
    application.include_router(v1_router)
    return application


app = create_app()
