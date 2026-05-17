from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


class QueryRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    top_k: int | None = Field(default=None, ge=1, le=100)
    filters: dict[str, str] | None = None
    output_format: Literal["text", "json"] | None = None
    session_id: str | None = None
    stream: bool = False


class Citation(BaseModel):
    document_name: str
    chunk_text: str
    page_reference: str | None = None


class QueryResponse(BaseModel):
    answer: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    citations: list[Citation]
    latency_ms: int
    session_id: str | None = None
    hallucination_risk: Literal["low", "medium", "high"] | None = None


class StreamEvent(BaseModel):
    type: Literal["token", "done", "error"]
    token: str | None = None
    confidence: Annotated[float | None, Field(default=None, ge=0.0, le=1.0)]
    citations: list[Citation] | None = None
    latency_ms: int | None = None
    session_id: str | None = None
    message: str | None = None
