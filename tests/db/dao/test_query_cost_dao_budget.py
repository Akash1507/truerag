from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.db.dao.query_cost_dao import QueryCostDAO


class _FakeCursor:
    def __init__(self, payload: list[dict]) -> None:
        self._payload = payload

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._payload


class _FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def aggregate(self, pipeline: list[dict]) -> _FakeCursor:
        match = pipeline[0]["$match"]
        tenant_id = match["tenant_id"]
        start = match["timestamp"]["$gte"]
        end = match["timestamp"]["$lt"]

        prompt_total = 0
        completion_total = 0
        for doc in self._docs:
            if doc["tenant_id"] != tenant_id:
                continue
            ts = doc["timestamp"]
            if start <= ts < end:
                prompt_total += doc["prompt_tokens"]
                completion_total += doc["completion_tokens"]

        if prompt_total == 0 and completion_total == 0:
            return _FakeCursor([])
        return _FakeCursor(
            [
                {
                    "_id": None,
                    "prompt_tokens_total": prompt_total,
                    "completion_tokens_total": completion_total,
                }
            ]
        )


@pytest.mark.asyncio
async def test_get_monthly_token_total_sums_only_requested_month() -> None:
    dao = QueryCostDAO()
    docs = [
        {
            "tenant_id": "tenant-1",
            "timestamp": datetime(2026, 5, 3, tzinfo=UTC),
            "prompt_tokens": 100,
            "completion_tokens": 25,
        },
        {
            "tenant_id": "tenant-1",
            "timestamp": datetime(2026, 5, 20, tzinfo=UTC),
            "prompt_tokens": 200,
            "completion_tokens": 50,
        },
        {
            "tenant_id": "tenant-1",
            "timestamp": datetime(2026, 4, 28, tzinfo=UTC),
            "prompt_tokens": 999,
            "completion_tokens": 999,
        },
        {
            "tenant_id": "tenant-2",
            "timestamp": datetime(2026, 5, 10, tzinfo=UTC),
            "prompt_tokens": 999,
            "completion_tokens": 999,
        },
    ]

    with patch("app.db.dao.query_cost_dao.QueryCost.get_motor_collection", return_value=_FakeCollection(docs)):
        total = await dao.get_monthly_token_total("tenant-1", "2026-05")

    assert total == 375


@pytest.mark.asyncio
async def test_get_monthly_token_total_returns_zero_when_no_docs() -> None:
    dao = QueryCostDAO()
    with patch(
        "app.db.dao.query_cost_dao.QueryCost.get_motor_collection",
        return_value=_FakeCollection([]),
    ):
        total = await dao.get_monthly_token_total("tenant-1", "2026-05")

    assert total == 0
