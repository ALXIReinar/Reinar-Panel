from typing import Any

from aiohttp import ClientError, ClientSession

from bot.config_dir.logger_config import log_event


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
                log_event(f'[Base Http Client] Ответ от Апи | status: \033[31m{resp.status}\033[0m; method: \033[34m{method}\033[0m; url: \033[35m{url}\033[0m')

                if raise_for_status:
                    resp.raise_for_status()

                if release_request:
                    log_event(f'[Base Http Client] Сбросили http conn | method: \033[34m{method}\033[0m; url: \033[35m{url}\033[0m', level='WARNING')
                    resp.release()
                    return True, None

                data = await resp.json()
                log_event(f'[Base Http Client] Json тело ответа | json: \033[34m{str(data)[:150]}\033[0m; method: \033[34m{method}\033[0m; url: \033[35m{url}\033[0m')
                return True, data

        except (ClientError, Exception) as e:
            # Ошибки сети, таймауты, DNS, сервис упал/не отвечает
            log_event(f'Ошибка на Sub-Service | err: \033[31m{repr(e)}\033[0m; method: \033[34m{method}\033[0m; url: \033[36m{url}\033[0m; kwargs: {kwargs}')
            return False, e

