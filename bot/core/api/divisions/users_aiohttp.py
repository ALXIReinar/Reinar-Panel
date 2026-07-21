from aiohttp import ClientSession

from bot.config_dir.logger_config import log_event


class UsersAioHttp:
    def __init__(self, session: ClientSession):
        self.session = session

    async def save_user(self, tg_id: int, tg_username: str, return_data: bool):
        """
        Обращение на Api Server

        **return_data** - отдаёт данные о пользователе. Ответ идентичен методу get_user_info(..., preview=True)
        """
        async with self.session.post(
                '/api/v1/telegram/users/add',
                json={'tg_id': tg_id, 'tg_username': tg_username, 'return_data': return_data}
        ) as resp:
            log_event(f'Отправили запрос на сохранение пользователя Telegram | tg_id: \033[33m{tg_id}\033[0m; tg_username: \033[34m{tg_username}\033[0m; return_data: \033[32m{return_data}\033[0m')
            if not return_data:
                resp.release() # не нужен ответ, сброс соединения
                return None

            resp_data = await resp.json()
            return resp_data


    async def get_user_info(self, tg_id: int, tg_username: str, preview: bool):
        ...