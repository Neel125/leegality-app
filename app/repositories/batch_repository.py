from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batch import Batch
from app.models.document import Document
from app.models.finding import Finding, ReviewStatus


class BatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, batch: Batch) -> Batch:
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get(self, batch_id: str) -> Batch | None:
        return await self.session.get(Batch, batch_id)

    async def review_counts(self, batch_id: str) -> dict[str, int]:
        stmt = (
            select(Finding.review_status, func.count())
            .join(Document, Document.id == Finding.document_id)
            .where(Document.batch_id == batch_id)
            .group_by(Finding.review_status)
        )
        rows = (await self.session.execute(stmt)).all()
        counts = {status.value: 0 for status in ReviewStatus}
        for status, count in rows:
            counts[status] = count
        return counts
