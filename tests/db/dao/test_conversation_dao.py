from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.db.dao.conversation_dao import ConversationSessionDAO
from app.models.conversation import ConversationSession


@pytest.mark.asyncio
async def test_create_session_generates_uuid_and_persists() -> None:
    dao = ConversationSessionDAO()
    with patch.object(dao, "insert_one", AsyncMock()) as insert_one:
        session = await dao.create_session(agent_id="agent-1", tenant_id="tenant-1")

    assert session.session_id
    assert session.agent_id == "agent-1"
    assert session.tenant_id == "tenant-1"
    assert session.messages == []
    insert_one.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_get_session_scopes_by_agent_and_tenant() -> None:
    dao = ConversationSessionDAO()
    expected = ConversationSession.model_construct(
        session_id="session-1",
        agent_id="agent-1",
        tenant_id="tenant-1",
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with patch.object(dao, "find_one", AsyncMock(return_value=expected)) as find_one:
        found = await dao.get_session("session-1", "agent-1", "tenant-1")

    assert found is expected
    find_one.assert_awaited_once_with(
        {
            "session_id": "session-1",
            "agent_id": "agent-1",
            "tenant_id": "tenant-1",
        }
    )


@pytest.mark.asyncio
async def test_append_messages_updates_timestamp_and_pushes_user_and_assistant() -> None:
    dao = ConversationSessionDAO()
    update_mock = AsyncMock()
    find_cursor = AsyncMock()
    find_cursor.update = update_mock

    with patch.object(ConversationSession, "find", return_value=find_cursor):
        await dao.append_messages("session-1", "scrubbed user", "assistant answer")

    update_mock.assert_awaited_once()
    update_payload = update_mock.await_args.args[0]
    assert "$push" in update_payload
    pushed = update_payload["$push"]["messages"]["$each"]
    assert pushed[0]["role"] == "user"
    assert pushed[0]["content"] == "scrubbed user"
    assert pushed[1]["role"] == "assistant"
    assert pushed[1]["content"] == "assistant answer"
    assert "$set" in update_payload
    assert "updated_at" in update_payload["$set"]


def test_conversation_session_declares_ttl_index() -> None:
    index_docs = [index.document for index in ConversationSession.Settings.indexes]
    assert any(doc.get("unique") and doc.get("key") == {"session_id": 1} for doc in index_docs)
    assert any(
        doc.get("expireAfterSeconds") == 172800 and doc.get("key") == {"updated_at": 1}
        for doc in index_docs
    )
