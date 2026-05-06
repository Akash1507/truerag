from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

import aioboto3

from app.core.config import Settings
from app.interfaces.queue_backend import QueueBackend, QueueMessage


class SQSBackend(QueueBackend):
    def __init__(self, aws_session: aioboto3.Session, settings: Settings) -> None:
        self._session = aws_session
        self._settings = settings

    async def send(self, payload: dict[str, object]) -> None:
        async with self._session.client(
            "sqs",
            region_name=self._settings.aws_region,
            endpoint_url=self._settings.aws_endpoint_url,
        ) as sqs:
            await sqs.send_message(
                QueueUrl=self._settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps(payload),
            )

    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        async with self._session.client(
            "sqs",
            region_name=self._settings.aws_region,
            endpoint_url=self._settings.aws_endpoint_url,
        ) as sqs:
            response = cast(
                Mapping[str, object],
                await sqs.receive_message(
                    QueueUrl=self._settings.sqs_ingestion_queue_url,
                    MaxNumberOfMessages=max_messages,
                    WaitTimeSeconds=wait_seconds,
                    AttributeNames=["ApproximateReceiveCount"],
                ),
            )

        raw_messages = response.get("Messages")
        if not isinstance(raw_messages, list):
            return []

        messages: list[QueueMessage] = []
        for raw_message in raw_messages:
            if not isinstance(raw_message, Mapping):
                continue

            raw_body = raw_message.get("Body")
            body: dict[str, object]
            if isinstance(raw_body, str):
                parsed = json.loads(raw_body)
                body = parsed if isinstance(parsed, dict) else {}
            elif isinstance(raw_body, (bytes, bytearray)):
                parsed = json.loads(raw_body.decode())
                body = parsed if isinstance(parsed, dict) else {}
            else:
                body = {}

            raw_attributes = raw_message.get("Attributes")
            attributes = raw_attributes if isinstance(raw_attributes, Mapping) else {}
            raw_receive_count = attributes.get("ApproximateReceiveCount", "1")
            receive_count = int(raw_receive_count) if isinstance(raw_receive_count, str) else 1

            messages.append(
                QueueMessage(
                    message_id=str(raw_message.get("MessageId", "")),
                    body=body,
                    receipt_handle=str(raw_message.get("ReceiptHandle", "")),
                    receive_count=receive_count,
                )
            )

        return messages

    async def delete(self, receipt_handle: str) -> None:
        async with self._session.client(
            "sqs",
            region_name=self._settings.aws_region,
            endpoint_url=self._settings.aws_endpoint_url,
        ) as sqs:
            await sqs.delete_message(
                QueueUrl=self._settings.sqs_ingestion_queue_url,
                ReceiptHandle=receipt_handle,
            )
