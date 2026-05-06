from __future__ import annotations

import pytest

from app.interfaces.queue_backend import QueueBackend, QueueMessage


class StubQueueBackend(QueueBackend):
    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []
        self.deleted: list[str] = []

    async def send(self, payload: dict[str, object]) -> None:
        self.messages.append(
            QueueMessage(
                message_id="msg-1",
                body=payload,
                receipt_handle="receipt-1",
                receive_count=1,
            )
        )

    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        _ = wait_seconds
        return self.messages[:max_messages]

    async def delete(self, receipt_handle: str) -> None:
        self.deleted.append(receipt_handle)


def test_queue_message_dataclass_fields() -> None:
    message = QueueMessage(
        message_id="m-1",
        body={"key": "value"},
        receipt_handle="r-1",
        receive_count=2,
    )
    assert message.message_id == "m-1"
    assert message.body["key"] == "value"
    assert message.receipt_handle == "r-1"
    assert message.receive_count == 2


@pytest.mark.asyncio
async def test_queue_backend_contract_roundtrip() -> None:
    backend = StubQueueBackend()
    await backend.send({"job_id": "job-1"})
    messages = await backend.receive(max_messages=1, wait_seconds=1)
    assert len(messages) == 1
    assert messages[0].body["job_id"] == "job-1"
    await backend.delete(messages[0].receipt_handle)
    assert backend.deleted == ["receipt-1"]
