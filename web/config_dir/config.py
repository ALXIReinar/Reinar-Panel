import logging
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from aiohttp import ClientSession
from fastapi import Depends
from passlib.context import CryptContext
from pydantic import BaseModel
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
WORKDIR = Path(__file__).resolve().parent.parent.parent

LOG_DIR = WORKDIR / 'web_logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

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
    pg_user: str
    pg_password: str
    pg_max_connections: int
    pg_db: str
    pg_port: int
    pg_host: str
    pg_port_docker: int
    pg_host_docker: str

    redis_password: str
    redis_host: str
    redis_port: int
    redis_port_docker: int
    redis_host_docker: str

    uvi_workers: int
    post_processing_responses: bool
    app_mode: AppMode
    trusted_proxies: set[str] = {'127.0.0.1', '172.18.0.1', '172.18.0.9'}
    model_config = SettingsConfigDict(extra='allow')
    domain: str


@lru_cache
def get_env_vars():
    return Settings()

env = get_env_vars()


"PostgreSQL"
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
    max_size=env.pg_max_connections # connections on pool
)


"AioHttp для микроопераций"
async def get_any_aiohttp(request: Request) -> ClientSession:
    return request.app.state.any_aiohttp

AnyAiohttpDep = Annotated[ClientSession, Depends(get_any_aiohttp)]