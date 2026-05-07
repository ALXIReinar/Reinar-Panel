from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.nodes_protocols_schema import NodeProtocolCreateSchema, NodeProtocolUpdateSchema
from web.utils.logger_config import log_event



router = APIRouter(tags=['Virtual Nodes-Protocols Variations'])

@router.post('/{node_id}/protocols', summary="Добавить протокол на ноду")
async def add_protocol_to_node_api(node_id: int, body: NodeProtocolCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    np_id = await db.nodes_protocols.create_node_protocol(body.node_id, body.proto_id, body.config_path)
    if not np_id:
        log_event(f'Не удалось добавить протокол. Нода не найдена | node_id: \033[31m{node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})

    log_event(f"Добавлен протокол на ноду | node_id: \033[33m{node_id}\033[0m; proto_id: \033[32m{body.proto_id}\033[0m; np_id: \033[34m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'node_protocol_id': np_id, 'message': 'Протокол добавлен на ноду'}


@router.get('/{node_id}/protocols', summary="Получить все протоколы на ноде")
async def get_node_protocols_api(node_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    protocols = await db.nodes_protocols.get_node_protocols(node_id)
    log_event(f'Отдали протоколы ноды | node_id: \033[33m{node_id}\033[0m; count: \033[32m{len(protocols)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'protocols': protocols}


@router.get('/protocols/{np_id}', summary="Получить виртуальную ноду")
async def get_node_protocol_api(np_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    node_protocol = await db.nodes_protocols.get_node_protocol(np_id)
    if not node_protocol:
        log_event(f"Виртуальная нода не найдена | np_id: \033[34m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Виртуальная нода не найдена'})

    log_event(f'Отдали Виртуальную ноду-протокол | node_proto_id: \033[32m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'node_protocol': node_protocol}


@router.put('/protocols/{np_id}', summary="Обновить виртуальную ноду")
async def update_node_protocol_api(np_id: int, data: NodeProtocolUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes_protocols.update_node_protocol(np_id, data.config_path)
    log_event(f"Обновлена виртуальная нода | np_id: \033[33m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'message': 'Виртуальная нода обновлена'}


@router.delete('/protocols/{np_id}', summary="Удалить протокол с ноды")
async def delete_node_protocol_api(np_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes_protocols.delete_node_protocol(np_id)
    log_event(f"Удалён протокол с ноды | np_id: \033[31m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': 'Протокол удалён с ноды'}