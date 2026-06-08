from fastapi import APIRouter

from node_client.config import env
from .node_config_api import router as node_config_router
from .execute_api import router as execute_router
from .proto_core.proto_core_users_api import router as proto_core_users_router

main_router = APIRouter(prefix='/api/v1/server')

main_router.include_router(execute_router)
main_router.include_router(node_config_router)
main_router.include_router(proto_core_users_router)

@main_router.get('/node/ping')
async def health_check():
    return {"status": True, "message": "pong", "service": env.node_name, "version": "0.1"}