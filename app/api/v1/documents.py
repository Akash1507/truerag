from fastapi import APIRouter, Depends, Request, UploadFile, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.models.document import DocumentUploadResponse
from app.models.tenant import TenantDocument
from app.services import ingestion_service

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
