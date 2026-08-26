import logging
import os
from functools import lru_cache
from pathlib import Path

import orjson
from arq.connections import RedisSettings
from asyncpg import Connection
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from web.arq_worker.utils.env_modes import AppMode


env_files = (
    os.getenv('ENV_FILE') or
    'web/arq_worker/.env.arq.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | app_mode: \033[32m{os.getenv('APP_MODE')}\033[0m')

"Создаём директории"
WORKDIR = Path(__file__).resolve().parent

ARQ_LOG_DIR = WORKDIR / 'arq_logs'

ARQ_LOG_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    pg_user: str
    pg_password: str
    pg_max_connections: int
    pg_db: str
    pg_port: int
    pg_host: str

    redis_password: str
    redis_host: str
    redis_port: int

    tg_bot_token: str | None = os.getenv('TG_BOT_TOKEN')
    sub_service_domain: str | None = os.getenv('SUB_SERVICE_DOMAIN')
    app_mode: AppMode

    # ARQ Settings
    arq_queue_name: str
    arq_max_jobs: int
    arq_job_timeout: int
    action_on_core_proto_limit: int
    node_client_command_timeout: int = os.getenv('NODE_CLIENT_COMMAND_TIMEOUT', 120)
    model_config = SettingsConfigDict(extra='allow', env_file_encoding='utf-8')

@lru_cache
def get_env_vars():
    return Settings()

env = get_env_vars()

"Redis"
def get_redis_settings(envs: Settings):
    redis_conf = {
        'host': envs.redis_host,
        'port': envs.redis_port,
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

pool_settings = dict(
    user=env.pg_user,
    database=env.pg_db,
    password=env.pg_password,
    host=env.pg_host,
    port=env.pg_port,
    command_timeout=60,
    init=init,
    max_size=env.pg_max_connections # connections on pool
)
