from fastapi import APIRouter, Depends, Query, Request, UploadFile, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.core.errors import InvalidCursorError
from app.models.document import DocumentListResponse, DocumentStatusResponse, DocumentUploadResponse
from app.models.tenant import TenantDocument
from app.services import ingestion_service
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
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    aws_session = request.app.state.aws_session
    return await ingestion_service.upload_document(
        file=file,
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        db=db,
        aws_session=aws_session,
        settings=settings,
    )


@router.get(
    "/{agent_id}/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
)
async def get_document_status_route(
    agent_id: str,
    document_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentStatusResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    aws_session = request.app.state.aws_session
    return await ingestion_service.get_document_status(
        document_id=document_id,
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        db=db,
        aws_session=aws_session,
        settings=settings,
    )


@router.get(
    "/{agent_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents_route(
    agent_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentListResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    try:
        items, next_cursor = await ingestion_service.list_documents(
            agent_id=agent_id,
            tenant_id=caller.tenant_id,
            db=db,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc
    return DocumentListResponse(items=items, next_cursor=next_cursor)
