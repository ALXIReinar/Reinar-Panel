from typing import Annotated

from aiohttp import ClientResponseError, ClientError, ClientTimeout
from fastapi import APIRouter, HTTPException
from fastapi.params import Query
from starlette.requests import Request

from web.api.protocols.proto_links_templates.handlers import generate_link_from_json
from web.config_dir.config import NodeExecAiohttpDep
from web.api.node_commander.handlers import resolve_user_template
from web.data.postgres import PgSqlDep
from web.data.redis_storage import RedisDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.node_commander_schema import ExecCMDNodeSchema, ReadConfigSchema, WriteConfigSchema, \
    DeleteUserCoreProtoSchema, AddUserCoreProtoSchema
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

    "Проверка по белому списку"
    if not await CommandWhitelistCache.is_whitelisted(body.cmd, redis, db):
        log_event(f'Команда не прошла по Whitelist | node_proto_id: \033[32m{body.node_proto_id}\033[0m; cmd: \033[36m{body.cmd}\033[0m; base_cmd: \033[37m{base_cmd}\033[0m; private_ip: \033[33m{body.private_ip}\033[0m; api_port: \033[35m{body.api_port}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        raise HTTPException(status_code=400, detail={'success': False, 'message': f'Команда {body.cmd} не находится в белом списке'})

    "Фиксиурем запрос на удалённое исполнение команды"
    action_id = await db.remote_command_history.save_action(body.node_proto_id, body.private_ip, body.api_port, body.cmd)

    "Отправка команды на ноду"
    # url = f'http://{body.private_ip}:{body.api_port}{NodeUris.exec_cmd}'
    url = f'http://localhost:18100{NodeUris.exec_cmd}'
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
    node_info = await db.nodes_protocols.get_node_for_file_edit(q_params.node_proto_id)

    "Виртуальной ноды не существует"
    if node_info is None:
        log_event(f'Виртуальной ноды не существует | node_proto_id: \033[32m{q_params.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Виртуальная нода не найдена'})

    "Не указан путь к файлу"
    if node_info['config_path'] is None:
        log_event(f'Путь к файлу не указан, не можем прочесть конфиг | node_proto_id: \033[32m{q_params.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Путь к конфиг-файлу протокола не указан!'})

    "Запрашиваем файл с ноды"
    try:
        url = f'http://{node_info['private_ip']}:{node_info['api_port']}{NodeUris.get_config_file}'
        async with aio_http.post(url, json={'path': node_info['config_path'], 'flatten_json_users_key': q_params.flatten_json_users_key}) as resp:
            resp.raise_for_status()
            resp_data = await resp.json()

        log_event(f'Нода прислала конфиг-файл | node_proto_id: \033[32m{q_params.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        return {'success': True, 'file_content': resp_data['stdout'], 'message': 'Получен конфиг-файл от ноды'}

    except ClientResponseError as e:
        log_event(f'Нода ответила, что-то пошло не так | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m; node_proto_id: \033[31m{q_params.node_proto_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Ошибка исполнения на ноде'})

    except ClientTimeout:
        log_event(f'Таймаут при чтении конфига | node_proto_id: \033[31m{q_params.node_proto_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Превышен таймаут запроса'})

    except Exception as e:
        log_event(f'Ошибка исполнения на админке, не удалось прочесть файл | error: \033[31m{e}\033[0m; node_proto_id: \033[33m{q_params.node_proto_id}\033[0m', request=request, level='CRITICAL')
        raise HTTPException(status_code=500, detail="Ошибка исполнения на админке")



