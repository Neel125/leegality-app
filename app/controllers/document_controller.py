from fastapi import APIRouter, Depends, status
from fastapi_utils.cbv import cbv

from app.dependencies import get_batch_service
from app.schemas.document import DocumentDetailResponse
from app.services.batch_service import BatchService


document_router = APIRouter(prefix="/documents", tags=["documents"])

@cbv(document_router)
class DocumentController():

    @document_router.get("/{document_id}", response_model=DocumentDetailResponse)
    async def get_document(
        self,
        document_id: str,
        service: BatchService = Depends(get_batch_service),
    ) -> DocumentDetailResponse:
        return await service.get_document(document_id)
