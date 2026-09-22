from fastapi import APIRouter

from app.controllers.batch_controller import batch_router
from app.controllers.document_controller import document_router
from app.controllers.finding_controller import finding_router
from app.controllers.health_controller import health_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(batch_router)
api_router.include_router(document_router)
api_router.include_router(finding_router)
api_router.include_router(health_router)
