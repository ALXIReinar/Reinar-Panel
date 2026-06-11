from contextlib import asynccontextmanager

import uvicorn
from aiohttp import ClientSession
from arq import create_pool as create_arq_pool
from asyncpg import create_pool
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from redis.asyncio import Redis
from starlette.middleware.cors import CORSMiddleware

from web.api import main_router
from web.api.middleware import ASGILoggingMiddleware, AuthUXASGIMiddleware
from web.config_dir.config import env, pool_settings, redis_settings, get_arq_redis_settings, get_arq_worker_settings


@asynccontextmanager
async def lifespan(web_app):
    """Lifecycle manager для FastAPI"""

    "Соединение с БД"
    web_app.state.pg_pool = await create_pool(**pool_settings)

    "AioHttp для взаимодействия с Нодами"
    web_app.state.cmd_center_aiohttp = ClientSession(timeout=30.0)

    "Соедиение с Redis"
    web_app.state.redis = Redis(**redis_settings)
    
    "ARQ пул для фоновых задач"
    web_app.state.arq_pool = await create_arq_pool(get_arq_redis_settings(), **get_arq_worker_settings())
    
    try:
        yield
    finally:
        await web_app.state.pg_pool.close()
        await web_app.state.cmd_center_aiohttp.close()
        await web_app.state.redis.aclose()
        await web_app.state.arq_pool.close()

app = FastAPI(
    # docs_url='/api/docs',
    # openapi_url='/api/openapi.json',
    lifespan=lifespan,
    default_response_class=ORJSONResponse, # используем в X5 раз более быстрый кодек orjson вместо json
    response_model=env.post_processing_responses,
    response_model_exclude_unset=env.post_processing_responses
)

app.include_router(main_router)


"Миддлвари"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://127.0.0.1:{env.uvicorn_port}", f"http://localhost:{env.uvicorn_port}", env.domain],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*']
)
app.add_middleware(AuthUXASGIMiddleware)
app.add_middleware(ASGILoggingMiddleware)

if __name__ == '__main__':
    # uvicorn.run('web.main:app', host="0.0.0.0", port=env.uvicorn_port, log_config=None, workers=env.uvicorn_workers)
    uvicorn.run('web.main:app', host="0.0.0.0", port=env.uvicorn_port, workers=env.uvicorn_workers)