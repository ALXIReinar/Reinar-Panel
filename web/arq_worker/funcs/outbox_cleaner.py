import asyncio

from arq import ArqRedis

from web.arq_worker.config import env
from web.arq_worker.data.postgres import PgSql
from web.arq_worker.depends_fabric import pg_sql_dep, arq_dep
from web.arq_worker.utils.anything import CoreProtoActions
from web.arq_worker.utils.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
async def retry_stuck_core_proto_actions(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    """Выполняем один SQL-запрос. БД берет на себя N+1 и группировку."""
    log_event('\033[35m[ARQ Cron]\033[0m Крона залипших операций', level='WARNING')

    # За один round-trip обновляем записи и получаем структуру вместе с нодами
    stuck_actions = await db.outbox.get_stuck_actions_by_chronology()

    "Выход, если нечего ретраить"
    if not stuck_actions:
        return {'success': True, 'message': 'Нет залипших операций', 'stuck_len': 0}

    sem = asyncio.Semaphore(env.action_on_core_proto_limit)

    async def enqueue_worker(vnode):
        """"""
        "1. СХЛОПЫВАНИЕ СОСТОЯНИЙ (State Compaction)"
        final_states = {}
        for ev in vnode.get('events_timeline', []):
            sub_id = ev['user_sub_id']
            if sub_id not in final_states:
                final_states[sub_id] = {
                    'uuid': ev['uuid'],
                    'user_sub_id': sub_id,
                    'operation': ev['operation'],
                    'event_id': []  # <-- Сюда будем складывать ВСЕ ID событий юзера
                }
            # Перезаписываем операцию на самую свежую (т.к. БД отсортировала по ASC)
            final_states[sub_id]['operation'] = ev['operation']
            # Сохраняем event_id, чтобы воркер закрыл и этот ack тоже
            final_states[sub_id]['event_id'].append(ev['event_id'])

        "2. Разделяем юзеров на две независимые пачки"
        add_batch = [u for u in final_states.values() if u['operation'] == CoreProtoActions.add]
        delete_batch = [u for u in final_states.values() if u['operation'] == CoreProtoActions.delete]

        async with sem:
            "4. Вспомогательная функция для постановки задачи в ARQ"
            async def dispatch_job(batch, operation):
                if not batch:
                    return  # Если пачка пустая, ничего не делаем

                action_pack = {
                    CoreProtoActions.delete: (
                        vnode['api_bulk_delete_user_script'],
                        vnode['bulk_delete_script_custom_params'],
                        CoreProtoActions.delete,
                    ),
                    CoreProtoActions.add: (
                        vnode['api_bulk_add_user_script'],
                        vnode['bulk_add_script_custom_params'],
                        CoreProtoActions.add,
                    ),
                }

                "Отправляем chain task на каждую ноду для бульк удаления"
                log_event(f'\033[31m[ARQ Cron]\033[0m Отправляем Бульк запрос на \033[33m{CoreProtoActions.id2name[operation]}\033[0m | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
                job = await arq.enqueue_job(
                    'bulk_action_users_by_node',
                    vnode['node_proto_id'],
                    vnode['private_ip'],
                    vnode['api_port'],
                    vnode['metrics_port'],
                    vnode['proto_python_lib'],
                    *action_pack[operation],
                    batch,
                    vnode['reload_core_command'],
                    vnode['config_path'],
                    vnode['user_injectors'],
                    vnode['required_user_data_obj'],
                    vnode['constant_user_data_obj'],
                    vnode['constant_node_data_obj'],
                )
                log_event(f'\033[35m[ARQ Cron]\033[0m Ретрай операции в vpn-ядро протокола | node_proto_id: \033[32m{vnode['node_proto_id']}\033[0m; operation: \033[36m{operation}\033[0m', job_id=job.job_id)
            "3. Кидаем на одну ноду 2 пачки"
            await dispatch_job(add_batch, CoreProtoActions.add)
            await dispatch_job(delete_batch, CoreProtoActions.delete)

    "Параллельный запуск"
    await asyncio.gather(*(enqueue_worker(action) for action in stuck_actions))

    log_event(f'\033[32m[ARQ Cron]\033[0m Перезапуск залипших операций прошёл успешно | stuck_len: \033[33m{len(stuck_actions)}\033[0m')
    return {'success': True, 'message': 'Чистка зависших операций', 'stuck_len': len(stuck_actions)}
