from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.params import Query
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_schema import NodeCreateSchema, NodeUpdateSchema, NodeIPSchema
from web.utils.logger_config import log_event


router = APIRouter(tags=['Nodes'])



@router.post('/create', summary="Создать ноду")
async def create_node_api(body: NodeCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Проверяем существование протокола
    status_code, node_id = await db.nodes.create_node(body.proto_id, body.ip, body.title, body.status)
    if status_code == 404:
        log_event(f'Не удалось создать ноду. Нет протокола | proto_id: \033[31m{body.proto_id}\033[0m; node_ip: \033[32m{body.ip}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})

    log_event(f"Создана нода: {body.title} | ip \033[36m{body.ip}\033[0m; node_id: \033[33m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'node_id': node_id, 'message': 'Нода создана'}


@router.get('/all', summary="Получить все ноды")
async def get_all_nodes_api(status: Annotated[int | None, Query()], proto_id: Annotated[int | None, Query()], request: Request, db: PgSqlDep, _: JWTCookieDep):
    nodes = await db.nodes.get_all_nodes(status, proto_id)
    log_event(f'Отдали все ноды | status: \033[33m{status}\033[0m; proto_id: \033[32m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'nodes': nodes}


@router.post('/by-ip/{ip}', summary="Получить ноды по IP")
async def get_nodes_by_ip_api(body: NodeIPSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    nodes = await db.nodes.get_nodes_by_ip(body.ip)
    log_event(f"Отдали информацию о ноде по ip | ip: \033[33m{body.ip}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'nodes': nodes}


@router.get('/{node_id}', summary="Получить ноду")
async def get_node_api(node_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    node = await db.nodes.get_node(node_id)
    if not node:
        log_event(f"Нода не найдена | node_id: \033[34m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})
    
    return {'node': node}


@router.put('/update/{node_id}', summary="Обновить ноду")
async def update_node_api(node_id: int, data: NodeUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes.update_node(node_id, data.proto_id, data.ip, data.title, data.status)
    log_event(f"Обновлена нода | node_id: \033[33m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'message': 'Нода обновлена'}


@router.delete('/{node_id}', summary="Удалить ноду")
async def delete_node_api(node_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes.delete_node(node_id)
    log_event(f"Удалена нода | node_id: \033[31m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': 'Нода удалена'}



