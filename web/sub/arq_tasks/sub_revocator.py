from arq import ArqRedis

from web.sub.anything import CoreProtoActions
from web.sub.arq_tasks.depends_fabric import pg_sql_dep, arq_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.data.postgres import PgSql


@pg_sql_dep
@arq_dep
async def revoke_sub_plan_by_expire(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    log_event('\033[33m[ARQ]\033[0m "Срок действия подписки истёк. Крона по удалению пользователей из ядер протоколов')
    expired_users = await db.users_subs.get_expired_subs()
    if not expired_users:
        log_event('\033[32m[ARQ]\033[0m Нет истёкших подписок. Idle')
        return {'success': True, 'message': 'Нет просроченных подписок'}

    log_event(f'Крона по удалению пользователей из ядер протоколов | expired_users: \033[31m{len(expired_users)}\033[0m')

    user_uuids, user_tg_names, order_ids, sub_node_ids = zip(*expired_users.values())
    sub_nodes = await db.sub.users_on_core_proto_action(user_uuids, user_tg_names, order_ids, sub_node_ids)
    log_event(f'\033[33m[ARQ]\033[0m Всего операций для удаления с нод | total_delete: \033[31m{len(sub_nodes)}\033[0m', level='WARNING')
    job = await arq.enqueue_job(
        'action_on_core_proto_by_sub_plan', user_info['uuid'], user_info['tg_username'], sub_nodes, CoreProtoActions.word_delete
    )