@router.put('/config_file/write')
async def config_file_write(body: WriteConfigSchema, request: Request, db: PgSqlDep, aio_http: NodeExecAiohttpDep, _: JWTCookieDep):
    log_event(f'Пробуем записать конфиг-файл с ноды | node_proto_id: \033[32m{body.node_proto_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Запрашиваем файл с ноды"
    try:
        url = f'http://{body.private_ip}:{body.api_port}{NodeUris.write_config_file}'
        async with aio_http.post(url, json={'file': body.file_path, 'content': body.file_content, 'flatten_json_users_key': body.flatten_json_users_key}) as resp:
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

    except ClientTimeout:
        log_event(f'Таймаут при чтении конфига | node_proto_id: \033[31m{body.node_proto_id}\033[0m', request=request, level='ERROR')
        raise HTTPException(status_code=400, detail={'success': False, 'message': 'Превышен таймаут запроса'})

    except Exception as e:
        log_event(f'Ошибка исполнения на админке, не удалось записать файл | error: \033[31m{e}\033[0m; node_proto_id: \033[33m{body.node_proto_id}\033[0m',request=request, level='CRITICAL')
        raise HTTPException(status_code=500, detail="Ошибка исполнения на админке")



@router.post('/core_protocol/user/add')
async def add_user(
        body: AddUserCoreProtoSchema, request: Request, db: PgSqlDep, aio_http: NodeExecAiohttpDep, _: JWTCookieDep
):
    """
    Добавление пользователя по активной подписке.
    1. Поиск доступных пользователю нод по **единственной** подписке
    2. Запрос на добавление на каждую ноду по подписке
    """
    log_event(f'Юзер в конфиг-файлы ядер на нодах | uuid: \033[35m{body.uuid}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Все ноды по подписке. Запрос на добавление на каждую ноду"
    trouble_nodes = []
    sub_nodes = await db.nodes_protocols.get_core_proto_deps_by_user_sub(body.uuid)

    for cpi in sub_nodes: # core_proto_info
        try:
            # Подстановка значений в шаблон через маркеры
            required_user_obj = resolve_user_template(
                template=cpi['required_user_data_obj'],
                uuid=body.uuid,
                tg_username=body.tg_username,
                additional_fields=body.additional_fields or {}
            )
            final_user_obj = {
                **required_user_obj,
                **cpi['constant_user_data_obj']
            }
            
        except ValueError as e:
            # Ошибка валидации шаблона (отсутствует требуемое поле)
            log_event(f'Ошибка валидации шаблона | node_proto_id: \033[33m{cpi["node_proto_id"]}\033[0m; error: \033[31m{str(e)}\033[0m', request=request, level='ERROR')
            trouble_nodes.append({
                'node_proto_id': cpi['node_proto_id'], 
                'status_code': 400, 
                'response_json': {'error': f'Template validation error: {str(e)}'}
            })
            continue

        "Отправляем запрос на ноду, в ядро протокола"
        log_event(f'Юзер в конфиг-файл ядра | uuid: \033[35m{body.uuid}\033[0m; node_proto_id: \033[33m{cpi['node_proto_id']}\033[0m; private_ip: \033[33m{cpi['private_ip']}\033[0m; api_port: \033[35m{cpi['api_port']}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

        url = f"http://{cpi['private_ip']}:{cpi['api_port']}{NodeUris.proto_core_add_user}"
        json_body = {
            'node_proto_id': cpi['node_proto_id'],
            'core_lib': cpi['proto_python_lib'],
            'user_uuid': body.uuid,
            'user_obj': final_user_obj,
            'flatten_user_identifier_key': cpi['flatten_user_identifier_key'],
            'add_script': cpi['api_add_user_script'],
            'core_port': cpi['metrics_port'],
            'reload_core_command': cpi['reload_core_command'],
            'config_file_path': cpi['config_path'],
            'flatten_json_users_key': cpi['flatten_json_users_key'],
        }
        async with aio_http.post(url, json=json_body) as resp:
            resp_json = await resp.json()
            resp_status = resp.status

        "Проблемы при добавлении"
        if resp_status != 200:
            trouble_nodes.append({'node_proto_id': cpi['node_proto_id'], 'status_code': resp_status, 'response_json': resp_json})

    total, trouble = len(sub_nodes), len(trouble_nodes)
    level = 'INFO' if trouble == 0 else 'ERROR'
    log_event(f'Пользователь добавлен в ядра виртуальных нод | successful: \033[32m{total - trouble}\033[0m; trouble: \033[31m{trouble}\033[0m; trouble_ext: \033[36m{trouble_nodes}\033[0m', request=request, level=level)
    return {'success': True, 'message': 'Пользователь добавлен на ноды', 'trouble_nodes': trouble_nodes}



@router.delete('/core_protocol/user/delete')
async def delete_user(
        body: DeleteUserCoreProtoSchema, request: Request, db: PgSqlDep, aio_http: NodeExecAiohttpDep, _: JWTCookieDep
):
    """
    Удаление пользователя по активной подписке.
    1. Поиск доступных пользователю нод по **единственной** подписке
    2. Запрос на удаление с каждой ноды из подписки
    """
    log_event(f'Удаление пользователя с нод | uuid: \033[35m{body.uuid}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Все ноды по подписке. Запрос на удаление на каждую ноду"
    trouble_nodes = []
    sub_nodes = await db.nodes_protocols.get_core_proto_deps_by_user_sub(body.uuid)

    for cpi in sub_nodes:  # core_proto_info
        log_event(f'Юзер на удаление из конфиг-файла ядра | uuid: \033[35m{body.uuid}\033[0m; node_proto_id: \033[33m{cpi['node_proto_id']}\033[0m; private_ip: \033[33m{cpi['private_ip']}\033[0m; api_port: \033[35m{cpi['api_port']}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        url = f"http://{cpi['private_ip']}:{cpi['api_port']}{NodeUris.proto_core_delete_user}"
        json_body = {
            'node_proto_id': cpi['node_proto_id'],
            'core_lib': cpi['proto_python_lib'],
            'user_uuid': body.uuid,
            'delete_script': cpi['api_delete_user_script'],
            'core_port': cpi['metrics_port'],
        }

        "Отправляем запрос на ноду, в ядро протокола"
        async with aio_http.post(url, json=json_body) as resp:
            resp_json = await resp.json()
            resp_status = resp.status

        "Проблемы при удалении"
        if resp_status != 200:
            trouble_nodes.append(
                {'node_proto_id': cpi['node_proto_id'], 'status_code': resp_status, 'response_json': resp_json})

    total, trouble = len(sub_nodes), len(trouble_nodes)
    level = 'INFO' if trouble == 0 else 'CRITICAL'
    log_event(f'Пользователь удалён с ядер виртуальных нод | successful: \033[32m{total}\033[0m; trouble: \033[31m{trouble}\033[0m; trouble_ext: \033[36m{trouble_nodes}\033[0m', request=request, level=level)
    return {
        'success': True if trouble == 0 else False,
        'message': 'Пользователь удалён с нод',
        'trouble_nodes': trouble_nodes
    }