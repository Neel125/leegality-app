from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.document import Document
from app.models.finding import Finding


class FindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, finding: Finding) -> Finding:
        self.session.add(finding)
        await self.session.flush()
        return finding

    async def get(self, finding_id: str) -> Finding | None:
        stmt = select(Finding).options(joinedload(Finding.document)).where(Finding.id == finding_id)
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def list_for_document(self, document_id: str) -> list[Finding]:
        stmt = (
            select(Finding)
            .options(joinedload(Finding.document))
            .where(Finding.document_id == document_id)
            .order_by(Finding.variable_name.asc())
        )
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def list_for_batch(
        self,
        batch_id: str,
        review_status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Finding], int]:
        filters = [Document.batch_id == batch_id]
        if review_status is not None:
            filters.append(Finding.review_status == review_status)

        total_stmt = (
            select(func.count())
            .select_from(Finding)
            .join(Document, Document.id == Finding.document_id)
            .where(*filters)
        )
        total = int((await self.session.execute(total_stmt)).scalar_one())

        stmt = (
            select(Finding)
            .join(Document, Document.id == Finding.document_id)
            .options(joinedload(Finding.document))
            .where(*filters)
            .order_by(Document.created_at.asc(), Finding.variable_name.asc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.session.execute(stmt)).unique().scalars().all())
        return items, total
