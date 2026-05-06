from fastapi import APIRouter
from .nodes_api import router as nodes_api_router
from .node_configs import router as config_nodes_router

nodes_router = APIRouter(prefix='/private/nodes')

nodes_router.include_router(nodes_api_router)
nodes_router.include_router(config_nodes_router)
