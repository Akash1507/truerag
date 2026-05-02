from app.core.errors import ProviderUnavailableError
from app.interfaces.reranker import Reranker
from app.models.chunk import Chunk

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

try:
    from sentence_transformers import CrossEncoder as SentenceTransformerCrossEncoder
except ImportError:  # pragma: no cover
    SentenceTransformerCrossEncoder = None


class CrossEncoderReranker(Reranker):
    def __init__(self) -> None:
        if SentenceTransformerCrossEncoder is None:
            raise ProviderUnavailableError("sentence-transformers is not installed")
        self._model = SentenceTransformerCrossEncoder(MODEL_NAME)

    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
        if not chunks:
            return []
        pairs = [(query, chunk.text) for chunk in chunks]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(chunks, scores, strict=False), key=lambda item: float(item[1]), reverse=True)
        return [chunk for chunk, _ in ranked[:top_k]]
