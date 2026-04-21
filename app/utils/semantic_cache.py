async def invalidate(agent_id: str) -> None:
    """No-op stub. Epic 8 replaces this body with pgvector cache invalidation.

    Call sites: await semantic_cache.invalidate(agent_id)
    """
    pass
