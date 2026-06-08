from aiohttp import ClientSession, ClientResponseError
from arq import ArqRedis

from web.sub.anything import NodeUris, CoreProtoActions
from web.sub.arq_tasks.depends_fabric import pg_sql_dep, arq_dep, aiohttp_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.data.postgres import PgSql


@pg_sql_dep
@arq_dep
async def revoke_sub_plan_by_expire(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    log_event('\033[31m[ARQ Sub Revoke]\033[0m Срок действия подписки истёк. Крона по удалению пользователей из ядер протоколов')
    expired_users_by_node = await db.sub.get_and_lock_expired_subs_grouped_by_node()
    if not expired_users_by_node:
        log_event('\033[31m[ARQ Sub Revoke]\033[0m Нет истёкших подписок. Idle')
        return {'success': True, 'message': 'Нет просроченных подписок'}

    users_to_delete = sum(len(vnode['users']) for vnode in  expired_users_by_node)
    log_event(f'\033[31m[ARQ Sub Revoke]\033[0m Крона по удалению пользователей из ядер протоколов | total_deletes: \033[31m{users_to_delete}\033[0m')

    "Отправляем chain task на каждую ноду для бульк удаления"
    for vnode in expired_users_by_node:
        if len(vnode['users']) > 0:
            log_event(f'\033[31m[ARQ Sub Revoke]\033[0m Отправляем Бульк запрос на фоновое удаление пользователей из ядра | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            job = await arq.enqueue_job(
                'bulk_delete_users_from_single_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                vnode['api_bulk_delete_user_script'],
                vnode['bulk_delete_script_custom_params'],
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['flatten_json_users_key'],
                vnode['flatten_user_identifier_key'],
            )
            log_event(f'\033[31m[ARQ Sub Revoke]\033[0m Фоновая задача запущена | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    return {'success': True, 'message': 'Запущено Бульк удаление с нод', 'total_nodes': len(expired_users_by_node)}


@pg_sql_dep
@arq_dep
@aiohttp_dep
async def bulk_delete_users_from_single_node(
        ctx: dict,
        node_proto_id: int,
        private_ip: str,
        api_port: int,
        metrics_port: int,
        proto_python_lib: str,
        api_bulk_delete_user_script: str,
        bulk_delete_script_custom_params: dict | None,
        users: list[dict],
        reload_core_command: str,
        config_file_path: str,
        flatten_json_users_key: str,
        flatten_user_identifier_key: str,
        current_attempt = 1,
        db: PgSql = None,
        arq: ArqRedis = None,
        aio_http: ClientSession = None,
):
    log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Юзер на удаление из конфиг-файла ядра | users_len: \033[35m{len(users)}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; private_ip: \033[33m{private_ip}\033[0m; api_port: \033[35m{api_port}\033[0m')
    url = f"http://{private_ip}:{api_port}{NodeUris.proto_core_bulk_delete_users}"
    # url = f"http://localhost:8200{NodeUris.proto_core_bulk_delete_users}"
    json_body = {
        'node_proto_id': node_proto_id,
        'core_lib': proto_python_lib,
        'users': users,
        'bulk_delete_script': api_bulk_delete_user_script,
        'core_port': metrics_port,
        'reload_core_command': reload_core_command,
        'config_file_path': config_file_path,
        'flatten_json_users_key': flatten_json_users_key,
        'flatten_user_identifier_key': flatten_user_identifier_key,
        'custom_params': bulk_delete_script_custom_params
    }
    try:
        "Отправляем запрос на ноду, в ядро протокола"
        async with aio_http.delete(url, json=json_body, timeout=60.0) as resp:
            resp.raise_for_status()

        "Очищаем outbox при успешном удалении"
        sub_node_ids = [u['sub_node_id'] for u in users]
        order_ids = [u['order_id'] for u in users]

        await db.sub.success_bulk_core_proto_users(sub_node_ids, order_ids, CoreProtoActions.delete)
        log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Юзеры удалены из конфиг-файла ядра | users_len: \033[35m{len(users)}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; private_ip: \033[33m{private_ip}\033[0m; api_port: \033[35m{api_port}\033[0m')
        return {'success': True, 'message': 'Пользователи удалены из инстанса ядра'}
    except ClientResponseError as err:
        if err.status == 422:
            log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Ошибка валидации в Инстансе ядре. Неправильные | node_proto_id: \033[33m{node_proto_id}\033[0m; operation: \033[36mbulk-add\033[0m; error: {err}', level='WARNING')
            return {'success': False, 'message': 'Не удалось прокинуть Бульк вставку пользователей в ядро. 422 от нод-клиента'}
        log_event(f'\033[31m[ARQ Bulk Delete]\033[0m HTTP ошибка | node_proto_id: \033[33m{node_proto_id}\033[0m; operation: \033[36mbulk-add\033[0m; status: \033[31m{err.status}\033[0m', level='ERROR')

    
    except Exception as e:
        log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Ошибка запроса на бульк удаление. Ретрай | node_proto_id: \033[33m{node_proto_id}\033[0m; users_len: {len(users)}; error: \033[36m{e}\033[0m', level='ERROR')

    "1. Retry: если есть failed ноды, отправляем повторную попытку"
    max_tries = 3
    if current_attempt < max_tries:
        log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Планируем retry | попытка: \033[33m{current_attempt + 1}/{max_tries}\033[0m; users_len: \033[33m{len(users)}\033[0m; node_proto_id: \033[36m{node_proto_id}\033[0m',level='WARNING')

        "Повторяем задачу с экспоненциальной задержкой: 60, 120, 240 секунд"
        defer_seconds = 60 * (2 ** current_attempt)

        "2. Запуск новой задачи"
        await arq.enqueue_job(
            'bulk_delete_users_from_single_node',
            node_proto_id,
            private_ip,
            api_port,
            metrics_port,
            proto_python_lib,
            api_bulk_delete_user_script,
            bulk_delete_script_custom_params,
            users,
            reload_core_command,
            config_file_path,
            flatten_json_users_key,
            flatten_user_identifier_key,
            current_attempt + 1,            # Инкрементируем попытку
            _defer_by=defer_seconds         # Откладываем выполнение
        )

    else:
        "3. Попытки кончились. Крона попробует снова"
        log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Удаление по истёкшим подпискам. Превышено количество попыток | max_tries: {max_tries}; node_proto_id: \033[31m{node_proto_id}\033[0m', level='ERROR')

    return {'success': True, 'message': 'Попытка бульк удаления пользователей с нод', 'current_attempt': current_attempt}
