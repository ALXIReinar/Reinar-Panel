import logging  # noqa: I001
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from aiohttp import ClientSession
from fastapi import Depends, Request
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

env_files = os.getenv('ENV_FILE') or os.getenv('ENV_LOCAL_TEST_FILE') or 'node_client/.env.node.prod'
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | node_port: \033[32m{os.getenv("NODE_PORT", "8100")}\033[0m')

"Создаём директории"
WORKDIR = Path(__file__).resolve().parent

LOG_DIR = WORKDIR / 'node_logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

TMP_DIR = Path('/tmp/reinar_panel')
TMP_DIR.mkdir(parents=True, exist_ok=True)


class CoreProtoActions:
    add: int = 1
    delete: int = 2

    word_add: str = 'add'
    word_delete: str = 'delete'

    name2id: dict[str, int] = {
        'add': 1,
        'delete': 2,
    }
    id2name: dict[str, str] = {id: name for name, id in name2id.items()}


class AdminPanelUris:
    startup: str = '/api/v1/server/nodes/{node_title}/startup'


class AuditModes(str, Enum):
    lite = 'lite'  # Сравнение длины. Лог при расхождении. Нод клиент продолжает работать
    medium = 'medium'  # Глубокое сравнение каждого пользователя из State файла с пользователем из Конфиг-файла впн-ядра
    strict = 'strict'  # Как Medium, но нод клиент прекращает работу и падает с ValueError

    medium_advanced = 'medium_advanced'  # Medium. Расхождения отправляются на админку
    strict_advanced = 'strict_advanced'  # Strict + Умное уведомление на админку


class Settings(BaseSettings):
    """Настройки Node Client"""

    # NODE_NAME — прежнее имя переменной: старые .env продолжают работать после обновления кода без install.sh
    node_title: str = Field(max_length=64, validation_alias=AliasChoices('NODE_TITLE', 'NODE_NAME', 'node_title'))
    lru_cache_max_size: int | None = os.getenv('LRU_CACHE_MAX_SIZE', 100)
    node_port: int
    command_timeout: int  # секунды

    write_buffer_size: int  # Размер очереди пользователей в памяти на удаление/запись в файл
    write_buffer_interval: int  # Интервал записи очереди из памяти на диск (в файл)

    admin_panel_private_ip: str
    # Без значения по умолчанию: тихий дефолт увёл бы запросы /startup на чужой порт
    admin_panel_port: int = Field(gt=0, le=65535)
    startup_retries: int = 30
    startup_retry_delay_s: int = 5

    audit_mode: AuditModes = Field(default=AuditModes.lite)
    model_config = SettingsConfigDict(extra='allow')


@lru_cache
def get_env_vars():
    return Settings()


env = get_env_vars()


def inject_admin_aiohttp(request: Request) -> ClientSession:
    """HTTP-сессия к админке: одна на всё время жизни нод-клиента (создаётся в lifespan)"""
    return request.app.state.admin_aiohttp


AioHttpAdminDep = Annotated[ClientSession, Depends(inject_admin_aiohttp)]
