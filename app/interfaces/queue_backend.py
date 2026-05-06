from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class QueueMessage:
    message_id: str
    body: dict[str, object]
    receipt_handle: str
    receive_count: int


class QueueBackend(ABC):
    @abstractmethod
    async def send(self, payload: dict[str, object]) -> None:
        """Enqueue one JSON-serializable payload."""

    @abstractmethod
    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        """Receive up to max_messages from queue."""

    @abstractmethod
    async def delete(self, receipt_handle: str) -> None:
        """Acknowledge a processed message."""
