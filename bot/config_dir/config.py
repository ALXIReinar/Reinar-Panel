import logging
import os
from functools import lru_cache
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


from bot.config_dir.env_modes import AppMode, APP_MODE_CONFIG
from bot.config_dir.msg_templates import MessageTemplates

env_files = (
    os.getenv('ENV_FILE') or
    'bot/.env.bot.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | app_mode: \033[33m{os.getenv('APP_MODE')}\033[0m')

WORKDIR = Path(__file__).resolve().parent.parent

"Создаём директорию для логов"
LOG_DIR = WORKDIR / 'bot_logs'
LOG_DIR.mkdir(exist_ok=True, parents=True)


class Settings(BaseSettings):
    # Message templates (загружаются из ENV напрямую)
    message_start: str = Field(description='Ответ бота на команду /start')
    message_profile: str
    message_help: str
    message_about: str
    message_subscriptions_shop_intro: str
    message_subscriptions_shop_extent: str
    message_user_profile_subs_intro: str
    message_subscriptions_user_extent: str
    message_subscriptions_offers_intro: str
    message_subscriptions_offers_extent: str
    message_pay_window: str
    
    redis_password: str
    redis_max_connections: int
    redis_host: str
    redis_port: int

    bot_token: str
    admin_tg_id: int
    sub_service_url: str = Field(max_length=255)

    app_mode: AppMode
    service_name: str = 'tg-bot-service'
    user_req_limit: int
    user_req_window_seconds: int
    shop_sub_plans_ttl: int

    model_config = SettingsConfigDict(extra='allow')
    
    @property
    def message_templates(self) -> MessageTemplates:
        """Геттер для обратной совместимости с env.message_templates"""
        return MessageTemplates(
            message_start=self.message_start,
            message_profile=self.message_profile,
            message_about=self.message_about,
            message_subscriptions_shop_intro=self.message_subscriptions_shop_intro,
            message_subscriptions_shop_extent=self.message_subscriptions_shop_extent,
            message_user_profile_subs_intro=self.message_user_profile_subs_intro,
            message_subscriptions_user_extent=self.message_subscriptions_user_extent,
            message_subscriptions_offers_intro=self.message_subscriptions_offers_intro,
            message_subscriptions_offers_extent=self.message_subscriptions_offers_extent,
            message_pay_window=self.message_pay_window,
            message_help=self.message_help,
        )

@lru_cache
def get_env_vars():
    return Settings()
env = get_env_vars()


"Bot"
bot = Bot(token=env.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

"Redis"
def get_redis_settings(envs: Settings):
    cfg = APP_MODE_CONFIG[envs.app_mode]

    redis_conf = {
        'host': getattr(envs, cfg['redis_host']),
        'port': getattr(envs, cfg['redis_port']),
        'max_connections': env.redis_max_connections
    }
    if envs.app_mode != 'local':
        redis_conf['password'] = envs.redis_password


    return redis_conf

redis_settings = get_redis_settings(env)