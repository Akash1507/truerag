from datetime import UTC, datetime
from uuid import uuid4

from app.db.base_dao import BaseDAO
from app.models.conversation import ConversationMessage, ConversationSession


class ConversationSessionDAO(BaseDAO[ConversationSession]):
    def __init__(self) -> None:
        super().__init__(ConversationSession)

    async def create_session(self, agent_id: str, tenant_id: str) -> ConversationSession:
        now = datetime.now(UTC)
        session = ConversationSession.model_construct(
            session_id=str(uuid4()),
            agent_id=agent_id,
            tenant_id=tenant_id,
            messages=[],
            created_at=now,
            updated_at=now,
        )
        await self.insert_one(session)
        return session

    async def get_session(
        self,
        session_id: str,
        agent_id: str,
        tenant_id: str,
    ) -> ConversationSession | None:
        return await self.find_one(
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
            }
        )

    async def list_sessions(
        self,
        agent_id: str,
        tenant_id: str,
        limit: int = 50,
    ) -> list[ConversationSession]:
        return (
            await self._model.find({"agent_id": agent_id, "tenant_id": tenant_id})
            .sort("-updated_at")
            .limit(limit)
            .to_list()
        )

    async def append_messages(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
        now = datetime.now(UTC)
        user_message = ConversationMessage(role="user", content=user_msg, timestamp=now)
        assistant_message = ConversationMessage(role="assistant", content=assistant_msg, timestamp=now)
        await self._model.find({"session_id": session_id}).update(
            {
                "$push": {
                    "messages": {
                        "$each": [
                            user_message.model_dump(),
                            assistant_message.model_dump(),
                        ]
                    }
                },
                "$set": {"updated_at": now},
            }
        )


conversation_dao = ConversationSessionDAO()
