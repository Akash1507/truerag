import argparse
import asyncio
import time

import httpx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed a tenant and an agent for local load testing."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="TrueRAG API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--admin-key",
        required=True,
        help="Admin API key (set via ADMIN_API_KEY env var on the server)",
    )
    parser.add_argument(
        "--tenant-name",
        default=f"locust-tenant-{int(time.time())}",
        help="Tenant name to create",
    )
    parser.add_argument(
        "--agent-name",
        default=f"locust-agent-{int(time.time())}",
        help="Agent name to create",
    )
    return parser.parse_args()


async def _seed(base_url: str, admin_key: str, tenant_name: str, agent_name: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        admin_headers = {"X-API-Key": admin_key}
        tenant_resp = await client.post(
            "/v1/tenants",
            json={"name": tenant_name},
            headers=admin_headers,
        )
        tenant_resp.raise_for_status()
        tenant = tenant_resp.json()

        api_key = tenant["api_key"]
        tenant_id = tenant["tenant_id"]

        headers = {"X-API-Key": api_key}
        agent_payload = {
            "name": agent_name,
            "chunking_strategy": "fixed_size",
            "vector_store": "pgvector",
            "embedding_provider": "openai",
            "llm_provider": "anthropic",
            "retrieval_mode": "dense",
            "reranker": "none",
            "top_k": 5,
            "semantic_cache_enabled": False,
        }
        agent_resp = await client.post("/v1/agents", json=agent_payload, headers=headers)
        agent_resp.raise_for_status()
        agent = agent_resp.json()

        print("Seed complete")
        print(f"tenant_id={tenant_id}")
        print(f"agent_id={agent['agent_id']}")
        print("")
        print("Export these before running locust:")
        print(f"export TRUERAG_API_KEY='{api_key}'")
        print(f"export TRUERAG_AGENT_ID='{agent['agent_id']}'")


async def main() -> None:
    args = _parse_args()
    await _seed(
        base_url=args.base_url.rstrip("/"),
        admin_key=args.admin_key,
        tenant_name=args.tenant_name,
        agent_name=args.agent_name,
    )


if __name__ == "__main__":
    asyncio.run(main())
