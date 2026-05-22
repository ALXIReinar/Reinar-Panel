from fastapi import APIRouter
from .sub_api import router as sub_router

main_router = APIRouter()

main_router.include_router(sub_router)