import asyncio

from arq import ArqRedis
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
    stuck_actions = await db.outbox.get_stuck_actions_with_nodes()

    "Выход, если нечего ретраить"
    if not stuck_actions:
        return {'success': True, 'message': 'Нет залипших операций', 'stuck_len': 0}

    async def enqueue_worker(action_info):
        sub_nodes_serialized = [dict(node) for node in action_info['sub_nodes']]

        if sub_nodes_serialized:
            job = await arq.enqueue_job(
                'action_on_core_proto_by_sub_plan',
                action_info['user_uuid'],
                action_info['user_sub_id'],
                sub_nodes_serialized,
                CoreProtoActions.id2name[action_info['operation']],
            )
            log_event(f'\033[35m[ARQ Cron]\033[0m Ретрай операции в ядро протокола | user_sub_id: \033[31m{action_info["user_sub_id"]}\033[0m; operation: \033[36m{action_info["operation"]}\033[0m', job_id=job.job_id)

    "Параллельный запуск"
    await asyncio.gather(*(enqueue_worker(action) for action in stuck_actions))

    log_event(f'\033[32m[ARQ Cron]\033[0m Перезапуск залипших операций прошёл успешно | stuck_len: \033[33m{len(stuck_actions)}\033[0m')
    return {'success': True, 'message': 'Чистка зависших операций', 'stuck_len': len(stuck_actions)}