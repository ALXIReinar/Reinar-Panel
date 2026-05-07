from fastapi import APIRouter
from .nodes_api import router as phys_nodes_router
from .nodes_protocols import router as virtual_nodes_router

nodes_router = APIRouter(prefix='/private/nodes')

nodes_router.include_router(phys_nodes_router)
nodes_router.include_router(virtual_nodes_router)
