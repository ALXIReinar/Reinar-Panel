from fastapi import APIRouter
from .templates_api import router as templates_router

tmp_router = APIRouter(prefix='/templates')

tmp_router.include_router(templates_router)
