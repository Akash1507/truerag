from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from app.models.chunk import Chunk


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: list[Chunk]) -> str: ...

    async def stream_generate(
        self,
        prompt: str,
        context: list[Chunk],
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError("Streaming is not implemented for this LLM provider")
