import asyncio

from aiohttp import ClientSession, ClientResponseError
from arq import ArqRedis

from web.arq_worker.config import env
from web.arq_worker.data.postgres import PgSql
from web.arq_worker.depends_fabric import pg_sql_dep, arq_dep
from web.arq_worker.utils.anything import CoreProtoActions
from web.arq_worker.utils.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
async def revoke_sub_plan_by_expire(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    log_event('\033[31m[ARQ Sub Revoke]\033[0m Срок действия подписки истёк. Крона по удалению пользователей из ядер протоколов')
    expired_users_by_node = await db.core_proto_bulk.get_and_lock_expired_subs_grouped_by_node()
    if not expired_users_by_node:
        log_event('\033[31m[ARQ Sub Revoke]\033[0m Нет истёкших подписок. Idle')
        return {'success': True, 'message': 'Нет просроченных подписок'}

    users_to_delete = sum(len(vnode['users']) for vnode in expired_users_by_node)
    log_event(f'\033[31m[ARQ Sub Revoke]\033[0m Крона по удалению пользователей из ядер протоколов | total_deletes: \033[31m{users_to_delete}\033[0m')

    sem = asyncio.Semaphore(env.action_on_core_proto_limit)

    async def enqueue_delete(vnode):
        async with sem:
            "Отправляем chain task на каждую ноду для бульк удаления"
            log_event(f'\033[31m[ARQ Sub Revoke]\033[0m Отправляем Бульк запрос на фоновое удаление пользователей из ядра | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            job = await arq.enqueue_job(
                'bulk_action_users_by_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                vnode['api_bulk_delete_user_script'],
                vnode['bulk_delete_script_custom_params'],
                CoreProtoActions.delete,
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['user_injectors'],
                vnode['required_user_data_obj'],
                vnode['constant_user_data_obj'],
                vnode['constant_node_data_obj'],
                vnode['config_format'],
            )
            log_event(f'\033[31m[ARQ Sub Revoke]\033[0m Фоновая задача запущена | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    "Размеренная обработка"
    await asyncio.gather(*[enqueue_delete(vnode) for vnode in expired_users_by_node if len(vnode['users']) > 0])

    return {'success': True, 'message': 'Запущено Бульк удаление с нод', 'total_nodes': len(expired_users_by_node)}
