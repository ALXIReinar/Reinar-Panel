from aiohttp import ClientSession

from bot.core.api.divisions.user_subs_aiohttp import UserSubsAioHttp
from bot.core.api.divisions.users_aiohttp import UsersAioHttp


class SubServiceConn:
    def __init__(self, aio_http_session: ClientSession):
        self.aio_http_session = aio_http_session
        self.users = UsersAioHttp(aio_http_session)
        self.user_subs = UserSubsAioHttp(aio_http_session)

