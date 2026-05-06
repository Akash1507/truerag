from __future__ import annotations

import importlib
import json
from typing import cast

from app.interfaces.queue_backend import QueueBackend, QueueMessage


class KafkaBackend(QueueBackend):
    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic

    async def send(self, payload: dict[str, object]) -> None:
        kafka_module = importlib.import_module("kafka")
        producer_cls = getattr(kafka_module, "KafkaProducer")
        producer = producer_cls(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode(),
        )
        try:
            producer.send(self._topic, payload)
            producer.flush()
        finally:
            producer.close()

    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        kafka_module = importlib.import_module("kafka")
        consumer_cls = getattr(kafka_module, "KafkaConsumer")
        consumer = consumer_cls(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            consumer_timeout_ms=wait_seconds * 1000,
            value_deserializer=lambda value: json.loads(value.decode()),
            enable_auto_commit=True,
        )
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
        finally:
            consumer.close()
        return messages

    async def delete(self, receipt_handle: str) -> None:
        # Offset commit/ack handling is managed by the consumer settings.
        _ = receipt_handle
