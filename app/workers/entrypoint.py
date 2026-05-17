"""Container worker entrypoint for local and queue-backend based runs."""

from __future__ import annotations

import asyncio

import aioboto3
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.models.agent import AgentDocument
from app.models.conversation import ConversationSession
from app.models.document import DocumentRecord
from app.models.ingestion_job import IngestionJob
from app.models.tenant import TenantDocument
from app.providers.queue import get_queue_backend
from app.utils.observability import configure_logging
from app.workers.sqs_consumer import run_consumer


def _configure_logging(level: str) -> None:
    configure_logging(level)


async def _run_with_backend_or_session() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)

    motor_client = AsyncIOMotorClient(settings.mongodb_uri)
    try:
        db = motor_client[settings.mongodb_database]
        await init_beanie(
            database=db,
            document_models=[
                TenantDocument,
                AgentDocument,
                DocumentRecord,
                IngestionJob,
                ConversationSession,
            ],
        )

        aws_session = aioboto3.Session()
        backend = get_queue_backend(settings, aws_session=aws_session)
        await run_consumer(backend, aws_session, settings)
    finally:
        motor_client.close()


def main() -> None:
    asyncio.run(_run_with_backend_or_session())


if __name__ == "__main__":
    main()
