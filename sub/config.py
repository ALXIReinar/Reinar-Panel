import logging
import os
from functools import lru_cache
from pathlib import Path

import orjson
from asyncpg import Connection
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


env_files = (
    os.getenv('ENV_FILE') or
    os.getenv('ENV_LOCAL_TEST_FILE') or
    '.env.sub.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | node_port: \033[32m{os.getenv("UVICORN_PORT")}\033[0m')

"Создаём директории"
WORKDIR = Path(__file__).resolve().parent

LOG_DIR = WORKDIR / 'sub_logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Настройки Node Client"""
    pg_user: str
    pg_password: str
    pg_db: str
    pg_port: int
    pg_host: str
    pg_max_connections: int

    uvicorn_port: int
    uvicorn_workers: int
    trusted_proxies: set[str] = {'127.0.0.1', '172.0.18.0'}

    domain: str = Field(max_length=255)
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

