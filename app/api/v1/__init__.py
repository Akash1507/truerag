from fastapi import APIRouter

from app.api.v1 import agents, documents, eval, observability, query, tenants

router = APIRouter(prefix="/v1")

router.include_router(tenants.router, prefix="/tenants", tags=["tenants"])
router.include_router(agents.router, prefix="/agents", tags=["agents"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(query.router, prefix="/query", tags=["query"])
router.include_router(eval.router, prefix="/eval", tags=["eval"])
router.include_router(observability.router, tags=["observability"])
