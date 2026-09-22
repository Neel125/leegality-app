import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.controllers.error_handlers import register_error_handlers
from app.routers import api_router
from app.db import create_engine, create_session_factory, create_tables
from app.extraction.factory import build_extraction_client
from app.workers.document_worker import DocumentProcessingWorker


def _ensure_sqlite_parent(database_url: str) -> None:
    if "sqlite" not in database_url or ":///:" in database_url or ":memory:" in database_url:
        return
    if ":///" not in database_url:
        return
    db_path = Path(database_url.split(":///", 1)[1])
    if db_path.parent.as_posix() not in {"", "."}:
        db_path.parent.mkdir(parents=True, exist_ok=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _ensure_sqlite_parent(settings.database_url)
        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
        await create_tables(engine)
        extractor = build_extraction_client(settings)
        worker = DocumentProcessingWorker(session_factory, extractor, settings)
        task = asyncio.create_task(worker.run())
        try:
            yield
        finally:
            await worker.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await engine.dispose()

    application = FastAPI(
        title="Contract Batch Processor",
        description="Bulk contract extraction with mocked async processing and human review.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.session_factory = session_factory
    register_error_handlers(application)
    application.include_router(api_router)

    frontend = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

    @application.get("/", include_in_schema=False)
    async def review_ui() -> FileResponse:
        return FileResponse(frontend)

    return application


app = create_app()
