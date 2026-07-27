from aiohttp import ClientSession

from bot.core.api.base_aio_http_client import BaseAioHTTPClient
from bot.core.utils.anything import SubServiceUris


class UserSubsAioHttp(BaseAioHTTPClient):
    def __init__(self, session: ClientSession):
        super().__init__(session)

    async def all(self, tg_id: int):
        ok, data = await self._request(
            'GET',
            SubServiceUris.get_user_subs_all, params={'tg_id': tg_id}
        )
        if not ok:
            return False, []

        return True, data['user_subs']