from app.interfaces.reranker import Reranker
from app.models.chunk import Chunk


class PassthroughReranker(Reranker):
    """No-op reranker for agents configured with reranker: none.

    Returns chunks unchanged in their original order.
    """

    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
        # Pure passthrough — do NOT slice to top_k here.
        # Caller applies top_k filtering after retrieval if needed.
        return chunks
