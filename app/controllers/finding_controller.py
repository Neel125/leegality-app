from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv

from app.dependencies import get_review_service
from app.models.finding import ReviewStatus
from app.schemas.finding import ReviewRequest, ReviewResponse
from app.services.review_service import ReviewService


finding_router = APIRouter(prefix="/findings", tags=["findings"])

@cbv(finding_router)
class FindingController():

    @finding_router.post("/{finding_id}/review", response_model=ReviewResponse)
    async def review_finding(
        self,
        finding_id: str,
        body: ReviewRequest,
        service: ReviewService = Depends(get_review_service),
    ) -> ReviewResponse:
        return await service.review(finding_id, ReviewStatus(body.decision))
