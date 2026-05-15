from fastapi import APIRouter

from web.api.auth_panel_api import router as auth_panel_router
from web.api.bg_tasks import bg_router
from web.api.whitelist_api import router as whitelist_router
from web.api.nodes import nodes_router
from web.api.protocols import protocols_router
from web.api.node_commander_api import router as node_commander_router
from web.api.users import users_router
from web.api.subscriptions import subscriptions_router
from web.api.execute_history import router as remote_execute_history_router

main_router = APIRouter(prefix="/api/v1")


main_router.include_router(auth_panel_router)
main_router.include_router(protocols_router)
main_router.include_router(nodes_router)
main_router.include_router(node_commander_router)
main_router.include_router(whitelist_router)
main_router.include_router(remote_execute_history_router)
main_router.include_router(users_router)
main_router.include_router(subscriptions_router)
main_router.include_router(bg_router)


@main_router.get('/healthcheck')
async def healthcheck():
    return {"status": True, "server": "web-panel", "version": '0.1'}