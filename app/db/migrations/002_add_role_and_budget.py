"""One-off migration for tenant role and monthly token budget.

Usage:
    python -m app.db.migrations.002_add_role_and_budget
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings


async def run() -> Mapping[str, int]:
    settings = get_settings()
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)  # type: ignore[type-arg]
    try:
        db = client[settings.mongodb_database]
        result = await db["tenants"].update_many(
            {"role": {"$exists": False}},
            {"$set": {"role": "agent_owner", "monthly_token_budget": None}},
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }
    finally:
        client.close()


if __name__ == "__main__":
    summary = asyncio.run(run())
    print(summary)
