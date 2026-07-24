from typing import Any

from aiohttp import ClientSession

from bot.core.api.aiohttp_conn import BaseAioHTTPClient
from bot.core.utils.anything import SubServiceUris

class SubPlansAioHttp(BaseAioHTTPClient):
    def __init__(self, aio_http_session: ClientSession):
        super().__init__(aio_http_session)

    async def all(self):
        ok, data = await self._request('GET', SubServiceUris.get_sub_plans_all)
        if not ok:
            return False, data
        return True, data['sub_plans']

    async def api_get_payment_link(self, tg_id: int, sub_plan_id: int, offer_id: int, description: str):
        ok, data = await self._request(
            "POST",
            SubServiceUris.get_payment_link,
            json={'tg_id': tg_id, 'sub_plan_id': sub_plan_id, 'offer_id': offer_id, 'description': description}
        )
        if not ok:
            return False, data

        return True, data['payment_url']
