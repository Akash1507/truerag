import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import cohere

from app.interfaces.reranker import Reranker
from app.models.chunk import Chunk
from app.utils.cost_tracker import record_reranker_call
from app.utils.retry import retry
from app.utils.secrets import get_secret

COHERE_SECRET_NAME = "cohere/api_key"
COHERE_RERANK_MODEL = "rerank-english-v3.0"


def _run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


class CohereReranker(Reranker):
    def __init__(self) -> None:
        self._api_key: str | None = None

    @retry()
    async def _rerank_call(self, client: cohere.ClientV2, query: str, documents: list[str], top_k: int) -> Any:
        return await asyncio.to_thread(
            client.rerank,
            model=COHERE_RERANK_MODEL,
            query=query,
            documents=documents,
            top_n=top_k,
        )

    def _get_api_key(self) -> str:
        if self._api_key is None:
            self._api_key = str(_run_coro_sync(get_secret(COHERE_SECRET_NAME)))
        return self._api_key

    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
        if not chunks:
            return []

        client = cohere.ClientV2(api_key=self._get_api_key())
        response = _run_coro_sync(
            self._rerank_call(client=client, query=query, documents=[chunk.text for chunk in chunks], top_k=top_k)
        )
        record_reranker_call()
        results = getattr(response, "results", [])
        return [chunks[result.index] for result in results]
