from datetime import datetime, timezone

from app.extraction.base import ExtractionClient, ExtractionRequest
from app.models.batch import Batch, BatchStatus
from app.models.document import Document, DocumentStatus
from app.models.finding import Finding, ReviewStatus
from app.repositories.batch_repository import BatchRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.finding_repository import FindingRepository


class DocumentProcessingService:
    def __init__(
        self,
        batches: BatchRepository,
        documents: DocumentRepository,
        findings: FindingRepository,
        extractor: ExtractionClient,
    ) -> None:
        self.batches = batches
        self.documents = documents
        self.findings = findings
        self.extractor = extractor

    async def process_claimed(self, document: Document) -> None:
        batch = await self.batches.get(document.batch_id)
        if batch is None:
            document.status = DocumentStatus.FAILED
            document.error = "Parent batch is missing"
            return

        await self._mark_batch_processing(batch)
        try:
            values = await self.extractor.extract(
                ExtractionRequest(
                    document_id=document.id,
                    filename=document.filename,
                    storage_path=document.storage_path,
                    variables=list(batch.variables),
                )
            )
            for name, value in values.items():
                await self.findings.add(
                    Finding(
                        document_id=document.id,
                        variable_name=name,
                        value=str(value),
                        review_status=ReviewStatus.PENDING,
                    )
                )
            document.status = DocumentStatus.COMPLETED
            document.error = None
        except Exception as exc:  # noqa: BLE001 - isolate one document failure
            document.status = DocumentStatus.FAILED
            document.error = str(exc)[:2000]
        await self.refresh_batch_status(batch)

    async def refresh_batch_status(self, batch: Batch) -> None:
        counts = await self.documents.count_by_status(batch.id)
        queued = counts[DocumentStatus.QUEUED]
        processing = counts[DocumentStatus.PROCESSING]
        completed = counts[DocumentStatus.COMPLETED]
        failed = counts[DocumentStatus.FAILED]
        total = queued + processing + completed + failed

        if total == 0:
            return
        if queued == total:
            batch.status = BatchStatus.QUEUED
            return
        if queued + processing > 0:
            batch.status = BatchStatus.PROCESSING
            batch.completed_at = None
            return
        if failed == total:
            batch.status = BatchStatus.FAILED
        else:
            batch.status = BatchStatus.COMPLETED
        batch.completed_at = datetime.now(timezone.utc)

    async def _mark_batch_processing(self, batch: Batch) -> None:
        if batch.status in {BatchStatus.QUEUED, BatchStatus.PROCESSING}:
            batch.status = BatchStatus.PROCESSING
            batch.completed_at = None
