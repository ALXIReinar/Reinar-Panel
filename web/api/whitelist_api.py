from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.data.redis_storage import RedisDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.whitelist_schema import WhitelistUpdateSchema, WhitelistAddSchema, WhitelistDeleteSchema
from web.data.redis_storage import CommandWhitelistCache
from web.utils.logger_config import log_event

router = APIRouter(prefix='/private/whitelist', tags=['Whitelist Management'])



@router.get('/all')
async def get_base_whitelist_api(request: Request, db: PgSqlDep, redis: RedisDep, _: JWTCookieDep):
    """Получить все базовые команды whitelist"""
    commands = await CommandWhitelistCache.get_base_whitelist(redis)
    if not commands:
        await CommandWhitelistCache.set_base_whitelist(redis, db)
        commands = await CommandWhitelistCache.get_base_whitelist(redis)

    log_event(f'Выдали команды whitelist | whlist_len: \033[32m{len(commands)}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'commands': commands}


@router.put('/bulk_update')
async def update_base_whitelist(
        body: WhitelistUpdateSchema, request: Request, db: PgSqlDep, redis: RedisDep, _: JWTCookieDep
):
    """
    Bulk update статусов базовых команд whitelist, автоматически инвалидирует кэш Redis
    """
    log_event(f'Bulk update базовых команд | set_active: {len(body.set_as_active)}; set_inactive: {len(body.set_as_inactive)}; admin_id: \033[31m{request.state.admin_id}\033[0m',request=request)

    active_count, inactive_count = await db.whitelist_cmd.bulk_update(body.set_as_active, body.set_as_inactive)

    "Очищаем кэш команд"
    await CommandWhitelistCache.flush_whitelist(redis)
    
    log_event(f'Базовые команды обновлены | active_count: {active_count}; inactive_count: {inactive_count}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': 'Статусы команд обновлены', 'active_count': active_count, 'inactive_count': inactive_count}


@router.post('/bulk_add')
async def add_base_whitelist(body: WhitelistAddSchema, request: Request, db: PgSqlDep, redis: RedisDep, _: JWTCookieDep):
    """
    Bulk add базовых команд в whitelist, автоматически инвалидирует кэш Redis
    """
    log_event(f'Bulk add Whitelist команд | commands: {body.commands}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    
    records = await db.whitelist_cmd.bulk_add(body.commands)

    "Очистка кэша команд"
    await CommandWhitelistCache.flush_whitelist(redis)

    if len(body.commands) != len(records):
        log_event(f'Добавление команд в белый список выполнено частично, uniq constraint | inp_cmds: {body.commands}; db_cmds: {records}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        return JSONResponse(status_code=202, content={'success': True, 'message': 'Вставка выполнена частично. Дубликаты команд проигнорированы', "success_insert_cmds": records})

    log_event(f'Добавлены команды белого списка | wh_cmd_ids: {records}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': f'Команды добавлены!', 'white_cmd_ids': records}


@router.delete('/bulk_delete')
async def delete_base_whitelist(body: WhitelistDeleteSchema, request: Request, db: PgSqlDep, redis: RedisDep, _: JWTCookieDep):
    """
    Bulk delete базовых команд из whitelist, автоматически инвалидирует кэш Redis
    """
    log_event(f'Bulk delete базовых команд | count: {len(body.ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    
    await db.whitelist_cmd.bulk_delete(body.ids)

    await CommandWhitelistCache.flush_whitelist(redis)
    log_event(f'Whlist команды удалены | wh_cmd_ids {body.ids}', request=request)
    return {'success': True, 'message': f'Команды удалены'}
