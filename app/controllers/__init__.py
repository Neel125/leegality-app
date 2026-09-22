from fastapi import FastAPI

from app.controllers.batch_controller import BatchController
from app.controllers.document_controller import DocumentController
from app.controllers.error_handlers import register_error_handlers
from app.controllers.finding_controller import FindingController
from app.controllers.health_controller import HealthController

__all__ = [
    "BatchController",
    "DocumentController",
    "FindingController",
    "HealthController",
    "register_controllers",
    "register_error_handlers",
]


def register_controllers(app: FastAPI) -> None:
    app.include_router(HealthController().router)
    app.include_router(BatchController().router)
    app.include_router(DocumentController().router)
    app.include_router(FindingController().router)
