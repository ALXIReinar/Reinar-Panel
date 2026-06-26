from typing import Literal

from arq import ArqRedis


async def put_to_arq_bg(
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
