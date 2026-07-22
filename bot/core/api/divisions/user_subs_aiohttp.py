from aiohttp import ClientSession, ClientError

from bot.core.utils.anything import SubServiceUris


class UserSubsAioHttp:
    def __init__(self, session: ClientSession):
        self.session = session

    async def get_payment_link(self, tg_id, sub_plan_id, cost, ttl_days: int):
        cost = f'{cost // 100}.00'
        try:
            async with self.session.post(
                    SubServiceUris.get_payment_link,
                    json={'tg_id': tg_id, 'sub_plan_id': sub_plan_id, 'cost': cost, 'ttl_days': ttl_days}
            ) as resp:
                resp.raise_for_status()
                resp_json = await resp.json()

                return True, resp_json['payment_url']

        except ClientError as e:
            return False, repr(e)