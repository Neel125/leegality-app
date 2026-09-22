from typing import Literal

from pydantic import BaseModel, Field


class ReviewCounts(BaseModel):
    pending: int
    accepted: int
    rejected: int


class FindingResponse(BaseModel):
    id: str
    document_id: str
    document_filename: str
    variable_name: str
    value: str
    review_status: str


class FindingListResponse(BaseModel):
    items: list[FindingResponse]
    total: int
    offset: int
    limit: int


class ReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected"] = Field(..., description="accepted or rejected")


class ReviewResponse(FindingResponse):
    pass
