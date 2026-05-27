from aiohttp import ClientSession
from arq import cron
from asyncpg import create_pool

from web.sub.arq_tasks.outbox_cleaner import retry_stuck_core_proto_actions
from web.sub.arq_tasks.sub_revocator import bulk_delete_users_from_single_node, revoke_sub_plan_by_expire
from web.sub.config_dir.config import env, pool_settings, get_arq_redis_settings
from web.sub.arq_tasks.action_on_user_core_proto import action_on_core_proto_by_sub_plan
from web.sub.config_dir.arq_logger_config import log_event




async def startup(ctx: dict):
    log_event('[ARQ Worker] Инициализация ресурсов...', level='WARNING')
    
    "PostgreSQL пул"
    ctx['pg_pool'] = await create_pool(**pool_settings)
    
    "AioHttp сессия для запросов к нодам"
    ctx['aio_http'] = ClientSession()

    "ArqRedis"
    ctx['arq_redis'] = get_arq_redis_settings()

    log_event('[ARQ Worker] Инициализация завершена!', level='WARNING')


async def shutdown(ctx: dict):
    log_event('[ARQ Worker] Остановка воркера, закрытие ресурсов...', level='WARNING')

    if 'pg_pool' in ctx:
        await ctx['pg_pool'].close()


    if 'aio_http' in ctx:
        await ctx['aio_http'].close()

    if 'arq_redis' in ctx:
        await ctx['arq_redis'].close()

    log_event('[ARQ Worker] Остановка завершена!', level='WARNING')



class WorkerSettings:
    """Настройки ARQ воркера"""
    redis_settings = get_arq_redis_settings()

    # Импорты задач
    functions = [
        action_on_core_proto_by_sub_plan,
        bulk_delete_users_from_single_node,
    ]
    
    # Cron задачи
    cron_jobs = [
        cron(revoke_sub_plan_by_expire, hour={0}, minute={0}, unique=True),
        cron(retry_stuck_core_proto_actions, hour={3}, minute={0}, unique=True),
    ]
    
    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown
    
    # Настройки производительности
    max_jobs = env.arq_max_jobs
    job_timeout = env.arq_job_timeout
    
    # Логирование
    log_results = True
    
    # Имя очереди
    queue_name = 'arq:queue'
