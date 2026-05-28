import asyncio
from typing import Literal

from aiohttp import ClientSession, ClientResponseError
from arq import ArqRedis

from web.sub.anything import NodeUris
from web.sub.arq_tasks.depends_fabric import aiohttp_dep, arq_dep, pg_sql_dep
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSql
from web.sub.config_dir.arq_logger_config import log_event



@aiohttp_dep
@arq_dep
@pg_sql_dep
async def action_on_core_proto_by_sub_plan(
        ctx: dict,
        user_uuid: str, tg_username: str, sub_nodes: list[dict], operation: Literal['add', 'delete'], current_attempt: int = 1,
        db: PgSql = None,
        aio_http: ClientSession = None,
        arq: ArqRedis = None
):
    log_event(f'\033[33m[ARQ]\033[0m Добавление пользователя на ноды | uuid: \033[35m{user_uuid}\033[0m; nodes_count: \033[32m{len(sub_nodes)}\033[0m', job_id=ctx.get('job_id'), task_name='add_user_core_proto_by_sub_plan')
    
    sem = asyncio.Semaphore(env.node_metrics_queue_limit)  # Батчинг нод
    trouble_nodes = []  # Критические ошибки (не ретраим)
    retry_nodes = []    # Временные ошибки (ретраим)
    success_nodes = []  # Ноды, где вставка пользователя прошла успешно
    success_count = 0
    
    async def worker(node: dict):
        """Обработка одной ноды"""
        nonlocal success_count
        
        async with sem:
            try:
                "1. Подстановка значений в шаблон через плейсхолдеры"
                required_user_obj = resolve_user_template(
                    template=node['required_user_data_obj'],
                    uuid=user_uuid,
                    tg_username=tg_username,
                )
                final_user_obj = {
                    **required_user_obj,
                    **node['constant_user_data_obj']
                }
            
            except ValueError as e:
                "Ошибка валидации шаблона (не ретраим, ошибка скрипта админа)"
                log_event(f'\033[33m[ARQ]\033[0m Ошибка валидации шаблона | node_proto_id: \033[33m{node["node_proto_id"]}\033[0m; operation: \033[36m{operation}\033[0m; error: \033[31m{str(e)}\033[0m', level='CRITICAL')
                trouble_nodes.append({
                    'node_proto_id': node['node_proto_id'],
                    'status_code': 400,
                    'response_json': {'error': f'Template validation error: {str(e)}'}
                })
                return
            
            "2. Подбираем тело запроса и эндпоинт в соответствии с operation"
            log_event(f'\033[33m[ARQ]\033[0m Добавление юзера в ядро | uuid: \033[35m{user_uuid}\033[0m; node_proto_id: \033[33m{node["node_proto_id"]}\033[0m; operation: \033[36m{operation}\033[0m; private_ip: \033[33m{node["private_ip"]}\033[0m; api_port: \033[35m{node['api_port']}\033[0m', level='DEBUG')
            json_add_body = {
                'node_proto_id': node['node_proto_id'],
                'core_lib': node['proto_python_lib'],
                'user_uuid': user_uuid,
                'user_obj': final_user_obj,
                'add_script': node['api_add_user_script'],
                'flatten_user_identifier_key': node['flatten_user_identifier_key'],
                'core_port': node['metrics_port'],
                'reload_core_command': node['reload_core_command'],
                'config_file_path': node['config_path'],
                'flatten_json_users_key': node['flatten_json_users_key'],
            }
            json_delete_body = {
                'node_proto_id': node['node_proto_id'],
                'core_lib': node['proto_python_lib'],
                'user_uuid': user_uuid,
                'delete_script': node['api_delete_user_script'],
                'flatten_user_identifier_key': node['flatten_user_identifier_key'],
                'core_port': node['metrics_port'],
                'reload_core_command': node['reload_core_command'],
                'config_file_path': node['config_path'],
                'flatten_json_users_key': node['flatten_json_users_key'],
            }
            action_pack = {
                'add': (json_add_body, NodeUris.proto_core_add_user),
                'delete': (json_delete_body, NodeUris.proto_core_delete_user)
            }
            # action_pack[operation][0] - json body;
            # action_pack[operation][1] - endpoint_uri
            url = f"http://{node['private_ip']}:{node['api_port']}{action_pack[operation][1]}"
            # url = f"http://localhost:8000/api/check_body"
            json_body = action_pack[operation][0]

            "3. Отправляем запрос на ноду"
            try:
                "3.1. Happy case"
                async with aio_http.post(url, json=json_body, timeout=30.0) as resp:
                    resp.raise_for_status()

                success_count += 1
                log_event(f'\033[33m[ARQ]\033[0m Пользователь добавлен | node_proto_id: \033[36m{node["node_proto_id"]}\033[0m')
                success_nodes.append(node['sub_node_id'])

            except ClientResponseError as e:
                "3.2. HTTP ошибка - ретраим"
                log_event(f'\033[33m[ARQ]\033[0m HTTP ошибка | node_proto_id: \033[33m{node["node_proto_id"]}\033[0m; operation: \033[36m{operation}\033[0m; status: \033[31m{e.status}\033[0m', level='ERROR')
                retry_nodes.append({
                    'node_proto_id': node['node_proto_id'],
                    'node_data': node,  # Уже dict, не нужно преобразовывать
                    'status_code': e.status,
                    'response_json': {'error': str(e)}
                })
            
            except Exception as e:
                "3.3. Неожиданная ошибка - ретраим"
                log_event(f'\033[33m[ARQ]\033[0m Неожиданная ошибка | node_proto_id: \033[33m{node["node_proto_id"]}\033[0m; operation: \033[36m{operation}\033[0m; error: \033[31m{e}\033[0m', level='CRITICAL')
                retry_nodes.append({
                    'node_proto_id': node['node_proto_id'],
                    'node_data': node,  # Уже dict, не нужно преобразовывать
                    'status_code': 500,
                    'response_json': {'error': str(e)}
                })
    
    "Запускаем воркеры параллельно"
    await asyncio.gather(*(worker(node) for node in sub_nodes))
    
    "Итоговая статистика"
    total = len(sub_nodes)
    failed = len(trouble_nodes) + len(retry_nodes)
    level = 'INFO' if failed == 0 else 'WARNING'
    
    log_event(f'\033[33m[ARQ]\033[0m Добавление пользователя завершено | operation: \033[36m{operation}\033[0m; success: \033[32m{success_count}\033[0m; trouble: \033[31m{len(trouble_nodes)}\033[0m; retry: \033[33m{len(retry_nodes)}\033[0m',
        level=level,
        success_count=success_count,
        error_count=failed
    )

    "Фиксируем в БД успешные вставки (удаляем маркеры для кроны на повторную вставку)"
    await db.sub.success_action_core_proto_user(success_nodes, operation, user_uuid)

    "1. Retry: если есть failed ноды, отправляем повторную попытку"
    if retry_nodes:
        max_tries = 3

        if current_attempt < max_tries:
            "Данные нод для retry"
            retry_sub_nodes = [node['node_data'] for node in retry_nodes]
            log_event(f'\033[33m[ARQ]\033[0m Планируем retry | попытка: \033[33m{current_attempt + 1}/{max_tries}\033[0m; nodes_count: \033[33m{len(retry_sub_nodes)}\033[0m; operation: \033[36m{operation}\033[0m', level='WARNING')

            "Повторяем задачу с экспоненциальной задержкой: 60, 120, 240 секунд"
            defer_seconds = 60 * (2 ** current_attempt)

            "2. Запуск новой задачи с ретрай-набором нод (уже dict, не Record)"
            await arq.enqueue_job(
                'action_on_core_proto_by_sub_plan',
                user_uuid,
                tg_username,
                retry_sub_nodes,
                operation,
                current_attempt + 1,  # Инкрементируем попытку
                _defer_by=defer_seconds  # Откладываем выполнение
            )

        else:
            "3. Попытки кончились. Крона попробует снова"
            log_event(f'\033[33m[ARQ]\033[0m Превышено количество попыток | max_tries: {max_tries}; failed_nodes: \033[31m{len(retry_nodes)}\033[0m; operation: \033[36m{operation}\033[0m', level='ERROR')

    return {
        'success': True,
        'message': 'Итерация завершена (см. retry_nodes)',
        'operation': operation,
        'total': total,
        'success_count': success_count,
        'trouble_nodes': trouble_nodes,
        'retry_nodes': retry_nodes
    }



