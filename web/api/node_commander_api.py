from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from web.config_dir.config import NodeExecAiohttpDep
from web.data.postgres import PgSqlDep
from web.data.redis_storage import RedisDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_commander_schema import ExecCMDNodeSchema
from web.utils.anything import NodeUris, Constants
from web.data.redis_storage import CommandWhitelistCache
from web.utils.logger_config import log_event

router = APIRouter(prefix='/cmd_center', tags=['Command Center Admin2Node'])




@router.post('/remote_execute')
async def execute_cmd_on_node(
    body: ExecCMDNodeSchema, request: Request, db: PgSqlDep, _: JWTCookieDep, 
    aio_http: NodeExecAiohttpDep, redis: RedisDep
):
    """Выполнение команды на удалённой ноде с валидацией"""
    log_event(f'Исполняем команду на ноде | private_ip-port: {body.private_ip}-{body.api_port}; cmd: \033[36m{body.cmd}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Обработка"
    splitted_cmd = body.cmd.split()
    base_cmd = splitted_cmd[0] if splitted_cmd[0] not in Constants.excluded_commands_words else splitted_cmd[1]

    "Проверка по белому списку"
    if not await CommandWhitelistCache.is_whitelisted(base_cmd, redis, db):
        log_event(f'Команда не прошла по Whitelist | cmd: \033[36m{body.cmd}\033[0m; base_cmd: \033[37m{base_cmd}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return JSONResponse(status_code=400, content={'success': False, 'message': f'Команда {body.cmd} не находится в белом списке'})

    "Отправка команды на ноду"
    url = f'http://{body.private_ip}:{body.api_port}{NodeUris.exec_cmd}'
    try:
        async with aio_http.post(url, json={'command': body.cmd}) as resp:
            status_code = resp.status
            resp_data = await resp.json()
    except Exception as e:
        log_event(f'Ошибка при отправке команды на ноду: {str(e)}', request=request, level='ERROR')
        return JSONResponse(status_code=500, content=f"Ошибка связи с нодой: {str(e)}")
    
    level = 'ERROR' if status_code >= 400 else 'INFO'
    log_event(f'Результат команды на ноде \033[33m{resp_data["success"]}\033[0m; status_code: \033[37m{status_code}\033[0m; stdout: {resp_data["stdout"][:30]}; stderr: {resp_data["stderr"][:30]}', request=request,level=level)
    return {'success': resp_data['success'], 'stdout': resp_data['stdout'], 'stderr': resp_data['stderr']}
