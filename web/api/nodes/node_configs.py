from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_configs_schema import ProtoConfigCreateSchema, ProtoConfigUpdateSchema, BaseProtoConfigSchema
from web.utils.logger_config import log_event

router = APIRouter(prefix='/configs', tags=['Nodes Configs'])


@router.post('/create', summary="Создать конфигурацию")
async def create_config(body: ProtoConfigCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    status_code, config_id = await db.proto_configs.create_config(body.node_id, body.path)

    "Не найдена нода или протокол"
    if status_code == 404:
        log_event(f'Протокол или Нода не найдены | node_id: \033[33m{body.node_id}\033[0m; proto_id: \033[31m{body.proto_id}\033[31m; admin_id: \033[31m{request.state.admin_id}\033[31m', request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол ли Нода не найдены'})

    "Конфиг не создан, т.к. уже существует"
    if not config_id:
        log_event(f'Нода с таким протоколом уже существует | node_id: \033[33m{body.node_id}\033[0m; proto_id: \033[31m{body.proto_id}\033[31m; admin_id: \033[31m{request.state.admin_id}\033[31m', request=request, level='WARNING')
        return JSONResponse(
            status_code=409, content={'success': False, 'message': 'Нода с таким протоколом уже существует', 'tip': "Если хотите поднять ядро на другом транспорте, создайте новый протокол с названием \"протокол-транспорт\""}
        )

    log_event(f"Создана конфигурация для ноды | config_id: \033[36m{config_id}\033[0m; node_id: \033[33m{body.node_id}\033[0m; proto_id: \033[31m{body.proto_id}\033[31m; admin_id: \033[31m{request.state.admin_id}\033[31m", request=request)
    return {'success': True, 'config_id': config_id, 'message': 'Конфигурация создана'}


@router.get('/all', summary="Получить все конфигурации")
async def get_all_configs(request: Request, db: PgSqlDep, _: JWTCookieDep):
    configs = await db.proto_configs.get_all_configs()
    log_event(f"Отдали все конфиги | len_configs: \033[34m{len(configs)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[31m", request=request)
    return {'configs': configs}


@router.get('/all/by_proto/{proto_id}', summary="Получить конфигурации протокола")
async def get_protocol_configs(proto_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    configs = await db.proto_configs.get_protocol_configs(proto_id)
    log_event(f'Отдали конфиги по протоколу | proto_id: \033[33m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[33m', request=request)
    return {'configs': configs}


@router.get('/get_by_node/{node_id}', summary="Получить конфигурацию ноды")
async def get_node_config_api(body: BaseProtoConfigSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    config = await db.proto_configs.get_node_config(body.node_id, body.proto_id)

    if not config:
        log_event(f'Не нашли конфигурацию ноды-протокола | node_id: \033[33m{body.node_id}\033[0m; proto_id: \033[31m{body.proto_id}\033[31m; admin_id: \033[31m{request.state.admin_id}\033[31m', request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})

    log_event(f'Отдали конфигурацию ноды-протокола | node_id: \033[32m{body.node_id}\033[0m; proto_id: \033[34m{body.proto_id}\033[31m; admin_id: \033[31m{request.state.admin_id}\033[31m', request=request)
    return {'config': config}


@router.get('/{config_id}', summary="Получить конфигурацию")
async def get_config(config_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    config = await db.proto_configs.get_config(config_id)

    if not config:
        log_event(f"Не нашли конфиг | config_id: \033[31m{config_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[31m", request=request)
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})

    log_event(f'Отдали конфиг | config_id: \033[31m{config_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[31m', request=request)
    return {'config': config}


@router.put('/update/{config_id}', summary="Обновить путь конфигурации")
async def update_config(config_id: int, data: ProtoConfigUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.proto_configs.update_config_path(config_id, data.path)
    log_event(f"Обновлена конфигурация | config_id: \033[35m{config_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[31m", request=request)
    return {'success': True, 'message': 'Конфигурация обновлена'}


@router.delete('/{config_id}', summary="Удалить конфигурацию")
async def delete_config(config_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    await db.proto_configs.delete_config(config_id)
    log_event(f"Удалена конфигурация | config_id: \033[31m{config_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[31m", request=request, level='WARNING')
    return {'success': True, 'message': 'Конфигурация удалена'}
