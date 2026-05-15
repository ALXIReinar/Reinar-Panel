from fastapi import APIRouter
from .templates_api import router as templates_router
from .spec_params import router as spec_params_router

tmp_router = APIRouter(prefix='/templates')

tmp_router.include_router(templates_router)
tmp_router.include_router(spec_params_router)
