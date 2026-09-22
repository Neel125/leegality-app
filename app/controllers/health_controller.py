from fastapi import APIRouter
from fastapi_utils.cbv import cbv

health_router = APIRouter(prefix="/health", tags=["health"])

@cbv(health_router)
class HealthController():

    @health_router.get("", response_model=dict[str, str])
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

    async def health(self) -> dict[str, str]:
        return {"status": "ok"}
