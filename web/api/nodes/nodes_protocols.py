from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.nodes_protocols_schema import NodeProtocolCreateSchema, UpdateNodeProtoSchema, GetNodeProtoSchema
from web.utils.logger_config import log_event



router = APIRouter(tags=['Virtual Nodes-Protocols Variations'])

@router.post('/protocols/create', summary="Добавить протокол на ноду")
async def add_protocol_to_node_api(body: NodeProtocolCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    np_id, msg = await db.nodes_protocols.create_node_protocol(body.node_id, body.proto_id, body.title, body.sub_node_address)

    "404, не найдена нода/протокол"
    if not np_id:
        log_event(f'Не удалось добавить протокол. \033[34m{msg}\033[0m | node_id: \033[31m{body.node_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': msg})

    log_event(f"Добавлен протокол на ноду | node_id: \033[33m{body.node_id}\033[0m; proto_id: \033[32m{body.proto_id}\033[0m; np_id: \033[34m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'node_protocol_id': np_id, 'message': msg}


@router.get('/protocols/by_node', summary="Получить все протоколы на ноде")
async def get_node_protocols_api(q_params: Annotated[GetNodeProtoSchema, Query()], request: Request, db: PgSqlDep, _: JWTCookieDep):
    protocols = await db.nodes_protocols.get_node_protocols(q_params.node_id, q_params.limit, q_params.offset)
    log_event(f'Отдали протоколы ноды | node_id: \033[33m{q_params.node_id}\033[0m; count: \033[32m{len(protocols)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'protocols': protocols}


@router.get('/protocols/{np_id}', summary="Получить виртуальную ноду")
async def get_node_protocol_api(np_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    node_protocol = await db.nodes_protocols.get_node_protocol(np_id)
    if not node_protocol:
        log_event(f"Виртуальная нода не найдена | np_id: \033[34m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Виртуальная нода не найдена'})

    log_event(f'Отдали Виртуальную ноду-протокол | node_proto_id: \033[32m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'node_protocol': node_protocol}


@router.put('/protocols/update', summary="Обновить виртуальную ноду")
async def update_node_protocol_api(body: UpdateNodeProtoSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    """
    Позволяет изменять все свойства виртуальной ноды (инстанса протокола на сервере)

    1. На фронте при вызове этого эндпоинта фиксировать, передаются ли metrics_port или proto_port.
    Если передаются, то предлагать изменить конфиг (если да, вызов эндпоинта чтения конфиг-файла)

    2. Также использовать этот эндпоинт при создании "Контроля уникальности портов":
    Достаточно просто вносить поля с портами и vnode ID(node_proto_id)

    3. Подумать над тем, чтобы ставить user_visible = False автоматически. Чтобы активировать ноду,
    необходимо какой-то тест прогнать. Можно политику безопасности предложить, удобно для провайдеров
    """
    log_event(f"Обновление виртуальной ноды | node_proto_id: \033[35m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    
    status_code, message = await db.nodes_protocols.update_node_protocol(
        np_id=body.node_proto_id,
        config_path=body.config_path,
        title=body.title,
        metrics_port=body.metrics_port,
        proto_port=body.proto_port,
        sub_node_address=body.sub_node_address,
        user_visible=body.user_visible,
    )

    "Конфликт портов на сервере"
    if status_code == 409:
        log_event(f"Конфликт портов при обновлении | node_proto_id: \033[33m{body.node_proto_id}\033[0m; proto_port: \033[35m{body.proto_port}\033[0m; metrics_port: \033[32m{body.metrics_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={'success': False, 'message': message})

    "Нода не найдена"
    if status_code == 404:
        log_event(f"Виртуальная нода не найдена | node_proto_id: \033[31m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': message})

    log_event(f"Виртуальная нода обновлена | node_proto_id: \033[32m{body.node_proto_id}\033[0m; node_proto_body: \033[36m{repr(body)}\033[0m;admin_id: \033[32m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'message': message}


@router.delete('/protocols/{np_id}', summary="Удалить протокол с ноды")
async def delete_node_protocol_api(np_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.nodes_protocols.delete_node_protocol(np_id)
    log_event(f"Удалён протокол с ноды | np_id: \033[31m{np_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'message': 'Виртуальная нода удалена'}