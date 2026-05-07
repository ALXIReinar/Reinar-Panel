import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

env_files = (
    os.getenv('ENV_FILE') or
    os.getenv('ENV_LOCAL_TEST_FILE') or
    '.env.node.prod'
)
load_dotenv(env_files, override=True)
logging.critical(f'\033[35m{env_files}\033[0m | node_port: \033[32m{os.getenv("NODE_PORT", "8001")}\033[0m')


class Settings(BaseSettings):
    """Настройки Node Client"""
    
    # Основные настройки
    node_port: int = 8001
    command_timeout: int = 30  # секунды
    
    # Разрешённые директории для чтения/записи конфигов
    allowed_config_dirs: set[str] = {
        "/etc/xray",
        "/etc/wireguard",
        "/etc/openvpn",
        "/etc/shadowsocks"
    }
    
    model_config = SettingsConfigDict(extra='allow')


@lru_cache
def get_env_vars():
    return Settings()
env = get_env_vars()
