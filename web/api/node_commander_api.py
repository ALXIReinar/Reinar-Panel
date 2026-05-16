from typing import Annotated

from aiohttp import ClientResponseError
from fastapi import APIRouter, HTTPException
from fastapi.params import Query
from starlette.requests import Request

from web.api.protocols.proto_links_templates.handlers import generate_link_from_json
from web.config_dir.config import NodeExecAiohttpDep
from web.data.postgres import PgSqlDep
from web.data.redis_storage import RedisDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_commander_schema import ExecCMDNodeSchema, ReadConfigSchema, WriteConfigSchema
from web.utils.anything import NodeUris, Constants, ExecHistoryStatuses
from web.data.redis_storage import CommandWhitelistCache
from web.utils.logger_config import log_event

router = APIRouter(prefix='/cmd_center', tags=['Command Center Admin2Node'])



@router.post('/remote_execute')
async def execute_cmd_on_node(
    body: ExecCMDNodeSchema, request: Request, db: PgSqlDep, _: JWTCookieDep, aio_http: NodeExecAiohttpDep, redis: RedisDep
):
    """Выполнение команды на удалённой ноде с валидацией"""
    log_event(f'Исполняем команду на ноде | node_proto_id: \033[32m{body.node_proto_id}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; cmd: \033[36m{body.cmd}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Обработка"
    splitted_cmd = body.cmd.split()
    base_cmd = splitted_cmd[0] if splitted_cmd[0] not in Constants.excluded_commands_words else splitted_cmd[1]

    "Проверка по белому списку"
    if not await CommandWhitelistCache.is_whitelisted(base_cmd, redis, db):
        log_event(f'Команда не прошла по Whitelist | node_proto_id: \033[32m{body.node_proto_id}\033[0m; cmd: \033[36m{body.cmd}\033[0m; base_cmd: \033[37m{base_cmd}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        raise HTTPException(status_code=400, detail={'success': False, 'message': f'Команда {body.cmd} не находится в белом списке'})

    "Фиксиурем запрос на удалённое исполнение команды"
    action_id = await db.remote_command_history.save_action(body.node_proto_id, body.private_ip, body.api_port, body.cmd)

    "Отправка команды на ноду"
    url = f'http://{body.private_ip}:{body.api_port}{NodeUris.exec_cmd}'
    try:
        async with aio_http.post(url, json={'command': body.cmd}) as resp:
            status_code = resp.status
            resp_data = await resp.json()
        await db.remote_command_history.update_action(
            action_id=action_id, status=ExecHistoryStatuses.success, stdout=resp_data['stdout'], stderr=resp_data['stderr'],
            exit_code=resp_data['exit_code'], status_code=200, node_success=resp_data['success']
        )
        log_event(f'Результат команды на ноде | node_proto_id: \033[32m{body.node_proto_id}\033[0m; cmd_success: \033[33m{resp_data["success"]}\033[0m; status_code: \033[37m{status_code}\033[0m; stdout: {resp_data["stdout"][:30]}; stderr: {resp_data["stderr"][:30]}', request=request)
        return {'success': True, 'stdout': resp_data['stdout'], 'stderr': resp_data['stderr']}

    except ClientResponseError as e:
        await db.remote_command_history.update_action(
            action_id=action_id, status=ExecHistoryStatuses.failed_on_node, status_code=e.status, exception_text=str(e)
        )
        log_event(f'Нода ответила, что-то пошло не так | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m; node_id: \033[31m{body.node_proto_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message':'Ошибка исполнения на ноде'})

    except Exception as e:
        await db.remote_command_history.update_action(
            action_id=action_id, status=ExecHistoryStatuses.failed_on_admin, status_code=500, exception_text=str(e)
        )
        log_event(f'Ошибка на админке | error: {str(e)}; node_proto_id: \033[32m{body.node_proto_id}\033[0m; private_ip: \033[31m{body.private_ip}\033[0m; api_port: \033[33m{body.api_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=500, detail=f"Ошибка исполнения на админке")



@router.get('/config_file/read')
async def config_file_read(
        q_params: Annotated[ReadConfigSchema, Query()], request: Request, db: PgSqlDep, aio_http: NodeExecAiohttpDep, _: JWTCookieDep
):
    log_event(f'Пробуем считать конфиг-файл с ноды | node_proto_id: \033[32m{q_params.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    node_info = await db.nodes_protocols.get_node_for_file_edit(request.state.node_proto_id)
    
    "Не указан путь к файлу"
    if node_info['config_path'] is None:
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Путь к конфиг-файлу протокола не указан!'})
    
    "Запрашиваем файл с ноды"
    try:
        url = f'http://{node_info['private_ip']}:{node_info['api_port']}{NodeUris.get_config_file}'
        async with aio_http.get(url, params={'file_path': node_info['config_path']}) as resp:
            resp.raise_for_status()
            resp_data = await resp.json()

        log_event(f'Нода прислала конфиг-файл | node_proto_id: \033[32m{q_params.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return {'success': True, 'file_content': resp_data['stdout'], 'message': 'Получен конфиг-файл от ноды'}

    except ClientResponseError as e:
        log_event(f'Нода ответила, что-то пошло не так | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m; node_proto_id: \033[31m{q_params.node_proto_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Ошибка исполнения на ноде'})

    except Exception as e:
        log_event(f'Ошибка исполнения на админке, не удалось прочесть файл | error: \033[31m{e}\033[0m; node_proto_id: \033[33m{q_params.node_proto_id}\033[0m', request=request, level='CRITICAL')
        raise HTTPException(status_code=500, detail="Ошибка исполнения на админке")



@router.put('/config_file/write')
async def config_file_write(body: WriteConfigSchema, request: Request, db: PgSqlDep, aio_http: NodeExecAiohttpDep, _: JWTCookieDep):
    log_event(f'Пробуем записать конфиг-файл с ноды | node_proto_id: \033[32m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Запрашиваем файл с ноды"
    try:
        url = f'http://{body.private_ip}:{body.api_port}{NodeUris.write_config_file}'
        async with aio_http.put(url, json={'file_path': body.file_path, 'file_content': body.file_content}) as resp:
            resp.raise_for_status()

        "1. Вытаскиваем ссылку-шаблон, зависимости и описание из БД"
        config_link_tmp, spec_params, node_ip_or_domain, node_title = await db.nodes_protocols.get_proto_tmp_w_spec_params(body.node_proto_id)
        sub_ready_link = generate_link_from_json(config_link_tmp, body.file_content, spec_params, node_ip_or_domain, node_title)

        "2. Генерируем конфиг-ссылку для подписок"
        await db.nodes_protocols.update_config_link(body.node_proto_id, sub_ready_link)
        log_event(f'Конфиг-ссылка для подписок сгенерирована из конфиг-файла | node_proto_id: \033[32m{body.node_proto_id}\033[0m', request=request)


        log_event(f'Нода записала конфиг-файл | node_proto_id: \033[32m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return {'success': True, 'message': 'Конфиг-файл ноды обновился!'}

    except ClientResponseError as e:
        log_event(f'Нода ответила, что-то пошло не так | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m; node_proto_id: \033[31m{body.node_proto_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Ошибка исполнения на ноде'})

    except Exception as e:
        log_event(f'Ошибка исполнения на админке, не удалось записать файл | error: \033[31m{e}\033[0m; node_proto_id: \033[33m{body.node_proto_id}\033[0m',request=request, level='CRITICAL')
        raise HTTPException(status_code=500, detail="Ошибка исполнения на админке")