def resolve_user_template(
        template: dict,
        uuid: str,
        tg_username: str | None = None,
        additional_fields: dict | None = None
) -> dict:
    """
    Подставляет значения в шаблон пользователя

    Поддерживаемые маркеры:
    - {USER_UUID} → uuid пользователя
    - {USER_TG_USERNAME} → telegram username
    - {USER_CUSTOM:field_name} → значение из additional_fields['field_name']
    - Обычное значение (без {}) → используется как есть

    Args:
        template: Шаблон из required_user_data_obj
        uuid: UUID пользователя (обязательно)
        tg_username: Telegram username (опционально)
        additional_fields: Дополнительные поля (опционально)

    Returns:
        dict: Разрешённый шаблон с подставленными значениями

    Raises:
        ValueError: Если требуемое поле отсутствует

    Examples:
        >>> template = {"id": "{USER_UUID}", "email": "{USER_TG_USERNAME}"}
        >>> resolve_user_template(template, "abc-123", "john_doe")
        {"id": "abc-123", "email": "john_doe"}

        >>> template = {"password": "{USER_UUID}"}
        >>> resolve_user_template(template, "abc-123")
        {"password": "abc-123"}

        >>> template = {"PublicKey": "{USER_CUSTOM:public_key}"}
        >>> resolve_user_template(template, "abc-123", additional_fields={"public_key": "key123"})
        {"PublicKey": "key123"}
    """
    if additional_fields is None:
        additional_fields = {}

    resolved = {}

    markers_map = {
        '{USER_UUID}': uuid,
        '{USER_TG_USERNAME}': tg_username,
    }
    if '{USER_TG_USERNAME}' in set(template.values()) and tg_username is None:
        raise ValueError(
            f"Одно из кастомных полей требует tg_username (плейсхолдер {{USER_TG_USERNAME}}), "
            f"но оно не передано в запросе"
        )

    for key, value in template.items():
        # Если значение не строка, используем как есть
        if not isinstance(value, str):
            resolved[key] = value
            continue

        # Подстановка маркеров
        if value in set(template.values()):
            resolved[key] = markers_map[value] # "custom_key": "{USER_UUID}" --> "{USER_UUID}": tg_username --> "custom_key": tg_username


        elif value.startswith('{USER_CUSTOM:') and value.endswith('}'):
            # Извлекаем имя поля: {USER_CUSTOM:field_name} → field_name
            field_name = value[13:-1]

            if field_name not in additional_fields:
                raise ValueError(
                    f"Поле '{key}' требует additional_fields['{field_name}'] "
                    f"(маркер {{USER_CUSTOM:{field_name}}}), но оно не передано в запросе"
                )
            resolved[key] = additional_fields[field_name]

        else:
            # Обычное значение или неизвестный маркер - используем как есть
            resolved[key] = value

    return resolved