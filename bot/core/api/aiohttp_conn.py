from typing import Any

from aiohttp import ClientSession, ClientError

from bot.config_dir.logger_config import log_event
from bot.core.api.divisions.sub_plans_aiohttp import SubPlansAioHttp
from bot.core.api.divisions.user_subs_aiohttp import UserSubsAioHttp
from bot.core.api.divisions.users_aiohttp import UsersAioHttp


class SubServiceConn:
    def __init__(self, aio_http_session: ClientSession):
        self.aio_http_session = aio_http_session
        self.users = UsersAioHttp(aio_http_session)
        self.user_subs = UserSubsAioHttp(aio_http_session)
        self.sub_plans = SubPlansAioHttp(aio_http_session)



class BaseAioHTTPClient:
    def __init__(self, aio_http_session: ClientSession):
        self.session = aio_http_session

    async def _request(
            self,
            method: str,
            url: str,
            raise_for_status: bool = True,
            release_request: bool = False,
            **kwargs
    ) -> tuple[bool, Any]:
        """
        Универсальный метод для выполнения HTTP-запросов.
        Возвращает (True, data) при успехе или (False, human_readable_error) при ошибке.
        """
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                # Генерирует ClientResponseError для статусов >= 400
                if raise_for_status:
                    resp.raise_for_status()

                if release_request:
                    resp.release()
                    return True, None

                data = await resp.json()
                return True, data

        except (ClientError, Exception) as e:
            # Ошибки сети, таймауты, DNS, сервис упал/не отвечает
            log_event(f'Ошибка на Sub-Service | err: \033[31m{repr(e)}\033[0m; method: \033[34m{method}\033[0m; url: \033[36m{url}\033[0m; kwargs: {kwargs}', e)
            return False, e

