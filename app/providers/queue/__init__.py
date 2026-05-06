from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings
from app.interfaces.queue_backend import QueueBackend
from app.providers.queue.kafka_backend import KafkaBackend
from app.providers.queue.local_backend import LocalQueueBackend
from app.providers.queue.sqs_backend import SQSBackend

if TYPE_CHECKING:
    import aioboto3


def get_queue_backend(
    settings: Settings,
    aws_session: "aioboto3.Session | None" = None,
) -> QueueBackend:
    if settings.queue_backend == "local":
        return LocalQueueBackend()
    if settings.queue_backend == "kafka":
        return KafkaBackend(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            topic=settings.kafka_topic,
        )
    if aws_session is None:
        raise ValueError("aws_session is required when queue_backend='sqs'")
    return SQSBackend(aws_session=aws_session, settings=settings)


__all__ = [
    "KafkaBackend",
    "LocalQueueBackend",
    "SQSBackend",
    "get_queue_backend",
]
