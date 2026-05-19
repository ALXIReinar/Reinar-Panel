"""
Схемы для управления пользователями в ядре протокола
"""
from pydantic import BaseModel, Field


class AddUserCoreSchema(BaseModel):
    """Схема для добавления пользователя в ядро протокола"""
    
    node_proto_id: int = Field(..., gt=0, description='ID виртуальной ноды')
    user_uuid: str = Field(..., min_length=1, description='UUID пользователя')
    user_obj: dict = Field(..., description='Готовый объект пользователя для конфига')
    core_lib: str | None = Field(None, max_length=100, description='Библиотека для hot-reload (grpcio, requests)')
    add_script: str | None = Field(None, description='Python скрипт для добавления через API')
    core_port: int | None = Field(None, gt=0, le=65535, description='Порт API ядра')
    reload_core_command: str | None = Field(None, max_length=255, description='Команда перезагрузки ядра')
    config_file_path: str = Field(..., min_length=1, description='Путь к конфиг-файлу')
    flatten_json_users_key: str = Field(..., min_length=1, description='Flatten-json путь до массива clients')


class DeleteUserCoreSchema(BaseModel):
    """Схема для удаления пользователя из ядра протокола"""
    
    node_proto_id: int = Field(..., gt=0, description='ID виртуальной ноды')
    user_uuid: str = Field(..., min_length=1, description='UUID пользователя для удаления')
    core_lib: str | None = Field(None, max_length=100, description='Библиотека для hot-reload')
    delete_script: str | None = Field(None, description='Python скрипт для удаления через API')
    core_port: int | None = Field(None, gt=0, le=65535, description='Порт API ядра')
    reload_core_command: str | None = Field(None, max_length=255, description='Команда перезагрузки ядра')
    config_file_path: str = Field(..., min_length=1, description='Путь к конфиг-файлу')
    flatten_json_users_key: str = Field(..., min_length=1, description='Flatten-json путь до массива clients')
