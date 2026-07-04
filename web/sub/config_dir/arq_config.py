from aiohttp import ClientSession
from arq import cron, create_pool as create_arq_pool
from asyncpg import create_pool

from web.sub.arq_tasks.admin_actions import admin_request_bulk_action_users
from web.sub.arq_tasks.metrics_collector import traffic_sync_scheduler, collect_traffic_metrics, \
    bulk_delete_by_traffic_limit
from web.sub.arq_tasks.outbox_cleaner import retry_stuck_core_proto_actions
from web.sub.arq_tasks.sub_revocator import bulk_delete_users_from_single_node, revoke_sub_plan_by_expire
from web.sub.arq_tasks.traffic_reset import reset_day_user_traffic, bulk_add_users_into_single_node
from web.sub.config_dir.config import env, pool_settings, get_arq_redis_settings, get_arq_worker_settings
from web.sub.arq_tasks.action_on_user_core_proto import action_on_core_proto_by_sub_plan
from web.sub.config_dir.arq_logger_config import log_event




async def startup(ctx: dict):
    log_event('[ARQ Worker] Инициализация ресурсов...', level='WARNING')
    
    "PostgreSQL пул"
    ctx['pg_pool'] = await create_pool(**pool_settings)
    
    "AioHttp сессия для запросов к нодам"
    ctx['aio_http'] = ClientSession()

    "ArqRedis"
    ctx['arq_redis'] = await create_arq_pool(get_arq_redis_settings(), **get_arq_worker_settings())

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
        collect_traffic_metrics,
        bulk_delete_by_traffic_limit,

        bulk_add_users_into_single_node,
        bulk_delete_users_from_single_node,

        admin_request_bulk_action_users,
    ]
    
    # Cron задачи
    cron_jobs = [
        # Истёкшие подписки
        cron(revoke_sub_plan_by_expire, hour={0}, minute={0}, unique=True),
        # cron(revoke_sub_plan_by_expire, minute=set(i for i in range(61) if i % 2 == 0), unique=True),

        # Обнуляем трафик, возвращаем пользователей в ядра
        cron(reset_day_user_traffic, hour={0}, minute={8}, unique=True),
        # cron(reset_day_user_traffic, minute=set(i for i in range(61) if i % 2 != 0), unique=True),

        # Ретраим Outbox залипшие операции
        cron(retry_stuck_core_proto_actions, hour={3}, minute={0}, unique=True),
        # cron(retry_stuck_core_proto_actions, minute=set(i for i in range(61) if i % 2 != 0), unique=True),

        # Сбор трафика, удаление из ядер протоколов
        cron(traffic_sync_scheduler, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}, unique=True),

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
    queue_name = env.arq_queue_name
