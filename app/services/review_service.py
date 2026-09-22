from app.models.finding import ReviewStatus
from app.repositories.finding_repository import FindingRepository
from app.schemas.finding import ReviewResponse
from app.services.errors import DomainValidationError, NotFoundError


class ReviewService:
    def __init__(self, findings: FindingRepository) -> None:
        self.findings = findings

    async def review(self, finding_id: str, decision: ReviewStatus) -> ReviewResponse:
        if decision not in {ReviewStatus.ACCEPTED, ReviewStatus.REJECTED}:
            raise DomainValidationError("decision must be accepted or rejected")

        finding = await self.findings.get(finding_id)
        if finding is None:
            raise NotFoundError(f"Finding {finding_id} not found")

        finding.review_status = decision
        filename = finding.document.filename if finding.document else ""
        return ReviewResponse(
            id=finding.id,
            document_id=finding.document_id,
            document_filename=filename,
            variable_name=finding.variable_name,
            value=finding.value,
            review_status=finding.review_status,
        )
