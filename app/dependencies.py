from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.repositories.batch_repository import BatchRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.finding_repository import FindingRepository
from app.services.batch_service import BatchService
from app.services.review_service import ReviewService
from app.services.zip_archive_service import ZipArchiveService
from app.storage.local import LocalStorageAdapter


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_batch_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BatchService:
    settings: Settings = request.app.state.settings
    return BatchService(
        settings=settings,
        batches=BatchRepository(session),
        documents=DocumentRepository(session),
        findings=FindingRepository(session),
        zip_service=ZipArchiveService(settings),
        storage=LocalStorageAdapter(settings.storage_dir),
    )


def get_review_service(
    session: AsyncSession = Depends(get_session),
) -> ReviewService:
    return ReviewService(findings=FindingRepository(session))
