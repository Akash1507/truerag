from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any, cast

from app.interfaces.queue_backend import QueueBackend, QueueMessage

_CONSUMER_GROUP_ID = "truerag-ingestion-workers"


class KafkaBackend(QueueBackend):
    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._consumer: Any = None
        self._producer: Any = None

    def _get_producer(self) -> Any:
        if self._producer is None:
            kafka_module = importlib.import_module("kafka")
            producer_cls = getattr(kafka_module, "KafkaProducer")
            self._producer = producer_cls(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda value: json.dumps(value).encode(),
            )
        return self._producer

    def _get_consumer(self, wait_seconds: int) -> Any:
        if self._consumer is None:
            kafka_module = importlib.import_module("kafka")
            consumer_cls = getattr(kafka_module, "KafkaConsumer")
            self._consumer = consumer_cls(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=_CONSUMER_GROUP_ID,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                consumer_timeout_ms=wait_seconds * 1000,
                value_deserializer=lambda value: json.loads(value.decode()),
            )
        else:
            # Update the timeout on the existing consumer's config so long-poll
            # duration is respected even when the consumer is reused.
            self._consumer.config["consumer_timeout_ms"] = wait_seconds * 1000
        return self._consumer

    async def send(self, payload: dict[str, object]) -> None:
        def _send() -> None:
            producer = self._get_producer()
            producer.send(self._topic, payload)
            producer.flush()

        await asyncio.to_thread(_send)

    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        def _poll() -> list[QueueMessage]:
            consumer = self._get_consumer(wait_seconds)
            messages: list[QueueMessage] = []
            try:
                for raw_message in consumer:
                    body = cast(dict[str, object], raw_message.value)
                    messages.append(
                        QueueMessage(
                            message_id=f"{raw_message.partition}-{raw_message.offset}",
                            body=body,
                            receipt_handle=f"{raw_message.partition}:{raw_message.offset}",
                            receive_count=1,
                        )
                    )
                    if len(messages) >= max_messages:
                        break
            except StopIteration:
                pass
            return messages

        return await asyncio.to_thread(_poll)

    async def delete(self, receipt_handle: str) -> None:
        # Offset commits handled by auto-commit on the persistent consumer.
        _ = receipt_handle
