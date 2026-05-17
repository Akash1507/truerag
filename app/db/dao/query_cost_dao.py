from datetime import UTC, datetime
from typing import Any

from app.db.base_dao import BaseDAO
from app.models.query_cost import QueryCost


class QueryCostDAO(BaseDAO[QueryCost]):
    def __init__(self) -> None:
        super().__init__(QueryCost)

    async def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cursor = QueryCost.get_motor_collection().aggregate(pipeline)
        return await cursor.to_list(length=None)

    async def get_monthly_token_total(self, tenant_id: str, year_month: str) -> int:
        month_start = datetime.strptime(f"{year_month}-01", "%Y-%m-%d").replace(tzinfo=UTC)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)

        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "tenant_id": tenant_id,
                    "timestamp": {"$gte": month_start, "$lt": next_month_start},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "prompt_tokens_total": {"$sum": "$prompt_tokens"},
                    "completion_tokens_total": {"$sum": "$completion_tokens"},
                }
            },
        ]
        result = await self.aggregate(pipeline)
        if not result:
            return 0
        return int(result[0].get("prompt_tokens_total", 0)) + int(
            result[0].get("completion_tokens_total", 0)
        )


query_cost_dao = QueryCostDAO()
