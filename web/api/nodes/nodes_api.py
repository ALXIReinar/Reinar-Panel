from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.vpn_protocols_schema import (
    NodeCreateSchema,
    NodeUpdateSchema,
)
from web.utils.logger_config import log_event


router = APIRouter(tags=['Nodes'])



@router.post('/create', summary="Создать ноду")
async def create_node(data: NodeCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Проверяем существование протокола
    protocol = await db.protocols.get_protocol(data.proto_id)
    if not protocol:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})
    
    node_id = await db.nodes.create_node(data.proto_id, data.ip, data.title, data.status.value, data.port)
    log_event(f"Создана нода: {data.title} ({data.ip}:{data.port or 'N/A'}) | node_id: {node_id}", request=request)
    return {'success': True, 'node_id': node_id, 'message': 'Нода создана'}


@router.get('/all', summary="Получить все ноды")
async def get_all_nodes(status: str | None = None, proto_id: int | None = None, db: PgSqlDep = None, _: JWTCookieDep = None):
    nodes = await db.nodes.get_all_nodes(status, proto_id)
    return {'nodes': nodes}


@router.get('/by-ip/{ip}', summary="Получить ноды по IP")
async def get_nodes_by_ip(ip: str, db: PgSqlDep, _: JWTCookieDep):
    nodes = await db.nodes.get_nodes_by_ip(ip)
    return {'nodes': nodes}


@router.get('/{node_id}', summary="Получить ноду")
async def get_node(node_id: int, db: PgSqlDep, _: JWTCookieDep):
    node = await db.nodes.get_node(node_id)
    
    if not node:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})
    
    return {'node': node}


@router.put('/update/{node_id}', summary="Обновить ноду")
async def update_node(node_id: int, data: NodeUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_value = data.status.value if data.status else None
    updated = await db.nodes.update_node(node_id, data.proto_id, data.ip, data.port, data.title, status_value)
    
    if not updated:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена или нет изменений'})
    
    log_event(f"Обновлена нода | node_id: {node_id}", request=request)
    return {'success': True, 'message': 'Нода обновлена'}


@router.delete('/{node_id}', summary="Удалить ноду")
async def delete_node(node_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.nodes.delete_node(node_id)
    
    if not deleted:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})
    
    log_event(f"Удалена нода | node_id: {node_id}", request=request, level='WARNING')
    return {'success': True, 'message': 'Нода удалена'}



