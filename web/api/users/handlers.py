import asyncio
from typing import Literal

from arq import ArqRedis

from web.config_dir.config import env
from web.utils.anything import CoreProtoActions
from web.utils.logger_config import log_event


async def put_to_arq_bg_bulk(
        arq: ArqRedis, outbox_event_ids: list[dict], action: Literal['activate', 'deactivate', 'reset_traffic', 'add', 'delete']
) -> str:
    """
    В микросервисе фона/подписок 5 путей с админки исполняются 2 функциями
    1. reset_traffic - с помощью reset_day_user_traffic
    2,3,4,5. - с помощью admin_request_bulk_action_users

    admin_request_bulk_action_users - принимает action(единая точка входа для вставки и удаления).
    А активация и деактивация это простые вставка и удаление для впн-ядер(xray, hysteria)

    P.S. Тестировать под микроскопом. Необходимы тесты на подачу аргументов именно в таком порядке, как сейчас.\\
    То же относится к sql запросам: order_id, sub_plan_id, user_id
    """
    action_simple = {
        'add': 'add',
        'activate': 'add',
        'delete': 'delete',
        'deactivate': 'delete',
    }
    # Если это что-то с активацией, то это просто удаление/вставка. Иначе это 'reset_traffic'
    action = action_simple.get(action, 'reset_traffic')

    "Выбираем нужную фоновую задачу"
    bg_func_params = ('admin_request_bulk_action_users', (action, outbox_event_ids,))
    if action == 'reset_traffic':
        bg_func_params = ('reset_day_user_traffic', (outbox_event_ids,))

    "Запускаем"
    arq_bg_task_name, task_args = bg_func_params
    job = await arq.enqueue_job(arq_bg_task_name, *task_args)
    return job.job_id


async def put_to_arq_bg_single(arq: ArqRedis, nodes_pack: list, action: Literal['add', 'delete']) -> list[str]:
    """
    Вставки и удаления требуют изменений на впн ядрах.
    
    :param nodes_pack: Список подписок, где каждая подписка содержит:
        - node_proto_id,
        - private_ip,
        - api_port,
        - ...

        - users: JSON массив [{user_sub_id, uuid, event_id}, ...]

    Так что параллельно раскидываем ноды. Они раскидают по пользователям всё это
    """
    sem = asyncio.Semaphore(env.node_metrics_queue_limit)
    
    async def worker(vnode: dict):
        async with sem:
            action_script_custom_params = {
                'delete': (vnode['api_bulk_delete_user_script'], vnode['bulk_delete_script_custom_params'], CoreProtoActions.delete),
                'add': (vnode['api_bulk_add_user_script'], vnode['bulk_add_script_custom_params'], CoreProtoActions.add),
            }
            job = await arq.enqueue_job(
                'bulk_action_users_by_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                *action_script_custom_params[action],
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['user_injectors'],
                vnode['required_user_data_obj'],
                vnode['constant_user_data_obj'],
            )
            log_event(f'\033[35m[User Subs Editor]\033[0m Отправили в фон \033[34m{action}\033[0m на ноду | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m; users: \033[32m{vnode["users"]}\033[0m; job_id: \033[31m{job.job_id}\033[0m')
            return job.job_id

    job_ids = await asyncio.gather(*(worker(vnode) for vnode in nodes_pack if len(vnode['users']) > 0))
    return job_ids
