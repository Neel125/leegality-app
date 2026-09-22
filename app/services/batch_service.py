import json
from pathlib import Path

from app.config import Settings
from app.models.batch import Batch, BatchStatus
from app.models.document import Document, DocumentStatus
from app.models.finding import Finding
from app.repositories.batch_repository import BatchRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.finding_repository import FindingRepository
from app.schemas.batch import BatchAcceptedResponse, BatchDetailResponse, DocumentListResponse, ProgressCounts
from app.schemas.document import DocumentDetailResponse, DocumentSummary
from app.schemas.finding import FindingListResponse, FindingResponse, ReviewCounts
from app.services.errors import DomainValidationError, NotFoundError
from app.services.zip_archive_service import ZipArchiveService
from app.storage.base import StorageBackend


class BatchService:
    def __init__(
        self,
        settings: Settings,
        batches: BatchRepository,
        documents: DocumentRepository,
        findings: FindingRepository,
        zip_service: ZipArchiveService,
        storage: StorageBackend,
    ) -> None:
        self.settings = settings
        self.batches = batches
        self.documents = documents
        self.findings = findings
        self.zip_service = zip_service
        self.storage = storage

    async def create_batch(
        self, zip_bytes: bytes, original_filename: str, variables_raw: str
    ) -> BatchAcceptedResponse:
        self._assert_zip_filename(original_filename)
        variables = self._parse_variables(variables_raw)
        entries = self.zip_service.extract(zip_bytes)

        batch = Batch(
            status=BatchStatus.QUEUED,
            variables=variables,
            original_filename=original_filename,
        )
        await self.batches.add(batch)

        try:
            for entry in entries:
                path = self.storage.save(batch.id, entry.filename, entry.data)
                await self.documents.add(
                    Document(
                        batch_id=batch.id,
                        filename=entry.filename,
                        size_bytes=entry.size_bytes,
                        status=DocumentStatus.QUEUED,
                        storage_path=path,
                    )
                )
        except Exception:
            self.storage.delete_batch(batch.id)
            raise

        return BatchAcceptedResponse(
            id=batch.id,
            status=batch.status,
            document_count=len(entries),
            variables=variables,
            message=(
                "Batch accepted. Poll GET "
                f"/api/v1/batches/{batch.id} until processing finishes, "
                "then review pending findings."
            ),
            poll_url=f"/api/v1/batches/{batch.id}",
            review_url=f"/api/v1/batches/{batch.id}/findings?review_status=pending",
        )

    async def get_batch(self, batch_id: str) -> BatchDetailResponse:
        batch = await self._require_batch(batch_id)
        progress = await self._progress(batch_id)
        review = await self._review_counts(batch_id)
        return BatchDetailResponse(
            id=batch.id,
            status=batch.status,
            original_filename=batch.original_filename,
            variables=list(batch.variables),
            progress=progress,
            review=review,
            ready_for_review=review.pending > 0,
            review_url=f"/api/v1/batches/{batch.id}/findings?review_status=pending",
            created_at=batch.created_at,
            completed_at=batch.completed_at,
        )

    async def list_documents(self, batch_id: str, offset: int, limit: int) -> DocumentListResponse:
        await self._require_batch(batch_id)
        rows, total = await self.documents.list_for_batch(batch_id, offset, limit)
        items = [
            DocumentSummary(
                id=document.id,
                filename=document.filename,
                size_bytes=document.size_bytes,
                status=document.status,
                error=document.error,
                finding_count=finding_count,
            )
            for document, finding_count in rows
        ]
        return DocumentListResponse(items=items, total=total, offset=offset, limit=limit)

    async def get_document(self, document_id: str) -> DocumentDetailResponse:
        document = await self.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")
        findings = await self.findings.list_for_document(document_id)
        return DocumentDetailResponse(
            id=document.id,
            batch_id=document.batch_id,
            filename=document.filename,
            size_bytes=document.size_bytes,
            status=document.status,
            error=document.error,
            storage_path=document.storage_path,
            findings=[self._to_finding(item) for item in findings],
        )

    async def list_findings(
        self,
        batch_id: str,
        review_status: str | None,
        offset: int,
        limit: int,
    ) -> FindingListResponse:
        await self._require_batch(batch_id)
        items, total = await self.findings.list_for_batch(batch_id, review_status, offset, limit)
        return FindingListResponse(
            items=[self._to_finding(item) for item in items],
            total=total,
            offset=offset,
            limit=limit,
        )

    async def _require_batch(self, batch_id: str) -> Batch:
        batch = await self.batches.get(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found")
        return batch

    async def _progress(self, batch_id: str) -> ProgressCounts:
        counts = await self.documents.count_by_status(batch_id)
        pending = counts[DocumentStatus.QUEUED] + counts[DocumentStatus.PROCESSING]
        return ProgressCounts(
            total=sum(counts.values()),
            completed=counts[DocumentStatus.COMPLETED],
            failed=counts[DocumentStatus.FAILED],
            pending=pending,
        )

    async def _review_counts(self, batch_id: str) -> ReviewCounts:
        counts = await self.batches.review_counts(batch_id)
        return ReviewCounts(
            pending=counts["pending"],
            accepted=counts["accepted"],
            rejected=counts["rejected"],
        )

    @staticmethod
    def _to_finding(finding: Finding) -> FindingResponse:
        return FindingResponse(
            id=finding.id,
            document_id=finding.document_id,
            document_filename=finding.document.filename if finding.document else "",
            variable_name=finding.variable_name,
            value=finding.value,
            review_status=finding.review_status,
        )

    @staticmethod
    def _assert_zip_filename(filename: str) -> None:
        if Path(filename).suffix.lower() != ".zip":
            raise DomainValidationError("Uploaded file must be a .zip archive")

    @staticmethod
    def _parse_variables(raw: str) -> list[str]:
        """Accept JSON arrays, comma-separated names, or a single name (Postman-friendly)."""
        text = (raw or "").strip()
        if not text:
            raise DomainValidationError("variables must not be empty")

        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            inner = text[1:-1].strip()
            if inner.startswith("["):
                text = inner

        items: list[object]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            items = [part.strip() for part in text.split(",") if part.strip()]
        else:
            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, str):
                items = [parsed]
            else:
                raise DomainValidationError("variables must be a list of names")

        variables: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, str) or not item.strip():
                raise DomainValidationError("each variable must be a non-empty string")
            name = item.strip().strip("'\"")
            if not name or name in seen:
                continue
            seen.add(name)
            variables.append(name)
        if not variables:
            raise DomainValidationError("variables must be a non-empty list of names")
        return variables
