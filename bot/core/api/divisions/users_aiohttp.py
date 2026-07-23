from aiohttp import ClientSession

from bot.config_dir.logger_config import log_event
from bot.core.api.aiohttp_conn import BaseAioHTTPClient
from bot.core.utils.anything import SubServiceUris


class UsersAioHttp(BaseAioHTTPClient):
    def __init__(self, session: ClientSession):
        super().__init__(session)

    async def save_user(self, tg_id: int, tg_username: str, return_data: bool):
        """
        Обращение на Api Server

        **return_data** - отдаёт данные о пользователе. Ответ идентичен методу get_user_info()
        """
        log_event(f'Отправили запрос на сохранение пользователя Telegram | tg_id: \033[33m{tg_id}\033[0m; tg_username: \033[34m{tg_username}\033[0m; return_data: \033[32m{return_data}\033[0m')
        ok, data = await self._request(
            'POST',
            SubServiceUris.add_tg_user,
            release_request=return_data,
            json={'tg_id': tg_id, 'tg_username': tg_username, 'return_data': return_data}
        )

        if not ok:
            data = {}
        return ok, data



    async def get_user_info(self, tg_id: int, tg_username: str):
        ...