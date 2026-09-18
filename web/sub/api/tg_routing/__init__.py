from fastapi import APIRouter  # noqa: I001
from .endpoints import router

tg_router = APIRouter(prefix='/api/v1/tg-bot')

tg_router.include_router(router)
