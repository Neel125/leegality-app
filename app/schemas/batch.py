from datetime import datetime

from pydantic import BaseModel

from app.schemas.document import DocumentSummary
from app.schemas.finding import ReviewCounts


class ProgressCounts(BaseModel):
    total: int
    completed: int
    failed: int
    pending: int


class BatchAcceptedResponse(BaseModel):
    id: str
    status: str
    document_count: int
    variables: list[str]
    message: str
    poll_url: str
    review_url: str


class BatchDetailResponse(BaseModel):
    id: str
    status: str
    original_filename: str
    variables: list[str]
    progress: ProgressCounts
    review: ReviewCounts
    ready_for_review: bool
    review_url: str
    created_at: datetime
    completed_at: datetime | None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int
    offset: int
    limit: int
