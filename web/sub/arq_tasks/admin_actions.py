import asyncio
from typing import Literal

from arq import ArqRedis

from web.sub.anything import CoreProtoActions
from web.sub.arq_tasks.depends_fabric import pg_sql_dep, arq_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSql


@pg_sql_dep
@arq_dep
async def admin_request_bulk_action_users(action: Literal['delete', 'add'] | CoreProtoActions, users: list[int], db: PgSql = None, arq: ArqRedis = None):
    sub_nodes = await db.sub.get_sub_nodes_for_bulk_action(users)
    
    sem = asyncio.Semaphore(env.action_on_core_proto_limit)

    async def worker(vnode):
        async with (sem):
            "Отправляем chain task на каждую ноду для бульк удаления"
            action_script_custom_params = {
                'delete': (vnode['api_bulk_delete_user_script'], vnode['bulk_delete_script_custom_params']),
                'add': (vnode['api_bulk_add_user_script'], vnode['bulk_add_script_custom_params']),
            }
            log_event(f'\033[36m[ARQ Admin Actioner]\033[0m Отправляем Бульк запрос на фоновое исполнение | action: \033[31m{action}\033[0m; node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            job = await arq.enqueue_job(
                'bulk_delete_users_from_single_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                *action_script_custom_params[action],
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['flatten_json_users_key'],
                vnode['flatten_user_identifier_key'],
            )
            log_event(f'\033[36m[ARQ Admin Actioner]\033[0m Фоновая задача запущена | action: \033[31m{action}\033[0m; node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    "Размеренная обработка"
    await asyncio.gather(*[worker(node) for node in sub_nodes if len(node['users']) > 0])
