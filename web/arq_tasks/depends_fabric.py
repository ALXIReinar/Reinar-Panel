from functools import wraps

from aiohttp import ClientSession
from arq import ArqRedis

from web.data.postgres import PgSql


def pg_sql_dep(func):
    """DI для использования PostgreSQL в arq воркере"""

    @wraps(func)
    async def wrapper(ctx: dict, *args, **kwargs):
        pool = ctx['pg_pool']

        "Передаём соединение"
        async with pool.acquire() as conn:
            db = PgSql(conn)

            return await func(ctx, *args, db=db, **kwargs)

    return wrapper


def arq_dep(func):
    """DI для использования Arq в arq воркере для task chaining"""

    @wraps(func)
    async def wrapper(ctx: dict, *args, **kwargs):
        arq_redis: ArqRedis = ctx['arq_redis']

        "Передаём соединение"
        return await func(ctx, *args, arq=arq_redis, **kwargs)

    return wrapper


def aiohttp_dep(func):
    """DI для использования AioHttp в arq воркере для обращения к нодам"""

    @wraps(func)
    async def wrapper(ctx: dict, *args, **kwargs):
        session: ClientSession = ctx['aio_http']

        "Передаём соединение"
        return await func(ctx, *args, aio_http=session, **kwargs)

    return wrapper