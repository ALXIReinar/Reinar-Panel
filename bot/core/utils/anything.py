from dataclasses import dataclass
from typing import Literal

from bot.config_dir.config import env


class RedisKeys:
    @staticmethod
    def rate_limit(tg_id: str | int) -> str:
        return f'{env.app_mode}:{env.service_name}:rate_limit:user:tg_id={tg_id}:v1'

@dataclass
class SubServiceUris:
    # users division
    add_tg_user: str = '/api/v1/tg-bot/users/add'

    # user_subs division
    get_user_subs_all: str = '/api/v1/tg-bot/users/subs/all'

    # sub_plans division
    get_sub_plans_all: str = '/api/v1/tg-bot/sub_plans/all'
    get_payment_link: str = '/api/v1/robokassa/get_pay_link'
