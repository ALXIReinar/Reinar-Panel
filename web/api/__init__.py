from fastapi import APIRouter

from web.api.auth_panel_api import router as auth_panel_router
from web.api.vpn_protocols_api import router as vpn_protocols_router

main_router = APIRouter(prefix="/api/v1")

main_router.include_router(auth_panel_router)
main_router.include_router(vpn_protocols_router)

@main_router.get('/healthcheck')
async def healthcheck():
    return {"status": True, "server": "api-server", "version": '0.1'}