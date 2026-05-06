from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.providers.queue import get_queue_backend
from app.providers.queue.kafka_backend import KafkaBackend
from app.providers.queue.local_backend import LocalQueueBackend
from app.providers.queue.sqs_backend import SQSBackend


def _make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "aws_region": "us-east-1",
        "aws_endpoint_url": None,
        "sqs_ingestion_queue_url": "http://localhost/queue",
        "queue_backend": "sqs",
        "kafka_bootstrap_servers": "localhost:9092",
        "kafka_topic": "truerag-ingestion",
    }
    base.update(overrides)
    return Settings(**base)


def _make_aws_session() -> MagicMock:
    sqs_client = AsyncMock()
    sqs_client.send_message = AsyncMock(return_value={})
    sqs_client.receive_message = AsyncMock(return_value={"Messages": []})
    sqs_client.delete_message = AsyncMock(return_value={})

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=sqs_client)
    context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.client = MagicMock(return_value=context)
    return session


@pytest.mark.asyncio
async def test_local_queue_backend_send_receive_roundtrip() -> None:
    backend = LocalQueueBackend()
    payload = {"job_id": "job-1", "tenant_id": "tenant-1"}
    await backend.send(payload)
    messages = await backend.receive(max_messages=1, wait_seconds=1)
    assert len(messages) == 1
    assert messages[0].body == payload


@pytest.mark.asyncio
async def test_sqs_backend_send_uses_expected_queue_url() -> None:
    aws_session = _make_aws_session()
    settings = _make_settings()
    backend = SQSBackend(aws_session=aws_session, settings=settings)

    payload = {"job_id": "job-1", "tenant_id": "tenant-1"}
    await backend.send(payload)

    sqs_client = aws_session.client.return_value.__aenter__.return_value
    sqs_client.send_message.assert_awaited_once()
    kwargs = sqs_client.send_message.await_args.kwargs
    assert kwargs["QueueUrl"] == settings.sqs_ingestion_queue_url
    assert json.loads(kwargs["MessageBody"]) == payload


def test_factory_returns_local_backend() -> None:
    backend = get_queue_backend(_make_settings(queue_backend="local"))
    assert isinstance(backend, LocalQueueBackend)


def test_factory_returns_kafka_backend() -> None:
    backend = get_queue_backend(
        _make_settings(
            queue_backend="kafka",
            kafka_bootstrap_servers="kafka:9092",
            kafka_topic="ingestion-topic",
        )
    )
    assert isinstance(backend, KafkaBackend)


def test_factory_requires_aws_session_for_sqs() -> None:
    with pytest.raises(ValueError):
        get_queue_backend(_make_settings(queue_backend="sqs"))


def test_factory_returns_sqs_backend_when_session_present() -> None:
    backend = get_queue_backend(_make_settings(queue_backend="sqs"), aws_session=_make_aws_session())
    assert isinstance(backend, SQSBackend)
