import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import create_engine, create_session_factory, create_tables
from app.models.batch import Batch, BatchStatus
from app.models.document import Document, DocumentStatus
from app.models.finding import Finding, ReviewStatus
from app.repositories.finding_repository import FindingRepository
from app.services.errors import DomainValidationError, NotFoundError
from app.services.review_service import ReviewService


@pytest.fixture
async def session(tmp_path) -> AsyncSession:
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/review.db")
    engine = create_engine(settings)
    await create_tables(engine)
    factory = create_session_factory(engine)
    async with factory() as db_session:
        yield db_session
        await db_session.commit()
    await engine.dispose()


async def _seed_finding(session: AsyncSession) -> Finding:
    batch = Batch(
        status=BatchStatus.COMPLETED,
        variables=["effective_date"],
        original_filename="contracts.zip",
    )
    session.add(batch)
    await session.flush()
    document = Document(
        batch_id=batch.id,
        filename="lease.txt",
        size_bytes=12,
        status=DocumentStatus.COMPLETED,
        storage_path="/tmp/lease.txt",
    )
    session.add(document)
    await session.flush()
    finding = Finding(
        document_id=document.id,
        variable_name="effective_date",
        value="2024-01-01",
        review_status=ReviewStatus.PENDING,
    )
    session.add(finding)
    await session.flush()
    return finding


@pytest.mark.asyncio
async def test_accept_and_rereview(session: AsyncSession) -> None:
    finding = await _seed_finding(session)
    service = ReviewService(FindingRepository(session))
    accepted = await service.review(finding.id, ReviewStatus.ACCEPTED)
    assert accepted.review_status == ReviewStatus.ACCEPTED
    rejected = await service.review(finding.id, ReviewStatus.REJECTED)
    assert rejected.review_status == ReviewStatus.REJECTED


@pytest.mark.asyncio
async def test_missing_finding(session: AsyncSession) -> None:
    service = ReviewService(FindingRepository(session))
    with pytest.raises(NotFoundError):
        await service.review("missing", ReviewStatus.ACCEPTED)


@pytest.mark.asyncio
async def test_invalid_decision(session: AsyncSession) -> None:
    finding = await _seed_finding(session)
    service = ReviewService(FindingRepository(session))
    with pytest.raises(DomainValidationError):
        await service.review(finding.id, ReviewStatus.PENDING)
