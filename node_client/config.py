import logging
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

env_files = (
    os.getenv('ENV_FILE') or
    os.getenv('ENV_LOCAL_TEST_FILE') or
    'node_client/.env.node.prod'
)
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


class AuditModes(str, Enum):
    lite = 'lite'                        # Сравнение длины. Лог при расхождении. Нод клиент продолжает работать
    medium = 'medium'                    # Глубокое сравнение каждого пользователя из State файла с пользователем из Конфиг-файла впн-ядра
    strict = 'strict'                    # Как Medium, но нод клиент прекращает работу и падает с ValueError

    medium_advanced = 'medium_advanced'  # Medium. Расхождения отправляются на админку
    strict_advanced = 'strict_advanced'  # Strict + Умное уведомление на админку


class Settings(BaseSettings):
    """Настройки Node Client"""

    node_name: str = Field(max_length=64)
    lru_cache_max_size: int | None = os.getenv('LRU_CACHE_MAX_SIZE', None)
    node_port: int
    command_timeout: int  # секунды

    write_buffer_size: int # Размер очереди пользователей в памяти на удаление/запись в файл
    write_buffer_interval: int # Интервал записи очереди из памяти на диск (в файл)

    admin_panel_private_ip: str
    audit_mode: AuditModes = Field(default=AuditModes.lite)
    model_config = SettingsConfigDict(extra='allow')


@lru_cache
def get_env_vars():
    return Settings()
env = get_env_vars()
