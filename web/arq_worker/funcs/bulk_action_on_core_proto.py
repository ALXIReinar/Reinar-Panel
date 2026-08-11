from aiohttp import ClientResponseError, ClientSession
from arq import ArqRedis

from web.arq_worker.data.postgres import PgSql
from web.arq_worker.depends_fabric import pg_sql_dep, arq_dep, aiohttp_dep
from web.arq_worker.funcs.metrics_collector import create_vpn_like_user
from web.arq_worker.utils.anything import CoreProtoActions, NodeUris
from web.arq_worker.utils.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
@aiohttp_dep
async def bulk_action_users_by_node(
        ctx: dict,
        node_proto_id: int,
        private_ip: str,
        api_port: int,
        metrics_port: int,
        proto_python_lib: str,
        api_bulk_action_script: str,
        bulk_action_script_custom_params: dict | None,
        operation: int,
        users: list[dict],
        reload_core_command: str,
        config_file_path: str,
        user_injectors: list[dict],
        required_user_data_obj: dict,
        constant_user_data_obj: dict,
        current_attempt = 1,
        db: PgSql = None,
        arq: ArqRedis = None,
        aio_http: ClientSession = None,
):
    log_event(f'\033[31m[ARQ Bulk Action]\033[0m Бульк \033[33m{CoreProtoActions.id2name[operation]}\033[0m юзеров из конфиг-файла ядра | action: \033[33m{operation}\033[0m; raw_users_len: \033[35m{len(users)}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; private_ip: \033[33m{private_ip}\033[0m; api_port: \033[35m{api_port}\033[0m')

    "1. Формируем готовые объекты-пользователей для списка впн-ядра"
    vpn_like_users = []
    for u in users:
        success, vpn_user = await create_vpn_like_user(
            user_uuid=u['uuid'],
            user_sub_id=u['user_sub_id'],
            required_user_data_obj=required_user_data_obj,
            constant_user_data_obj=constant_user_data_obj,
        )
        if success:
            vpn_like_users.append(vpn_user)

    "1.2. Если ни одного пользователя не создалось, не запускаем бульк"
    if not vpn_like_users:
        log_event(f'\033[31m[ARQ Bulk Action]\033[0m Не удалось создать ни одного впн-пользователя для ядра | node_proto_id: \033[31m{node_proto_id}\033[0m; action: \033[33m{operation}\033[0m', level='CRITICAL')
        return {'success': False, 'message': 'Нет впн-пользователей для ядра'}


    # url = f"http://localhost:8200{NodeUris.proto_core_bulk_delete_users}"
    url = f"http://{private_ip}:{api_port}{NodeUris.proto_core_bulk_action}"
    json_body = {
        'node_proto_id': node_proto_id,
        'core_lib': proto_python_lib,
        'users': vpn_like_users,
        'action_script': api_bulk_action_script,
        'core_port': metrics_port,
        'reload_core_command': reload_core_command,
        'config_file_path': config_file_path,
        'user_injectors': user_injectors,
        'custom_params': bulk_action_script_custom_params,
        'action': operation,
    }
    try:
        "2. Отправляем запрос на ноду, для изменений в впн-ядре"
        async with aio_http.put(url, json=json_body, timeout=60.0) as resp:
            resp.raise_for_status()

        "3. Очищаем outbox при успешной операции"
        outbox_event_ids = []
        for u in users:
            event = u['event_id']

            "Если список, то это ack от Outbox Cron"
            if isinstance(event, list):
                outbox_event_ids.extend(event)
            else:
                outbox_event_ids.append(event)


        await db.core_proto_bulk.success_bulk_action_core_proto_users(outbox_event_ids)
        log_event(f'\033[31m[ARQ Bulk Action]\033[0m Юзеры удалены из конфиг-файла ядра | action: \033[33m{operation}\033[0m; users_len: \033[35m{len(users)}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; private_ip: \033[33m{private_ip}\033[0m; api_port: \033[35m{api_port}\033[0m')
        return {'success': True, 'message': 'Пользователи удалены из инстанса ядра'}
    except ClientResponseError as err:
        if err.status == 422:
            log_event(f'\033[31m[ARQ Bulk Delete]\033[0m Ошибка валидации в Инстансе ядре. Неправильные | action: \033[33m{operation}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; error: {err}', level='WARNING')
            return {'success': False, 'message': 'Не удалось прокинуть Бульк вставку пользователей в ядро. 422 от нод-клиента'}
        log_event(f'\033[31m[ARQ Bulk Action]\033[0m HTTP ошибка | action: \033[33m{operation}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; operation: \033[36mbulk-add\033[0m; status: \033[31m{err.status}\033[0m', level='ERROR')


    except Exception as e:
        log_event(f'\033[31m[ARQ Bulk Action]\033[0m Ошибка запроса на \033[33m{CoreProtoActions.id2name[operation]}\033[0m. Ретрай | action: \033[33m{operation}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; users_len: {len(users)}; error: \033[36m{e}\033[0m', level='ERROR')

    "1. Retry: если есть failed ноды, отправляем повторную попытку"
    max_tries = 3
    if current_attempt < max_tries:
        log_event(f'\033[31m[ARQ Bulk Action]\033[0m Планируем retry | action: \033[33m{operation}\033[0m; attempt: \033[33m{current_attempt + 1}/{max_tries}\033[0m; users_len: \033[33m{len(users)}\033[0m; node_proto_id: \033[36m{node_proto_id}\033[0m',level='WARNING')

        "Повторяем задачу с экспоненциальной задержкой: 60, 120, 240 секунд"
        defer_seconds = 60 * (2 ** current_attempt)

        "2. Запуск новой задачи"
        await arq.enqueue_job(
            'bulk_action_users_by_node',
            node_proto_id,
            private_ip,
            api_port,
            metrics_port,
            proto_python_lib,
            api_bulk_action_script,
            bulk_action_script_custom_params,
            operation,
            users,
            reload_core_command,
            config_file_path,
            user_injectors,
            required_user_data_obj,
            constant_user_data_obj,
            current_attempt + 1,            # Инкрементируем попытку
            _defer_by=defer_seconds         # Откладываем выполнение
        )

    else:
        "3. Попытки кончились. Крона попробует снова"
        log_event(f'\033[31m[ARQ Bulk Action]\033[0m Бульк операция. Превышено количество попыток | action: \033[33m{operation}\033[0m; max_tries: {max_tries}; node_proto_id: \033[31m{node_proto_id}\033[0m', level='ERROR')

    return {'success': True, 'message': 'Попытка бульк операции над пользователями', 'current_attempt': current_attempt}
