from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.proto_commands_schema import CommandsBulkInsertSchema, CommandsBulkUpdateSchema, CommandsBulkDeleteSchema

from web.utils.logger_config import log_event

router = APIRouter(prefix='/protocol-commands', tags=['Proto Commands'])



@router.get('/by_proto/{proto_id}', summary="Получить команды протокола")
async def get_proto_commands(proto_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    commands = await db.protocol_commands.get_protocol_commands(proto_id)
    log_event(f'Отдали команды для протокола | cmds_len: \033[34m{len(commands)}\033[0m; proto_id: \033[32m{proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'commands': commands}


@router.post('/bulk/insert', summary="Массовая вставка команд")
async def bulk_insert_commands(body: CommandsBulkInsertSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    """Bulk insert commands for proto"""
    "Pydantic модели -> dict"
    commands_data = [cmd.model_dump() for cmd in body.commands]
    status_code, cmd_ids = await db.protocol_commands.insert_commands_bulk(body.proto_id, commands_data)
    if status_code == 404:
        log_event(f"Bulk insert отклонён. Протокол не найден! | proto_id: \033[31m{body.proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Протокол не найден'})


    log_event(f"Bulk insert команд | proto_id: \033[33m{body.proto_id}\033[0m; inserted: \033[32m{cmd_ids}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'cmd_ids': cmd_ids, 'message': f'Вставлено команд: {len(cmd_ids)}'}


@router.put('/bulk/update', summary="Массовое обновление команд")
async def bulk_update_commands(body: CommandsBulkUpdateSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    # Преобразуем Pydantic модели в dict для DAO
    commands_data = [cmd.model_dump() for cmd in body.commands]
    updated_cmds = await db.protocol_commands.update_commands_bulk(commands_data)
    
    log_event(f"Bulk update команд | updated: \033[32m{updated_cmds}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
    return {'success': True, 'updated_count': updated_cmds, 'message': f'Обновлено команд: {updated_cmds}'}


@router.delete('/bulk/delete', summary="Массовое удаление команд")
async def bulk_delete_commands(body: CommandsBulkDeleteSchema, db: PgSqlDep, request: Request, _: JWTCookieDep):
    deleted_count = await db.protocol_commands.delete_commands_bulk(body.cmd_ids)
    
    log_event(f"Bulk delete команд | deleted: \033[31m{deleted_count}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
    return {'success': True, 'deleted_count': deleted_count, 'message': f'Удалено команд: {deleted_count}'}


@router.get('/{cmd_id}', summary="Получить команду")
async def get_cmd(cmd_id: int, db: PgSqlDep, request: Request, _: JWTCookieDep):
    command = await db.protocol_commands.get_command(cmd_id)
    if not command:
        log_event(f'Не нашли команду | cmd_id: \033[31m{cmd_id}\033[0m', request=request)
        return JSONResponse(status_code=404, content={'success': False, 'message': 'Команда не найдена'})

    log_event(f'Отдали команду | cmd_id: \033[32m{cmd_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'command': command}