from arq import ArqRedis

from web.arq_worker.data.postgres import PgSql
from web.arq_worker.depends_fabric import pg_sql_dep, arq_dep
from web.arq_worker.utils.anything import CoreProtoActions
from web.arq_worker.utils.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
async def reset_day_user_traffic(
        ctx: dict, users: list[dict] | None = None,
        db: PgSql = None,
        arq: ArqRedis = None
):
    """
    Получилось неожиданно удобно. По-правильному эта функция должна называться `execute_bulk_add_by_users` при указании пользователей
    1. По-хорошему ресет трафика должен быть 3-уровневым:
        1. крона тригерится, находит пользователей
        2. ЭТА функция исполняет бульк вставку + чейнит на саму функцию бульк-вставки
        3. bulk_add_users_into_single_node
    А крона должна быть вынесена

    :param ctx:
    :param users:
    :param db:
    :param arq:
    :return:
    """
    log_event(f'\033[35m[ARQ Traffic Reset]\033[0m Обнуление трафика пользователей. \033[34m(Крона, если users = None)\033[0m | users: {users}', level='WARNING')
    if users:
        unlock_users_by_node = await db.traffic_reset.reset_traffic_by_users(users)
    else:
        unlock_users_by_node = await db.traffic_reset.reset_user_traffic_per_day()
    users_to_add = sum(len(vnode['users']) for vnode in unlock_users_by_node)
    log_event(f'\033[32m[ARQ Traffic Reset]\033[0m Крона по возврату пользователей после обнуления трафика | total_adds: \033[31m{users_to_add}\033[0m')

    if not users_to_add:
        log_event('\033[32m[ARQ Traffic Reset]\033[0m Нет пользователей, блокированных по лимиту трафика. Idle')
        return {'success': True, 'message': 'Нет пользователей, блокированных по лимиту трафика'}

    "Отправляем chain task на каждую ноду для бульк добавления в ядра"
    for vnode in unlock_users_by_node:
        if len(vnode['users']) > 0:
            log_event(f'\033[35m[Traffic Reset]\033[0m Отправляем Бульк запрос на фоновое добавление пользователей в ядра | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            job = await arq.enqueue_job(
                'bulk_action_users_by_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                vnode['api_bulk_add_user_script'],
                vnode['bulk_add_script_custom_params'],
                CoreProtoActions.add,
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['user_injectors'],
                vnode['required_user_data_obj'],
                vnode['constant_user_data_obj'],
            )
            log_event(f'\033[35m[Traffic Reset]\033[0m Фоновая задача запущена, бульк-добавление | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    return {'success': True, 'message': 'Трафик пользователей обнулён', 'is_definite_users': bool(users)}
