from abc import ABC, abstractmethod

from app.models.chunk import Chunk


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: list[Chunk]) -> str: ...
