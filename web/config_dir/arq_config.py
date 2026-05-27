from datetime import datetime
from decimal import Decimal
from uuid import UUID

import orjson
from aiohttp import ClientSession
from arq.cron import cron
from asyncpg import create_pool, Record

from web.config_dir.config import env, pool_settings, get_arq_redis_settings
from web.utils.arq_logger_config import log_event

from web.arq_tasks.cron_tasks import run_rT_cleaner, traffic_sync_scheduler
from web.arq_tasks.metrics_collector.metrics_tasks import collect_traffic_metrics



async def startup(ctx: dict):
    log_event('[ARQ Worker] Инициализация ресурсов...', level='WARNING')
    
    "PostgreSQL пул"
    ctx['pg_pool'] = await create_pool(**pool_settings)
    
    "AioHttp сессия для запросов к нодам"
    ctx['aio_http'] = ClientSession()

    log_event('[ARQ Worker] Инициализация завершена!', level='WARNING')


async def shutdown(ctx: dict):
    log_event('[ARQ Worker] Остановка воркера, закрытие ресурсов...', level='WARNING')
    
    if 'pg_pool' in ctx:
        await ctx['pg_pool'].close()

    if 'aio_http' in ctx:
        await ctx['aio_http'].close()

    log_event('[ARQ Worker] Остановка завершена!', level='WARNING')


def custom_json_encoder(obj):
    if isinstance(obj, Record):
        return dict(obj)  # Превращаем asyncpg.Record в обычный dict
    if isinstance(obj, (datetime, UUID)):
        return obj.isoformat()  # Даты и UUID переводим в строки
    if isinstance(obj, Decimal):
        return float(obj)  # Десятичные дроби в float
    raise TypeError(f"Type {type(obj)} not serializable")

def arq_serializer(data):
    return orjson.dumps(data, default=custom_json_encoder)

def arq_deserializer(b):
    return orjson.loads(b)


class WorkerSettings:
    """Настройки ARQ воркера"""
    redis_settings = get_arq_redis_settings()

    serializer = arq_serializer
    deserializer = arq_deserializer

    # Импорты задач
    functions = [
        run_rT_cleaner,
        traffic_sync_scheduler,
        collect_traffic_metrics,
    ]
    
    # Cron задачи
    cron_jobs = [
        # Очистка просроченных refresh токенов (13 и 28 числа в 01:02)
        cron(run_rT_cleaner, day={13, 28}, hour=1, minute=2, unique=True),
        # Синхронизация трафика (каждые 5 минут)
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
    queue_name = 'arq:queue'
