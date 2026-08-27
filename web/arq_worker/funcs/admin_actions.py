import asyncio
from typing import Literal

from arq import ArqRedis

from web.arq_worker.config import env
from web.arq_worker.data.postgres import PgSql
from web.arq_worker.depends_fabric import pg_sql_dep, arq_dep
from web.arq_worker.utils.anything import CoreProtoActions
from web.arq_worker.utils.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
async def admin_request_bulk_action_users(ctx: dict, action: Literal['delete', 'add'] | CoreProtoActions, outbox_event_ids: list[int], db: PgSql = None, arq: ArqRedis = None):
    sub_nodes = await db.core_proto_bulk.get_meta_for_bulk(outbox_event_ids)
    
    sem = asyncio.Semaphore(env.action_on_core_proto_limit)

    async def worker(vnode):
        async with (sem):
            "Отправляем chain task на каждую ноду для бульк удаления"
            action_script_custom_params = {
                'delete': (vnode['api_bulk_delete_user_script'], vnode['bulk_delete_script_custom_params'], CoreProtoActions.delete),
                'add': (vnode['api_bulk_add_user_script'], vnode['bulk_add_script_custom_params'], CoreProtoActions.add),
            }
            log_event(f'\033[36m[ARQ Admin Actioner]\033[0m Отправляем Бульк запрос на фоновое исполнение | action: \033[31m{action}\033[0m; node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
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
                vnode['constant_node_data_obj'],
                vnode['json2config_script'],
                vnode['config2json_script'],
                vnode['conf_converter_libs'],
            )
            log_event(f'\033[36m[ARQ Admin Actioner]\033[0m Фоновая задача запущена | action: \033[31m{action}\033[0m; node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    "Размеренная обработка"
    await asyncio.gather(*[worker(node) for node in sub_nodes if len(node['users']) > 0])
