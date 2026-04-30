from app.db.base_dao import BaseDAO
from app.models.agent import AgentDocument


class AgentDAO(BaseDAO[AgentDocument]):
    def __init__(self) -> None:
        super().__init__(AgentDocument)


agent_dao = AgentDAO()
