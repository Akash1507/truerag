from pydantic import AwareDatetime, BaseModel, Field


class ChunkMetadata(BaseModel):
    tenant_id: str
    agent_id: str
    document_id: str
    chunk_index: int = Field(ge=0)
    chunking_strategy: str
    timestamp: AwareDatetime
    version: int = Field(ge=0)


class Chunk(BaseModel):
    text: str
    metadata: ChunkMetadata


class VectorRecord(BaseModel):
    id: str  # unique ID for the vector (e.g. f"{document_id}_{chunk_index}")
    vector: list[float]
    metadata: ChunkMetadata
    text: str  # stored for retrieval response reconstruction


class VectorResult(BaseModel):
    id: str
    score: float
    metadata: ChunkMetadata
    text: str
