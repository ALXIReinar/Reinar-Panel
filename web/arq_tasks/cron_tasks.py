from arq.connections import ArqRedis

from web.arq_tasks.depends_fabric import pg_sql_dep, arq_dep
from web.data.postgres import PgSql
from web.utils.arq_logger_config import log_event



@pg_sql_dep
async def run_rT_cleaner(ctx: dict, db: PgSql = None):
    """
    Очистка просроченных refresh токенов
    Запускается: 13 и 28 числа каждого месяца в 01:02
    """
    log_event('\033[36m[ARQ]\033[0m Очистка refresh токенов', level='WARNING')
    await db.auth.slam_refresh_tokens()
    log_event('\033[36m[ARQ]\033[0m Истёкшие сессии удалены', level='WARNING')
    return {'success': True, 'message': 'Refresh tokens cleaned'}



@pg_sql_dep
@arq_dep
async def traffic_sync_scheduler(ctx: dict, db: PgSql = None, redis: ArqRedis = None):
    """
    Крона синхронизации трафика
    Запускается: каждые 5 минут
    Запускает Task Chaining: находит ноды для сбора трафика, отправляет их далее в Arq
    """
    log_event('\033[36m[ARQ]\033[0m Планировщик синхронизации трафика запущен')
    
    "Получаем список АКТИВНЫХ и ВИДИМЫХ для пользователя нод, с которых можно собрать метрики(есть metrics_port)"
    nodes = await db.nodes_protocols.get_all_nodes_for_metrics()

    if not nodes:
        log_event('\033[36m[ARQ]\033[0m Нет активных нод для сбора метрик', level='ERROR')
        return {'success': True, 'nodes_count': 0}

    "Ставим задачу сбора метрик в очередь. Task Chaining"
    job = await redis.enqueue_job('collect_traffic_metrics', nodes)
    log_event(f'\033[36m[ARQ]\033[0m Найдены ноды для сбора метрик. Задача поставлена в очередь | job_id: \033[33m{job.job_id}\033[0m; nodes_count: \033[32m{len(nodes)}\033[0m')
    return {'success': True, 'job_id': job.job_id, 'nodes_count': len(nodes)}

