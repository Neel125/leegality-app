from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.finding import Finding


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def get(self, document_id: str) -> Document | None:
        return await self.session.get(Document, document_id)

    async def count_by_status(self, batch_id: str) -> dict[str, int]:
        stmt = (
            select(Document.status, func.count())
            .where(Document.batch_id == batch_id)
            .group_by(Document.status)
        )
        rows = (await self.session.execute(stmt)).all()
        counts = {status.value: 0 for status in DocumentStatus}
        for status, count in rows:
            counts[status] = count
        return counts

    async def list_for_batch(
        self, batch_id: str, offset: int, limit: int
    ) -> tuple[list[tuple[Document, int]], int]:
        total_stmt = select(func.count()).select_from(Document).where(Document.batch_id == batch_id)
        total = int((await self.session.execute(total_stmt)).scalar_one())

        finding_count = (
            select(func.count())
            .select_from(Finding)
            .where(Finding.document_id == Document.id)
            .correlate(Document)
            .scalar_subquery()
        )
        stmt = (
            select(Document, finding_count)
            .where(Document.batch_id == batch_id)
            .order_by(Document.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], int(row[1] or 0)) for row in rows], total

    async def claim_next_queued(self) -> Document | None:
        queued_id = (
            await self.session.execute(
                select(Document.id)
                .where(Document.status == DocumentStatus.QUEUED)
                .order_by(Document.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if queued_id is None:
            return None
        result = await self.session.execute(
            update(Document)
            .where(Document.id == queued_id, Document.status == DocumentStatus.QUEUED)
            .values(status=DocumentStatus.PROCESSING)
        )
        if result.rowcount != 1:
            return None
        return await self.session.get(Document, queued_id)
