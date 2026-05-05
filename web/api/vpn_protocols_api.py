from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.vpn_protocols_schema import (
    ProtocolCreateSchema,
    ProtocolCommandCreateSchema,
    ProtocolCommandUpdateSchema,
    NodeCreateSchema,
    NodeUpdateSchema,
    ProtoConfigCreateSchema,
    ProtoConfigUpdateSchema
)
from web.utils.logger_config import log_event


router = APIRouter(tags=['VPN Protocols🔐'], prefix='/private/vpn')


# ============= Protocols =============

@router.post('/protocols', summary="Создать протокол")
async def create_protocol(data: ProtocolCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    proto_id = await db.protocols.create_protocol(data.name)
    log_event(f"Создан протокол: {data.name} | proto_id: {proto_id}", request=request)
    return {'success': True, 'proto_id': proto_id, 'message': 'Протокол создан'}


@router.get('/protocols', summary="Получить все протоколы")
async def get_all_protocols(db: PgSqlDep, _: JWTCookieDep):
    protocols = await db.protocols.get_all_protocols()
    return {'protocols': protocols}


@router.get('/protocols/{proto_id}', summary="Получить протокол")
async def get_protocol(proto_id: int, db: PgSqlDep, _: JWTCookieDep):
    protocol = await db.protocols.get_protocol(proto_id)
    
    if not protocol:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})
    
    return {'protocol': protocol}


@router.delete('/protocols/{proto_id}', summary="Удалить протокол")
async def delete_protocol(proto_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.protocols.delete_protocol(proto_id)
    
    if not deleted:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})
    
    log_event(f"Удалён протокол | proto_id: {proto_id}", request=request, level='WARNING')
    return {'success': True, 'message': 'Протокол удалён'}


# ============= Protocol Commands =============

@router.post('/protocols/{proto_id}/commands', summary="Создать команду для протокола")
async def create_command(proto_id: int, data: ProtocolCommandCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Проверяем существование протокола
    protocol = await db.protocols.get_protocol(proto_id)
    if not protocol:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})
    
    cmd_id = await db.protocol_commands.create_command(proto_id, data.cmd_title, data.command)
    log_event(f"Создана команда '{data.cmd_title}' для протокола {proto_id} | cmd_id: {cmd_id}", request=request)
    return {'success': True, 'cmd_id': cmd_id, 'message': 'Команда создана'}


@router.get('/protocols/{proto_id}/commands', summary="Получить команды протокола")
async def get_protocol_commands(proto_id: int, db: PgSqlDep, _: JWTCookieDep):
    commands = await db.protocol_commands.get_protocol_commands(proto_id)
    return {'commands': commands}


@router.get('/commands/{cmd_id}', summary="Получить команду")
async def get_command(cmd_id: int, db: PgSqlDep, _: JWTCookieDep):
    command = await db.protocol_commands.get_command(cmd_id)
    
    if not command:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Команда не найдена'})
    
    return {'command': command}


@router.put('/commands/{cmd_id}', summary="Обновить команду")
async def update_command(cmd_id: int, data: ProtocolCommandUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    updated = await db.protocol_commands.update_command(cmd_id, data.cmd_title, data.command)
    
    if not updated:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Команда не найдена или нет изменений'})
    
    log_event(f"Обновлена команда | cmd_id: {cmd_id}", request=request)
    return {'success': True, 'message': 'Команда обновлена'}


@router.delete('/commands/{cmd_id}', summary="Удалить команду")
async def delete_command(cmd_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.protocol_commands.delete_command(cmd_id)
    
    if not deleted:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Команда не найдена'})
    
    log_event(f"Удалена команда | cmd_id: {cmd_id}", request=request, level='WARNING')
    return {'success': True, 'message': 'Команда удалена'}


# ============= Nodes =============

@router.post('/nodes', summary="Создать ноду")
async def create_node(data: NodeCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Проверяем существование протокола
    protocol = await db.protocols.get_protocol(data.proto_id)
    if not protocol:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})
    
    node_id = await db.nodes.create_node(data.proto_id, data.ip, data.title, data.status.value, data.port)
    log_event(f"Создана нода: {data.title} ({data.ip}:{data.port or 'N/A'}) | node_id: {node_id}", request=request)
    return {'success': True, 'node_id': node_id, 'message': 'Нода создана'}


@router.get('/nodes', summary="Получить все ноды")
async def get_all_nodes(status: str | None = None, proto_id: int | None = None, db: PgSqlDep = None, _: JWTCookieDep = None):
    nodes = await db.nodes.get_all_nodes(status, proto_id)
    return {'nodes': nodes}


@router.get('/nodes/by-ip/{ip}', summary="Получить ноды по IP")
async def get_nodes_by_ip(ip: str, db: PgSqlDep, _: JWTCookieDep):
    nodes = await db.nodes.get_nodes_by_ip(ip)
    return {'nodes': nodes}


@router.get('/nodes/{node_id}', summary="Получить ноду")
async def get_node(node_id: int, db: PgSqlDep, _: JWTCookieDep):
    node = await db.nodes.get_node(node_id)
    
    if not node:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})
    
    return {'node': node}


