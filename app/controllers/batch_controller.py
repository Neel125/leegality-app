from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi_utils.cbv import cbv
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_batch_service, get_session
from app.models.finding import ReviewStatus
from app.schemas.batch import BatchAcceptedResponse, BatchDetailResponse, DocumentListResponse
from app.schemas.finding import FindingListResponse
from app.services.batch_service import BatchService
from app.services.errors import DomainValidationError


batch_router = APIRouter(prefix="/batches", tags=["batches"])


@cbv(batch_router)
class BatchController():


    @batch_router.post("/", response_model=BatchAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
    async def create_batch(
        self,
        request: Request,
        db_session: AsyncSession = Depends(get_session),
        variables: str = Form(
            ...,
            description='JSON array or comma-separated names, e.g. ["effective_date","governing_law"] or effective_date,governing_law',
        ),
        file: UploadFile = File(..., description="ZIP archive of contract documents"),
    ) -> BatchAcceptedResponse:
        filename = file.filename or "upload.zip"
        zip_bytes = await file.read()
        return await get_batch_service(request, db_session).create_batch(zip_bytes, filename, variables)

    @batch_router.get("/{batch_id}", response_model=BatchDetailResponse)
    async def get_batch(
        self,
        request: Request,
        batch_id: str,
        service: BatchService = Depends(get_batch_service),
    ) -> BatchDetailResponse:
        return await service.get_batch(batch_id)

    @batch_router.get("/{batch_id}/documents", response_model=DocumentListResponse)
    async def list_documents(
        self,
        request: Request,
        batch_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        service: BatchService = Depends(get_batch_service),
    ) -> DocumentListResponse:
        return await service.list_documents(batch_id, offset, limit)

    @batch_router.get("/{batch_id}/findings", response_model=FindingListResponse)
    async def list_findings(
        self,
        request: Request,
        batch_id: str,
        review_status: str | None = Query(default=None),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        service: BatchService = Depends(get_batch_service),
    ) -> FindingListResponse:
        status_filter: str | None = None
        if review_status is not None:
            try:
                status_filter = ReviewStatus(review_status).value
            except ValueError as exc:
                raise DomainValidationError(
                    "review_status must be pending, accepted, or rejected"
                ) from exc
        return await service.list_findings(batch_id, status_filter, offset, limit)
