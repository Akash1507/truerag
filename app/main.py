from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.core.errors import TrueRAGError
from app.core.exception_handlers import generic_exception_handler, truerag_exception_handler
from app.core.middleware import RequestIDMiddleware
from app.utils.observability import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", extra={"operation": "app_startup"})
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="TrueRAG",
        version="0.1.0",
        description="Production-grade open-source RAG Engine",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.add_middleware(RequestIDMiddleware)
    application.add_exception_handler(TrueRAGError, truerag_exception_handler)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, generic_exception_handler)
    application.include_router(v1_router)
    return application


app = create_app()
