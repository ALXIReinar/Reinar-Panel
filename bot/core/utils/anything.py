from dataclasses import dataclass
from bot.config_dir.config import env


admin_commands = {
    '/flush_shop_cache', # Очистка кэша тарифных планов магазина
    '/reset_req_limit', # сброс счётчика запросов на пользователя
}

class RedisKeys:
    @staticmethod
    def rate_limit(tg_id: str | int) -> str:
        return f'{env.app_mode}:{env.service_name}:rate_limit:user:tg_id={tg_id}:v1'

    shop_sub_plans: str = f'{env.app_mode}:{env.service_name}:shop_sub_plans:v1'

@dataclass
class SubServiceUris:
    # users division
    add_tg_user: str = '/api/v1/tg-bot/users/add'
    get_user_profile: str = '/api/v1/tg-bot/users/get'

    # user_subs division
    get_user_subs_all: str = '/api/v1/tg-bot/users/subs/all'

    # sub_plans division
    get_sub_plans_all: str = '/api/v1/tg-bot/sub_plans/all'
    get_payment_link: str = '/api/v1/robokassa/get_pay_link'
