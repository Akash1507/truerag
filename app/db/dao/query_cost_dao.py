from typing import Any

from app.db.base_dao import BaseDAO
from app.models.query_cost import QueryCost


class QueryCostDAO(BaseDAO[QueryCost]):
    def __init__(self) -> None:
        super().__init__(QueryCost)

    async def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cursor = QueryCost.get_motor_collection().aggregate(pipeline)
        return await cursor.to_list(length=None)


query_cost_dao = QueryCostDAO()
