from fastapi import APIRouter  # noqa: I001
from .protocols_api import router as protocols_api_router
from .proto_commands_api import router as proto_commands_router

protocols_router = APIRouter(prefix='/private')

protocols_router.include_router(protocols_api_router)
protocols_router.include_router(proto_commands_router)
