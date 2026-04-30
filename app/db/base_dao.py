from typing import Any, Generic, TypeVar

from beanie import Document

T = TypeVar("T", bound=Document)


class BaseDAO(Generic[T]):
    def __init__(self, model: type[T]) -> None:
        self._model = model

    async def find_one(self, query: dict[str, Any]) -> T | None:
        return await self._model.find_one(query)

    async def find(
        self,
        query: dict[str, Any],
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[T]:
        cursor = self._model.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list()

    async def insert_one(self, document: T) -> T:
        await document.insert()
        return document

    async def update(self, query: dict[str, Any], update_dict: dict[str, Any]) -> None:
        await self._model.find(query).update({"$set": update_dict})

    async def delete_one(self, query: dict[str, Any]) -> None:
        doc = await self._model.find_one(query)
        if doc:
            await doc.delete()

    async def delete_many(self, query: dict[str, Any]) -> None:
        await self._model.find(query).delete()

    async def count(self, query: dict[str, Any]) -> int:
        return await self._model.find(query).count()
