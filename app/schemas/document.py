from pydantic import BaseModel

from app.schemas.finding import FindingResponse


class DocumentSummary(BaseModel):
    id: str
    filename: str
    size_bytes: int
    status: str
    error: str | None
    finding_count: int


class DocumentDetailResponse(BaseModel):
    id: str
    batch_id: str
    filename: str
    size_bytes: int
    status: str
    error: str | None
    storage_path: str
    findings: list[FindingResponse]
