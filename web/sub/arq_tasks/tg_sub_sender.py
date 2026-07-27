from aiohttp import ClientSession

from web.sub.anything import TgBotApi
from web.sub.arq_tasks.depends_fabric import pg_sql_dep, aiohttp_dep
from web.sub.config_dir.arq_logger_config import log_event
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSql


@pg_sql_dep
@aiohttp_dep
async def send_sub_link_tg_user(ctx: dict, user_id: int, user_sub_id: int, db: PgSql = None, aio_http: ClientSession = None):
    user = await db.sub.get_user_tg_notify(user_id, user_sub_id)

    try:
        async with aio_http.post(
            TgBotApi.send_message.format(env.tg_bot_token),
            json={
                'chat_id': user['tg_id'],
                'parse_mode': 'HTML',
                'text': f'🚀Оплата прошла успешно!\n🌀Ссылка для подключения в <b>Happ</b>\n\n<code>{env.domain}/sub/{user['b64_id']}</code>',
            }
        ) as resp:
            log_event(f'\033[34m[Tg Notify]\033[0m Отправили ссылку на подписку пользователю | status_code: {resp.status}')
            resp.release()
    except Exception as e:
        log_event(f'Не удалось подключиться к апи телеграм | err: \033[31m{repr(e)}\033[0m')

    return {'success': True, 'message': 'Пользователь в тг уведомлён', 'status_code': resp.status}
