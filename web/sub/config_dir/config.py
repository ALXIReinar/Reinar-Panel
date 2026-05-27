import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import orjson
from aiohttp import ClientSession
from arq.connections import RedisSettings, ArqRedis
from asyncpg import Connection
from fastapi import Depends
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
from starlette.requests import Request

from web.sub.config_dir.env_modes import APP_MODE_CONFIG, AppMode

env_files = (
    os.getenv('ENV_FILE') or
    os.getenv('ENV_LOCAL_TEST_FILE') or
    '.env.sub.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | node_port: \033[32m{os.getenv("UVICORN_PORT")}\033[0m')

"Создаём директории"
WORKDIR = Path(__file__).resolve().parent.parent

LOG_DIR = WORKDIR / 'sub_logs'
ARQ_LOG_DIR = WORKDIR / 'arq_logs'

LOG_DIR.mkdir(parents=True, exist_ok=True)
ARQ_LOG_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Настройки Node Client"""
    # Postgresql
    pg_user: str
    pg_password: str
    pg_db: str
    pg_port: int
    pg_host: str
    pg_port_docker: int
    pg_host_docker: str
    pg_max_connections: int

    # Redis
    redis_password: str
    redis_host: str
    redis_port: int
    redis_port_docker: int
    redis_host_docker: str

    # Robokassa
    robo_shop_login: str
    robo_crypt_algorithm: Literal['sha256', 'md5']
    robo_passw_1: str
    robo_passw_2: str

    # ARQ Settings
    arq_max_jobs: int = 10
    arq_job_timeout: int = 300
    node_metrics_queue_limit: int = 10


    uvicorn_port: int
    uvicorn_workers: int
    trusted_proxies: set[str] = {'127.0.0.1', '172.0.18.0'}

    app_mode: AppMode
    subscription_update_interval: str
    tg_bot_link: str
    model_config = SettingsConfigDict(extra='allow')


@lru_cache
def get_env_vars():
    return Settings()
env = get_env_vars()


"PostgreSQL"
async def init(conn: Connection):
    await conn.set_type_codec(
        'jsonb',
        encoder=lambda v: orjson.dumps(v).decode('utf-8'),
        decoder=orjson.loads,
        schema='pg_catalog',
    )
    await conn.set_type_codec(
        'json',
        encoder=lambda v: orjson.dumps(v).decode('utf-8'),
        decoder=orjson.loads,
        schema='pg_catalog',
    )

def get_pg_settings(envs: Settings):
    cfg = APP_MODE_CONFIG[envs.app_mode]
    host = getattr(envs, cfg["pg_host"])
    port = getattr(envs, cfg["pg_port"])

    return {"host": host, "port": port}

pool_settings = dict(
    user=env.pg_user,
    database=env.pg_db,
    password=env.pg_password,
    **get_pg_settings(env),
    command_timeout=60,
    init=init,
    max_size=env.pg_max_connections # connections on pool
)


"Redis"
def get_redis_settings(envs: Settings):
    cfg = APP_MODE_CONFIG[envs.app_mode]

    redis_conf = {
        'host': getattr(envs, cfg['redis_host']),
        'port': getattr(envs, cfg['redis_port']),
        'decode_responses': True,
    }
    if envs.app_mode != 'local':
        redis_conf['password'] = envs.redis_password
    return redis_conf

redis_settings = get_redis_settings(env)


"ARQ для фоновых задач"
def get_arq_redis_settings():
    return RedisSettings(
        host=redis_settings['host'],
        port=redis_settings['port'],
        password=redis_settings.get('password'),
        database=0,
    )

async def get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool

ArqDep = Annotated[ArqRedis, Depends(get_arq_pool)]


"AioHttp для вызова эндпоинтов админки"
def get_robo_aiohttp(request: Request) -> ClientSession:
    return request.app.state.robo_aiohttp

RoboAiohttpDep = Annotated[ClientSession, Depends(get_robo_aiohttp)]