import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
from starlette.requests import Request

env_files = (
    os.getenv('ENV_FILE') or
    os.getenv('ENV_LOCAL_TEST_FILE') or
    '.env.node.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | node_port: \033[32m{os.getenv("NODE_PORT", "8100")}\033[0m')

"Создаём директории"
WORKDIR = Path(__file__).resolve().parent

LOG_DIR = WORKDIR / 'node_logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

TMP_DIR = Path('/tmp/vpn-panel')
TMP_DIR.mkdir(parents=True, exist_ok=True)

class Settings(BaseSettings):
    """Настройки Node Client"""

    node_name: str = Field(max_length=64)
    node_port: int
    command_timeout: int  # секунды

    write_buffer_size: int # Размер очереди пользователей в памяти на удаление/запись в файл
    write_buffer_interval: int # Интервал записи очереди из памяти на диск (в файл)

    admin_panel_private_ip: str
    model_config = SettingsConfigDict(extra='allow')


@lru_cache
def get_env_vars():
    return Settings()
env = get_env_vars()
