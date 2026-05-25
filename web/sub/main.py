import uvicorn
from contextlib import asynccontextmanager

from aiohttp import ClientSession
from asyncpg import create_pool
from arq import create_pool as create_arq_pool
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from redis.asyncio import Redis

from web.sub.config_dir.config import redis_settings, pool_settings, env, get_arq_redis_settings


@asynccontextmanager
async def lifespan(web_app: FastAPI):
    """"""
    "Соединение с БД"
    web_app.state.pg_pool = await create_pool(**pool_settings)

    "AioHttp для Робокассы"
    web_app.state.robo_aiohttp = ClientSession()

    "Соедиение с Redis"
    web_app.state.redis = Redis(**redis_settings)

    "ARQ пул для фоновых задач"
    web_app.state.arq_pool = await create_arq_pool(get_arq_redis_settings())
    try:
        yield
    finally:
        await web_app.state.pg_pool.close()
        await web_app.state.robo_aiohttp.close()
        await web_app.state.redis.aclose()
        await web_app.state.arq_pool.close()


app = FastAPI(default_response_class=ORJSONResponse, lifespan=lifespan)



if __name__ == '__main__':
    uvicorn.run('web.sub.main:app', log_config=None, host="0.0.0.0", port=env.uvicorn_port, workers=env.uvicorn_workers)
