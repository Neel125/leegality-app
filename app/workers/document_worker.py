import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.extraction.base import ExtractionClient
from app.repositories.batch_repository import BatchRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.finding_repository import FindingRepository
from app.services.document_processing_service import DocumentProcessingService

logger = logging.getLogger(__name__)


class DocumentProcessingWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractor: ExtractionClient,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.extractor = extractor
        self.concurrency = max(1, settings.worker_concurrency)
        self.poll_seconds = max(settings.worker_poll_interval_ms, 10) / 1000
        self._stopped = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def run(self) -> None:
        self._tasks = [asyncio.create_task(self._loop()) for _ in range(self.concurrency)]
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._stopped.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _loop(self) -> None:
        print("Document worker loop started")
        while not self._stopped.is_set():
            try:
                worked = await self._process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Document worker loop failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_seconds)
                except asyncio.TimeoutError:
                    pass

    async def _process_one(self) -> bool:
        async with self.session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.claim_next_queued()
            if document is None:
                return False
            service = DocumentProcessingService(
                batches=BatchRepository(session),
                documents=documents,
                findings=FindingRepository(session),
                extractor=self.extractor,
            )
            await service.process_claimed(document)
            await session.commit()
            return True
