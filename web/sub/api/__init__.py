from fastapi import APIRouter
from .sub_api import router as sub_router
from .robo_payment.payment_api import router as robo_payment_router

main_router = APIRouter()

main_router.include_router(sub_router)
main_router.include_router(robo_payment_router)
