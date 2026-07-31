import logging
from aiohttp import ClientSession
from arq import cron, create_pool as create_arq_pool
from asyncpg import create_pool

from web.arq_worker.config import pool_settings, get_arq_redis_settings, get_arq_worker_settings, env
from web.arq_worker.funcs.admin_actions import admin_request_bulk_action_users
from web.arq_worker.funcs.cron_tasks import run_rT_cleaner
from web.arq_worker.funcs.metrics_collector import collect_traffic_metrics, bulk_delete_by_traffic_limit, traffic_sync_scheduler
from web.arq_worker.funcs.outbox_cleaner import retry_stuck_core_proto_actions
from web.arq_worker.funcs.pounted_bulk.pointed_bulk_actions import pointed_bulk_action
from web.arq_worker.funcs.sub_revocator import bulk_delete_users_from_single_node, revoke_sub_plan_by_expire
from web.arq_worker.funcs.tg_sub_sender import send_sub_link_tg_user
from web.arq_worker.funcs.traffic_reset import reset_day_user_traffic, bulk_add_users_into_single_node
from web.arq_worker.funcs.action_on_user_core_proto import action_on_core_proto_by_sub_plan



async def startup(ctx: dict):
    logging.warning('[ARQ Worker] Инициализация ресурсов...')
    
    "PostgreSQL пул"
    ctx['pg_pool'] = await create_pool(**pool_settings)
    
    "AioHttp сессия для запросов к нодам"
    ctx['aio_http'] = ClientSession()

    "ArqRedis"
    ctx['arq_redis'] = await create_arq_pool(get_arq_redis_settings(), **get_arq_worker_settings())

    logging.warning('[ARQ Worker] Инициализация завершена!')


async def shutdown(ctx: dict):
    logging.warning('[ARQ Worker] Остановка воркера, закрытие ресурсов...')

    if 'pg_pool' in ctx:
        await ctx['pg_pool'].close()


    if 'aio_http' in ctx:
        await ctx['aio_http'].close()

    if 'arq_redis' in ctx:
        await ctx['arq_redis'].close()

    logging.warning('[ARQ Worker] Остановка завершена!')



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
        send_sub_link_tg_user,
        pointed_bulk_action,
    ]
    
    # Cron задачи
    cron_jobs = [
        # Истёкшие подписки
        cron(revoke_sub_plan_by_expire, hour={0}, minute={0}, unique=True),
        # cron(revoke_sub_plan_by_expire, minute=set(i for i in range(61) if i % 2 != 0), unique=True),

        # Обнуляем трафик, возвращаем пользователей в ядра
        cron(reset_day_user_traffic, hour={0}, minute={8}, unique=True),
        # cron(reset_day_user_traffic, minute=set(i for i in range(61) if i % 2 == 0), unique=True),

        # Ретраим Outbox залипшие операции
        cron(retry_stuck_core_proto_actions, hour={3}, minute={0}, unique=True),
        # cron(retry_stuck_core_proto_actions, minute=set(i for i in range(61) if i % 2 != 0), unique=True),

        # Сбор трафика, удаление из ядер протоколов
        cron(traffic_sync_scheduler, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}, unique=True),

        # Очистка просроченных refresh токенов (13 и 28 числа в 01:02)
        cron(run_rT_cleaner, day={13, 28}, hour=1, minute=2, unique=True),
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
