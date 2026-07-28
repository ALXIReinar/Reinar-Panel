import asyncio
from typing import Literal

from arq import ArqRedis

from web.config_dir.config import env
from web.utils.logger_config import log_event


async def put_to_arq_bg_bulk(
        arq: ArqRedis, user_ids: list[dict], action: Literal['activate', 'deactivate', 'reset_traffic', 'add', 'delete']
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
    bg_func_params = ('admin_request_bulk_action_users', (action, user_ids,))
    if action == 'reset_traffic':
        bg_func_params = ('reset_day_user_traffic', (user_ids,))

    "Запускаем"
    arq_bg_task_name, task_args = bg_func_params
    job = await arq.enqueue_job(arq_bg_task_name, *task_args)
    return job.job_id


async def put_to_arq_bg_single(arq: ArqRedis, nodes_pack: list, action: Literal['add', 'delete']) -> list[str]:
    """
    Вставки и удаления требуют изменений на впн ядрах.
    
    :param nodes_pack: Список подписок, где каждая подписка содержит:
        - user_sub_id
        - uuid
        - sub_plan_id
        - nodes: JSON массив [{node_proto_id, private_ip, api_port, ...}, ...]
    """
    sem = asyncio.Semaphore(env.node_metrics_queue_limit)
    
    async def worker(subscription):
        async with sem:
            job = await arq.enqueue_job(
                'action_on_core_proto_by_sub_plan',
                subscription['uuid'],
                subscription['user_sub_id'],
                subscription['nodes'],
                action
            )
            log_event(f'\033[35m[User Subs Editor]\033[0m Отправили в фон \033[34m{action}\033[0m на ноды | nodes_len: \033[33m{len(subscription['nodes'])}\033[0m; uuid: \033[32m{subscription["uuid"]}\033[0m; user_sub_id: \033[35m{subscription["user_sub_id"]}\033[0m; job_id: \033[31m{job.job_id}\033[0m')
            return job.job_id

    job_ids = await asyncio.gather(*(worker(sub) for sub in nodes_pack))
    return job_ids
