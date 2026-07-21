from aiohttp import ClientSession

from bot.core.api.divisions.users_aiohttp import UsersAioHttp


class ApiServerConn:
    def __init__(self, aio_http_session: ClientSession):
        self.aio_http_session = aio_http_session
        self.users = UsersAioHttp(aio_http_session)

