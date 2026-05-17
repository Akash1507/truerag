from datetime import datetime
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime


class SessionSummary(BaseModel):
    session_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str | None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class SessionDetailResponse(BaseModel):
    session_id: str
    messages: list[ConversationMessage]
    created_at: datetime
    updated_at: datetime


class ConversationSession(Document):
    session_id: str
    agent_id: str
    tenant_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "conversation_sessions"
        indexes = [
            IndexModel([("session_id", 1)], unique=True),
            IndexModel([("updated_at", 1)], expireAfterSeconds=172800),
        ]
