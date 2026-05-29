from web.sub.arq_tasks.depends_fabric import pg_sql_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.data.postgres import PgSql


@pg_sql_dep
async def reset_day_user_traffic(ctx: dict, db: PgSql):
    log_event('\033[35m[ARQ Cron]\033[0m Обнуление трафика пользователей за день', level='WARNING')
    await db.users_subs.reset_user_traffic_per_day()
    log_event('\033[32m[ARQ Cron]\033[0m Успешно обнулили трафик пользователей')
    return {'success': True, 'message': 'Трафик пользователей обнулён'}