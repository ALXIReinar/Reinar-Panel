from aiohttp import ClientSession, ClientResponseError
from arq import ArqRedis

from web.sub.anything import NodeUris, CoreProtoActions
from web.sub.arq_tasks.action_on_user_core_proto import resolve_user_template
from web.sub.arq_tasks.depends_fabric import pg_sql_dep, arq_dep, aiohttp_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.data.postgres import PgSql


@pg_sql_dep
@arq_dep
async def reset_day_user_traffic(ctx: dict, users: list[dict] | None = None, db: PgSql = None, arq: ArqRedis = None):
    log_event(f'\033[35m[ARQ Traffic Reset]\033[0m Обнуление трафика пользователей. \033[34m(Крона, если user_ids = None)\033[0m | user_ids: {user_ids}', level='WARNING')
    if users:
        unlock_users_by_node = await db.users_subs.reset_traffic_by_users(users)
    else:
        unlock_users_by_node = await db.users_subs.reset_user_traffic_per_day()
    users_to_add = sum(len(vnode['users']) for vnode in unlock_users_by_node)
    log_event(f'\033[32m[ARQ Traffic Reset]\033[0m Крона по возврату пользователей после обнуления трафика | total_adds: \033[31m{users_to_add}\033[0m')

    if not users_to_add:
        log_event('\033[32m[ARQ Traffic Reset]\033[0m Нет пользователей, блокированных по лимиту трафика. Idle')
        return {'success': True, 'message': 'Нет пользователей, блокированных по лимиту трафика'}

    "Отправляем chain task на каждую ноду для бульк добавления в ядра"
    for vnode in unlock_users_by_node:
        if len(vnode['users']) > 0:
            log_event(f'\033[35m[Traffic Reset]\033[0m Отправляем Бульк запрос на фоновое добавление пользователей в ядра | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            job = await arq.enqueue_job(
                'bulk_add_users_into_single_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                vnode['api_bulk_add_user_script'],
                vnode['bulk_add_script_custom_params'],
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['flatten_json_users_key'],
                vnode['flatten_user_identifier_key'],
                vnode['required_user_data_obj'],
                vnode['constant_user_data_obj'],
            )
            log_event(f'\033[35m[Traffic Reset]\033[0m Фоновая задача запущена, бульк-добавление | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    return {'success': True, 'message': 'Трафик пользователей обнулён', 'is_definite_users': bool(users)}



@arq_dep
@pg_sql_dep
@aiohttp_dep
async def bulk_add_users_into_single_node(
        ctx: dict,
        node_proto_id: int,
        private_ip: str,
        api_port: int,
        metrics_port: int,
        proto_python_lib: str,
        api_add_user_script: str,
        bulk_add_script_custom_params: dict | None,
        users: list[dict],
        reload_core_command: str,
        config_file_path: str,
        flatten_json_users_key: str,
        flatten_user_identifier_key: str,
        required_user_data_obj: dict,
        constant_user_data_obj: dict,
        current_attempt = 1,
        db: PgSql = None,
        arq: ArqRedis = None,
        aio_http: ClientSession = None,
):
    log_event(f'\033[35m[ARQ Bulk Add]\033[0m Юзер на удаление из конфиг-файла ядра | users_len: \033[35m{len(users)}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; private_ip: \033[33m{private_ip}\033[0m; api_port: \033[35m{api_port}\033[0m')

    "Собираем готовые объекты пользователей для конфиг-файлов ядра протокола"
    users_to_core = [{
        **resolve_user_template(
            template=required_user_data_obj,
            uuid=u['uuid'],
            tg_username=u['tg_username'],
        ),
        **constant_user_data_obj
    }
    for u in users]

    "Готовим тело запроса и Url"
    url = f"http://{private_ip}:{api_port}{NodeUris.proto_core_bulk_add_users}"
    # url = f"http://localhost:8200{NodeUris.proto_core_bulk_add_users}"
    json_body = {
        'node_proto_id': node_proto_id,
        'core_lib': proto_python_lib,
        'users': users_to_core,
        'bulk_add_script': api_add_user_script,
        'core_port': metrics_port,
        'reload_core_command': reload_core_command,
        'config_file_path': config_file_path,
        'flatten_json_users_key': flatten_json_users_key,
        'flatten_user_identifier_key': flatten_user_identifier_key,
        'custom_params': bulk_add_script_custom_params
    }
    # log_event(f'Бульк Адд тело запроса для Сваггера\n\033[34m{orjson.dumps(json_body, option=orjson.OPT_INDENT_2).decode()}\033[0m', level='DEBUG')
    try:
        "Отправляем запрос на ноду, в ядро протокола"
        async with aio_http.post(url, json=json_body, timeout=60.0) as resp:
            resp.raise_for_status()

        "Очищаем outbox при успешном добавлении"
        sub_node_ids = [u['sub_node_id'] for u in users]
        order_ids = [u['order_id'] for u in users]

        await db.sub.success_bulk_core_proto_users(sub_node_ids, order_ids, CoreProtoActions.add)
        log_event(f'\033[35m[ARQ Bulk Add]\033[0m Юзеры Добавлены в конфиг-файл ядра | users_len: \033[35m{len(users)}\033[0m; node_proto_id: \033[33m{node_proto_id}\033[0m; private_ip: \033[33m{private_ip}\033[0m; api_port: \033[35m{api_port}\033[0m')
        return {'success': True, 'message': 'Пользователи добавлены в инстанс ядра'}

    except ClientResponseError as err:
        if err.status == 422:
            log_event(f'\033[35m[ARQ Bulk Add]\033[0m Ошибка валидации в Инстансе ядре | node_proto_id: \033[33m{node_proto_id}\033[0m; operation: \033[36mbulk-add\033[0m; error: {err}', level='WARNING')
            return {'success': False, 'message': 'Не удалось прокинуть Бульк вставку пользователей в ядро. 422 от нод-клиента'}
        log_event(f'\033[33m[ARQ Bulk Add]\033[0m HTTP ошибка | node_proto_id: \033[33m{node_proto_id}\033[0m; operation: \033[36mbulk-add\033[0m; status: \033[31m{err.status}\033[0m; err: {err}', level='ERROR')

    except Exception as e:
        log_event(f'\033[35m[ARQ Bulk Add]\033[0m Ошибка запроса на бульк Добавление. Ретрай | node_proto_id: \033[33m{node_proto_id}\033[0m; users_len: {len(users)}; error: \033[36m{e}\033[0m', level='ERROR')

    "1. Retry: если есть failed ноды, отправляем повторную попытку"
    max_tries = 3
    if current_attempt < max_tries:
        log_event(f'\033[35m[ARQ Bulk Add]\033[0m Планируем retry | попытка: \033[33m{current_attempt + 1}/{max_tries}\033[0m; users_len: \033[33m{len(users)}\033[0m; node_proto_id: \033[36m{node_proto_id}\033[0m',level='WARNING')

        "Повторяем задачу с экспоненциальной задержкой: 60, 120, 240 секунд"
        defer_seconds = 60 * (2 ** current_attempt)

        "2. Запуск новой задачи"
        await arq.enqueue_job(
            'bulk_add_users_into_single_node',
            node_proto_id,
            private_ip,
            api_port,
            metrics_port,
            proto_python_lib,
            api_add_user_script,
            bulk_add_script_custom_params,
            users,
            reload_core_command,
            config_file_path,
            flatten_json_users_key,
            flatten_user_identifier_key,
            required_user_data_obj,
            constant_user_data_obj,
            current_attempt + 1,            # Инкрементируем попытку
            _defer_by=defer_seconds         # Откладываем выполнение
        )

    else:
        "3. Попытки кончились. Крона попробует снова"
        log_event(f'\033[35m[ARQ Bulk Add]\033[0m Добавление(возврат) пользователей после обнуления трафика. Превышено количество попыток | max_tries: {max_tries}; node_proto_id: \033[31m{node_proto_id}\033[0m', level='ERROR')

    return {'success': True, 'message': 'Попытка бульк добавления пользователей в ядра', 'current_attempt': current_attempt}
