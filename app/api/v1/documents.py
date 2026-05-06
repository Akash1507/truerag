from fastapi import APIRouter, Depends, Query, Request, UploadFile, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.models.document import (
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    ReindexResponse,
)
from app.models.tenant import TenantDocument
from app.services.ingestion_service import ingestion_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post(
    "/{agent_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
)
async def upload_document_route(
    agent_id: str,
    file: UploadFile,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentUploadResponse:
    return await ingestion_service.upload_document(
        file=file,
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        aws_session=request.app.state.aws_session,
        settings=get_settings(),
    )


@router.get(
    "/{agent_id}/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
)
async def get_document_status_route(
    agent_id: str,
    document_id: str,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentStatusResponse:
    return await ingestion_service.get_document_status(
        document_id=document_id,
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
    )


@router.get(
    "/{agent_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents_route(
    agent_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentListResponse:
    return await ingestion_service.list_documents(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/{agent_id}/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReindexResponse,
)
async def reindex_agent_route(
    agent_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> ReindexResponse:
    return await ingestion_service.reindex_agent(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        aws_session=request.app.state.aws_session,
        settings=get_settings(),
    )


@router.delete(
    "/{agent_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document_route(
    agent_id: str,
    document_id: str,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> None:
    await ingestion_service.delete_document(
        document_id=document_id,
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
    )
