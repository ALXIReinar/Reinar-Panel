from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from starlette.requests import Request

from web.sub.config_dir.config import redis_settings


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
