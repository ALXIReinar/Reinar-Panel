from fastapi import APIRouter
from starlette.requests import Request

from web.config_dir.config import NodeExecAiohttpDep
from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_commander_schema import ExecCMDNodeSchema, RemoteExecBaseSchema
from web.utils.anything import NodeUris
from web.utils.logger_config import log_event

router = APIRouter(prefix='/cmd_center', tags=['Command Center Admin2Node'])


@router.post('/remote_execute')
async def execute_cmd_on_node(body: ExecCMDNodeSchema, request: Request, db: PgSqlDep, _: JWTCookieDep, aio_http: NodeExecAiohttpDep):
    """
    Добавить историю команд после успешной рабочей реализации
    """
    log_event(f'Исполняем команду на ноде | private_ip-port: {body.private_ip}-{body.api_port}; cmd: \033[36m{body.cmd}\033[0m;admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    url = f'http://{body.private_ip}:{body.api_port}{NodeUris.exec_cmd}'
    async with aio_http.post(url, json={'command': body.cmd}) as resp:
        status_code = resp.status
        resp = await resp.json()


    level = 'ERROR' if status_code >= 400 else 'INFO'
    log_event(f'Результат команды на ноде \033[33m{resp['success']}\033[0m; status_code: \033[37m{status_code}\033[0m; stdout: {resp['stdout'][:30]}; stderr: {resp['stderr'][:30]}', request=request, level=level)
    return {'success': resp['success'], 'stdout': resp['stdout'], 'stderr': resp['stderr']}
