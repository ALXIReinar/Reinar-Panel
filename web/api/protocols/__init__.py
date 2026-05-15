from fastapi import APIRouter
from .protocols_api import router as protocols_api_router
from .proto_commands_api import router as proto_commands_router
from .proto_links_templates import tmp_router

protocols_router = APIRouter(prefix='/private')

protocols_router.include_router(protocols_api_router)
protocols_router.include_router(proto_commands_router)
protocols_router.include_router(tmp_router)