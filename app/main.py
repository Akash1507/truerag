from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import router as v1_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
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
    application.include_router(v1_router)
    return application


app = create_app()
