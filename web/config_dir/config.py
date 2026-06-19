import logging
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import orjson
from aiohttp import ClientSession
from arq.connections import ArqRedis, RedisSettings
from asyncpg import Connection
from fastapi import Depends
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
from starlette.requests import Request

from web.config_dir.env_modes import AppMode, APP_MODE_CONFIG

env_files = (
    os.getenv('ENV_FILE') or
    os.getenv('ENV_LOCAL_TEST_FILE') or
    '.env.api.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | app_mode: \033[32m{os.getenv('APP_MODE')}\033[0m')

"Создаём директории"
WORKDIR = Path(__file__).resolve().parent.parent

LOG_DIR = WORKDIR / 'web_logs'
ARQ_LOG_DIR = WORKDIR / 'arq_logs'

LOG_DIR.mkdir(parents=True, exist_ok=True)
ARQ_LOG_DIR.mkdir(parents=True, exist_ok=True)

"Хэш-метод"
encryption = CryptContext(schemes=['argon2'], deprecated='auto')


@lru_cache
def get_pkey():
    """"""
    "Докер Окружение"
    docker_secret_path = Path('/run/secrets/private_key.pem')
    if docker_secret_path.exists():
        return docker_secret_path.read_text()

    "Локалка"
    local_path = WORKDIR / 'secrets' / 'keys' / 'private_key.pem'
    if local_path.exists():
        return local_path.read_text()

    raise FileNotFoundError("Private key not found in Docker secrets or local paths")


@lru_cache
def get_pubkey():
    """"""
    "Докер Окружение"
    docker_secret_path = Path('/run/secrets/public_key.pem')
    if docker_secret_path.exists():
        return docker_secret_path.read_text()

    "Локалка"
    local_path = WORKDIR / 'secrets' / 'keys' / 'public_key.pem'
    if local_path.exists():
        return local_path.read_text()

    raise FileNotFoundError("Public key not found in Docker secrets or local paths")

class AuthConfig(BaseModel):
    private_key: str = get_pkey()
    public_key: str = get_pubkey()
    algorithm: str = 'RS256'
    ttl_aT: timedelta = timedelta(minutes=15)
    ttl_rT: timedelta = timedelta(days=30)


class Settings(BaseSettings):
    JWTs: AuthConfig = AuthConfig()
    pg_user: str
    pg_password: str
    pg_max_connections: int
    pg_db: str
    pg_port: int
    pg_host: str

    redis_password: str
    redis_host: str
    redis_port: int

    uvicorn_workers: int
    uvicorn_port: int
    post_processing_responses: bool
    app_mode: AppMode
    sub_link_bytes: int = Field(le=64, ge=16)
    trusted_proxies: set[str] = {'127.0.0.1', '172.20.0.1'}
    allowed_ips: set[str] = {'127.0.0.1', '172.20.0.1',}
    model_config = SettingsConfigDict(extra='allow')
    domain: str
    
    # ARQ Settings
    arq_queue_name: str
    arq_max_jobs: int
    arq_job_timeout: int
    node_metrics_queue_limit: int = 10


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
    if envs.app_mode != AppMode.LOCAL:
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

def get_arq_worker_settings():
    return {
        'default_queue_name': env.arq_queue_name,
    }

async def get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool

ArqDep = Annotated[ArqRedis, Depends(get_arq_pool)]


"AioHttp для Исполнения команд на Нодах"
async def get_cmd_exec_aiohttp(request: Request) -> ClientSession:
    return request.app.state.cmd_center_aiohttp

NodeExecAiohttpDep = Annotated[ClientSession, Depends(get_cmd_exec_aiohttp)]