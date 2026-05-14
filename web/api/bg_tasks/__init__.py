from fastapi import APIRouter

from .metrics_collector.metrics_collector_api import router as traffic_updater_router
from .crons import router as crons_router

bg_router = APIRouter(prefix='/server')

bg_router.include_router(traffic_updater_router)
bg_router.include_router(crons_router)
