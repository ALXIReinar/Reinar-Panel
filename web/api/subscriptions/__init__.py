from fastapi import APIRouter
from .sub_plans_api import router as sub_plans_router

subscriptions_router = APIRouter()
subscriptions_router.include_router(sub_plans_router)

__all__ = ['subscriptions_router']
