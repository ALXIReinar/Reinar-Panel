from typing import Literal

from arq import ArqRedis

from web.arq_worker.depends_fabric import arq_dep, pg_sql_dep
from web.arq_worker.funcs.pounted_bulk.handlers import group_users_by_node_proto_id
from web.arq_worker.data.postgres import PgSql
from web.arq_worker.utils.arq_logger_config import log_event


@arq_dep
@pg_sql_dep
async def pointed_bulk_action(ctx: dict, outbox_event_ids: list[int], action: Literal['add', 'delete'], db: PgSql = None, arq: ArqRedis = None):
    if not outbox_event_ids:
        return {'success': False, 'message': 'Нет оутбоксов для вставки пользователей!'}

    log_event(f'\033[33m[ARQ Pointer Actioner]\033[0m Точечная бульк операция на нодах | action: \033[32m{action}\033[0m', level='WARNING')
    nodes_meta_wo_group_by = await db.core_proto_bulk.get_users_by_sub_plan(outbox_event_ids, action)
    nodes_meta = group_users_by_node_proto_id(nodes_meta_wo_group_by)


    users_to_action = sum(len(vnode['users']) for vnode in nodes_meta)
    log_event(f'\033[33m[ARQ Pointer Actioner]\033[0m Статистика перед запуском | total_operations: \033[31m{users_to_action}\033[0m', level='WARNING')


    "Отправляем chain task на каждую ноду для бульк добавления в ядра"
    for vnode in nodes_meta:
        if len(vnode['users']) > 0:
            log_event(f'\033[33m[ARQ Pointer Actioner]\033[0m Отправляем Бульк запрос на фоновое \033[31m{action}\033[0m пользователей в ядра | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')

            "Что нужно делать: вставку или удаление"
            arq_args = {
                'add': (
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
                ),
                'delete': (
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
            }
            arq_func = {'add': 'bulk_add_users_into_single_node', 'delete': 'bulk_delete_users_from_single_node'}
            job = await arq.enqueue_job(arq_func[action], *arq_args[action])

            log_event(f'\033[33m[Pointer Actioner]\033[0m Фоновая задача запущена, бульк-\033[31m{action}\033[0m | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    return {'success': True, 'message': 'Бульк запросы полетели'}
