import asyncio

from arq import ArqRedis
from asyncpg import Pool

from web.sub.anything import CoreProtoActions
from web.sub.arq_tasks.depends_fabric import pg_sql_dep, arq_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSql

@pg_sql_dep
@arq_dep
async def retry_stuck_core_proto_actions(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    """Прокидываем Индивидуальное соединение каждому воркеру"""
    log_event('\033[35m[ARQ Cron]\033[0m Крона залипших операций', level='WARNING')

    stuck_actions = await db.users_subs.get_stuck_actions()
    sem = asyncio.Semaphore(env.action_on_core_proto_limit)

    async def worker(action_info, db_pool: Pool):
        """Каждый воркер открывает своё соединение, чтобы не инициировать Race Condition"""
        async with (sem):
            "Находим ноды по подписке, ретраим"
            async with db_pool.acquire() as conn:
                sub_nodes = await PgSql(conn).sub.get_nodes_to_core_proto_action(action_info['order_id'])
            if len(sub_nodes) > 0:
                # Преобразуем asyncpg.Record в dict для сериализации
                sub_nodes_serializable = [dict(node) for node in sub_nodes]
                
                job = await arq.enqueue_job(
                    'action_on_core_proto_by_sub_plan',
                    action_info['user_uuid'],
                    action_info['tg_username'],
                    sub_nodes_serializable,
                    CoreProtoActions.id2name[action_info['operation']],
                )
                log_event(f'\033[35m[ARQ Cron]\033[0m Ретрай операции в ядро протокола | order_id: \033[31m{action_info['order_id']}\033[0m; operation: \033[36m{action_info['operation']}\033[0m', job_id=job.job_id)

    "Параллельный запуск"
    await asyncio.gather(*(worker(node, ctx['pg_pool']) for node in stuck_actions))
    log_event(f'\033[32m[ARQ Cron]\033[0m Перезапуск залипших операций прошёл успешно | stuck_len: \033[33m{len(stuck_actions)}\033[0m ')
    return {'success': True, 'message': 'Чистка зависших операций', 'stuck_len': len(stuck_actions)}
