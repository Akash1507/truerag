from __future__ import annotations

import asyncio
from uuid import uuid4

from app.interfaces.queue_backend import QueueBackend, QueueMessage


class LocalQueueBackend(QueueBackend):
    """In-process queue backend for local development and tests."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueueMessage] = asyncio.Queue()

    async def send(self, payload: dict[str, object]) -> None:
        await self._queue.put(
            QueueMessage(
                message_id=str(uuid4()),
                body=payload,
                receipt_handle=str(uuid4()),
                receive_count=1,
            )
        )

    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        if max_messages <= 0:
            return []

        try:
            first_message = await asyncio.wait_for(self._queue.get(), timeout=wait_seconds)
        except asyncio.TimeoutError:
            return []

        messages: list[QueueMessage] = [first_message]
        while len(messages) < max_messages:
            try:
                messages.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    async def delete(self, receipt_handle: str) -> None:
        # Local backend acknowledges on receive; explicit delete is a no-op.
        _ = receipt_handle
