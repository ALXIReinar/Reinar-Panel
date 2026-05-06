from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.vpn_protocols_schema import ProtoConfigCreateSchema, ProtoConfigUpdateSchema
from web.utils.logger_config import log_event

router = APIRouter(prefix='/configs', tags=['Nodes Configs'])

@router.post('/create', summary="Создать конфигурацию")
async def create_config(data: ProtoConfigCreateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Проверяем существование ноды
    node = await db.nodes.get_node(data.node_id)
    if not node:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Нода не найдена'})

    config_id = await db.proto_configs.create_config(data.node_id, data.path)
    log_event(f"Создана конфигурация для ноды {data.node_id} | config_id: {config_id}", request=request)
    return {'success': True, 'config_id': config_id, 'message': 'Конфигурация создана'}


@router.get('/all', summary="Получить все конфигурации")
async def get_all_configs(db: PgSqlDep, _: JWTCookieDep):
    configs = await db.proto_configs.get_all_configs()
    return {'configs': configs}


@router.get('/configs/protocol/{proto_id}/SOMNITELNO', summary="Получить конфигурации протокола")
async def get_protocol_configs(proto_id: int, db: PgSqlDep, _: JWTCookieDep):
    """
    Не может быть конфига у протокола. Конфиг есть у ноды, под протокол
    """
    configs = await db.proto_configs.get_protocol_configs(proto_id)
    return {'configs': configs}


@router.get('/get_by_node/{node_id}', summary="Получить конфигурацию ноды")
async def get_node_config(node_id: int, db: PgSqlDep, _: JWTCookieDep):
    config = await db.proto_configs.get_node_config(node_id)

    if not config:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})

    return {'config': config}


@router.get('/{config_id}/SUPER-SOMNITELNO', summary="Получить конфигурацию")
async def get_config(config_id: int, db: PgSqlDep, _: JWTCookieDep):
    config = await db.proto_configs.get_config(config_id)

    if not config:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})

    return {'config': config}


@router.put('/update/{config_id}', summary="Обновить путь конфигурации")
async def update_config(config_id: int, data: ProtoConfigUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    updated = await db.proto_configs.update_config_path(config_id, data.path)

    if not updated:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})

    log_event(f"Обновлена конфигурация | config_id: {config_id}", request=request)
    return {'success': True, 'message': 'Конфигурация обновлена'}


@router.delete('/{config_id}', summary="Удалить конфигурацию")
async def delete_config(config_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted = await db.proto_configs.delete_config(config_id)

    if not deleted:
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Конфигурация не найдена'})

    log_event(f"Удалена конфигурация | config_id: {config_id}", request=request, level='WARNING')
    return {'success': True, 'message': 'Конфигурация удалена'}
