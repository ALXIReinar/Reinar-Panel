from web.arq_tasks.depends_fabric import pg_sql_dep
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

