from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BaseUserCoreSchema(BaseModel):
    node_proto_id: int = Field(..., gt=0, description='ID инстанса ядра (виртуальной ноды)')
    core_lib: str | None = Field(None, max_length=512, description='Библиотека для hot-reload (grpcio, requests)')
    reload_core_command: str = Field(None, max_length=255, description='Команда перезагрузки ядра')
    core_port: int | None = Field(gt=0, le=65535, description='Порт к апи ядра для взаимодействия через скрипты')
    config_file_path: str = Field(..., min_length=1, description='Путь к конфиг-файлу')
    custom_params: dict | None = Field(description='Зависимости для скрипта, которые идут отдельно от объекта пользователя')
    user_injectors: list["UserInjector"]
    users: list[dict]
    action_script: str | None
    config2json_script: str | None = Field(description='Конвертер-скрпт конфига из его формата в json-структуру(python dict)')
    json2config_script: str | None = Field(description='Конвертер-скрпт из json-структуры в dict')
    conf_converter_libs: str | None

    action: Literal["add", "delete"] = Field(description="Операция, выполняемая скриптом. Вставка или удаление. 1 - add, 2 - delete. Допускаются строки и цифры")

    @field_validator("action", mode="before")
    @classmethod
    def convert_int_to_str(cls, value):
        mapping = {1: "add", 2: "delete"}
        # Если пришло число 1 или 2, меняем его на строку
        return mapping.get(value, value)


class UserInjector(BaseModel):
    """
    Схема для BaseUserCoreSchema.user_injectors. Это список вставок в конкретные массивы с помощью extractor_script.
    Массивы определяются flatten_array_cursor. Таких вставок может быть несколько.

    - Задача extractor_script сделать из объекта в buffer_storage тот, который нужен в впн ядре.
    - Позволяет сделать несколько операций(удаление/вставка) за одну операцию над пользователем
    """
    flatten_array_cursor: str = Field(description='inbounds___0___users - массив')
    extractor_script: str = Field(description='скрипт-обработчик для трансформации user_obj под требования массива под flatten_array_cursor')
    libs: str | None = Field(None, max_length=512, description='Либы, нужные для скрипта-экстрактора объекта пользователя для впн-ядра из Суперобъекта')
