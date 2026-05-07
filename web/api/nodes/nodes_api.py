from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.params import Query
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_schema import NodeCreateSchema, NodeUpdateSchema
from web.utils.logger_config import log_event


router = APIRouter(tags=['Physical Nodes (Servers)'])



@router.post('/create', summary="Создать физическую ноду")
async def create_node_api(body: NodeCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    node_id = await db.nodes.create_node(
        body.ip, body.private_ip, body.api_port, body.title, body.status, body.is_active
    )
    if not node_id:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Убедитесь, что публичный и приватный ip не заняты другими нодами'})

    log_event(f"Создана нода: {body.title} | ip: \033[36m{body.ip}\033[0m; private_ip: \033[35m{body.private_ip}\033[0m; node_id: \033[33m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'node_id': node_id, 'message': 'Нода создана'}


@router.get('/all', summary="Получить все физические ноды")
async def get_all_nodes_api(
        status: Annotated[int | None, Query()], is_active: Annotated[bool | None, Query()], db: PgSqlDep, request: Request, _: JWTCookieDep = None
):
    nodes = await db.nodes.get_all_nodes(status, is_active)
    log_event(f'Отдали все ноды | status: \033[33m{status}\033[0m; is_active: \033[32m{is_active}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'nodes': nodes}


@router.get('/{node_id}', summary="Получить физическую ноду")
async def get_node_api(node_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    node = await db.nodes.get_node(node_id)
    if not node:
        log_event(f"Нода не найдена | node_id: \033[34m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})

    log_event(f'Отдали физическую ноду | node_id: \033[32m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'node': node}


@router.put('/update/{node_id}', summary="Обновить физическую ноду")
async def update_node_api(body: NodeUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes.update_node(body.node_id, body.ip, body.private_ip, body.api_port, body.title, body.status, body.is_active)
    log_event(f"Обновлена нода | node_id: \033[33m{body.node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'message': 'Нода обновлена'}


@router.delete('/{node_id}', summary="Удалить физическую ноду")
async def delete_node_api(node_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes.delete_node(node_id)
    log_event(f"Удалена нода | node_id: \033[31m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': 'Нода удалена'}


