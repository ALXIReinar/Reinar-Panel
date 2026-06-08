import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from starlette.requests import Request

from web.config_dir.config import redis_settings
from web.data.postgres import PgSqlDep
from web.utils.logger_config import log_event


@asynccontextmanager
async def get_redis_connection():
    redis = Redis(**redis_settings)
    try:
        yield redis
    finally:
        await redis.aclose()

async def redis_pool(request: Request) -> Redis:
    return request.app.state.redis

RedisDep = Annotated[Redis, Depends(redis_pool)]



class CommandWhitelistCache:
    """Кэш белого списка команд в Redis"""

    whitelist_key = "wh_list_commands"
    whitelist_mode = None

    @classmethod
    async def get_base_whitelist(cls, redis: Redis) -> list[str]:
        """
        Получить базовый белый список команд из Redis

        Если кэш пуст, возвращает пустой список (нужно загрузить из БД)
        """
        try:
            cached = await redis.get(cls.whitelist_key)
            if cached is not None:
                return json.loads(cached)
            return []
        except Exception as e:
            log_event(f"Ошибка чтения whitelist из Redis: {e}", level="ERROR")
            return []


    @classmethod
    async def set_base_whitelist(cls, redis: Redis, db: PgSqlDep) -> bool:
        try:
            base_commands = await db.whitelist_cmd.get_all()
            base_list = [row['command'] for row in base_commands]

            "On/Off Whitelist"
            if len(base_list) == 0:
                cls.whitelist_mode = False
            else:
                cls.whitelist_mode = True

            await redis.set(cls.whitelist_key, json.dumps(base_list))

            log_event(f"whitelist сохранён в Redis: {len(base_list)} команд")
            return True

        except Exception as e:
            log_event(f"Ошибка сохранения базового whitelist в Redis: {e}", level="ERROR")
            return False


    @classmethod
    async def flush_whitelist(cls, redis: Redis):
        await redis.delete(cls.whitelist_key)

    @classmethod
    async def is_whitelisted(cls, command: str, redis: Redis, db) -> bool:
        """"""
        "Проверка если действует whitelist"
        if cls.whitelist_mode:
            "Заполняем список, если был удалён"
            whitelist = await CommandWhitelistCache.get_base_whitelist(redis)
            if not whitelist:
                whitelist = await CommandWhitelistCache.set_base_whitelist(redis, db)

            "Повторная проверка, если обновление списка выключило whitelist"
            return cls.whitelist_mode or (command in whitelist)

        return True