@router.put('/nodes/{node_id}', summary="Обновить ноду")
async def update_node(node_id: int, data: NodeUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_value = data.status.value if data.status else None
    updated = await db.nodes.update_node(node_id, data.proto_id, data.ip, data.port, data.title, status_value)
    
    if not updated:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена или нет изменений'})
    
    log_event(f"Обновлена нода | node_id: {node_id}", request=request)
    return {'success': True, 'message': 'Нода обновлена'}


@router.delete('/nodes/{node_id}', summary="Удалить ноду")
async def delete_node(node_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.nodes.delete_node(node_id)
    
    if not deleted:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})
    
    log_event(f"Удалена нода | node_id: {node_id}", request=request, level='WARNING')
    return {'success': True, 'message': 'Нода удалена'}


# ============= Protocol Configs =============

@router.post('/configs', summary="Создать конфигурацию")
async def create_config(data: ProtoConfigCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Проверяем существование ноды
    node = await db.nodes.get_node(data.node_id)
    if not node:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})
    
    config_id = await db.proto_configs.create_config(data.node_id, data.path)
    log_event(f"Создана конфигурация для ноды {data.node_id} | config_id: {config_id}", request=request)
    return {'success': True, 'config_id': config_id, 'message': 'Конфигурация создана'}


@router.get('/configs', summary="Получить все конфигурации")
async def get_all_configs(db: PgSqlDep, _: JWTCookieDep):
    configs = await db.proto_configs.get_all_configs()
    return {'configs': configs}


@router.get('/configs/protocol/{proto_id}', summary="Получить конфигурации протокола")
async def get_protocol_configs(proto_id: int, db: PgSqlDep, _: JWTCookieDep):
    configs = await db.proto_configs.get_protocol_configs(proto_id)
    return {'configs': configs}


@router.get('/configs/node/{node_id}', summary="Получить конфигурацию ноды")
async def get_node_config(node_id: int, db: PgSqlDep, _: JWTCookieDep):
    config = await db.proto_configs.get_node_config(node_id)
    
    if not config:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})
    
    return {'config': config}


@router.get('/configs/{config_id}', summary="Получить конфигурацию")
async def get_config(config_id: int, db: PgSqlDep, _: JWTCookieDep):
    config = await db.proto_configs.get_config(config_id)
    
    if not config:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})
    
    return {'config': config}


@router.put('/configs/{config_id}', summary="Обновить путь конфигурации")
async def update_config(config_id: int, data: ProtoConfigUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    updated = await db.proto_configs.update_config_path(config_id, data.path)
    
    if not updated:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})
    
    log_event(f"Обновлена конфигурация | config_id: {config_id}", request=request)
    return {'success': True, 'message': 'Конфигурация обновлена'}


@router.delete('/configs/{config_id}', summary="Удалить конфигурацию")
async def delete_config(config_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.proto_configs.delete_config(config_id)
    
    if not deleted:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})
    
    log_event(f"Удалена конфигурация | config_id: {config_id}", request=request, level='WARNING')
    return {'success': True, 'message': 'Конфигурация удалена'}
