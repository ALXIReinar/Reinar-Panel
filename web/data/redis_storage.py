from contextlib import asynccontextmanager
from typing import Annotated

import orjson
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
    async def get_base_whitelist(cls, redis: Redis, cmd_only: bool = False) -> list[str]:
        """
        Получить базовый белый список команд из Redis

        Если кэш пуст, возвращает пустой список (нужно загрузить из БД)
        """

        try:
            cached = await redis.get(cls.whitelist_key)
            if cached is not None:
                ids_cmds = orjson.loads(cached)
                if cmd_only:
                    return [id_cmd_active['command'] for id_cmd_active in ids_cmds if id_cmd_active['is_active'] == True]
                return ids_cmds
            return []
        except Exception as e:
            log_event(f"Ошибка чтения whitelist из Redis: {e}", level="ERROR")
            return []


    @classmethod
    async def set_base_whitelist(cls, redis: Redis, db: PgSqlDep) -> bool:
        try:
            base_commands = await db.whitelist_cmd.get_all()
            base_list = [{'id': row['id'], 'command': row['command'], 'is_active': row['is_active']} for row in base_commands]

            "On/Off Whitelist"
            if len(base_list) == 0:
                cls.whitelist_mode = False
            else:
                cls.whitelist_mode = True

            await redis.set(cls.whitelist_key, orjson.dumps(base_list).decode('utf-8'))

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
        whitelist = await CommandWhitelistCache.get_base_whitelist(redis, cmd_only=True)

        "Заполняем список, если был удалён"
        if not whitelist or cls.whitelist_mode is None:
            await CommandWhitelistCache.set_base_whitelist(redis, db)
            whitelist = await CommandWhitelistCache.get_base_whitelist(redis, cmd_only=True)
            log_event(f'Сетим команды белого списка | cmds: {whitelist}')

        if cls.whitelist_mode:
            base_cmd = command.split()[0]
            "Заполняем список, если был удалён"


            "Повторная проверка, если обновление списка выключило whitelist"
            # если команда в белом списке - пропускаем. Если она не в белом списке, блок. НО если белый список вырублен, то пропускаем
            log_event(f'Проверяем команду на наличие в белом списке | base_cmd: \033[32m{base_cmd}\033[0m; wh_status: \033[34m{cls.whitelist_mode}\033[0m')
            return (base_cmd in whitelist) or (not cls.whitelist_mode)

        log_event(f'Белый список отключён, команда пропущена | cmd: \033[35m{command}\033[0m', level='WARNING')
        return True