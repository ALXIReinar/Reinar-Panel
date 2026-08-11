from pydantic import BaseModel, Field


class BaseUserCoreSchema(BaseModel):
    node_proto_id: int = Field(..., gt=0, description='ID инстанса ядра (виртуальной ноды)')
    core_lib: str | None = Field(None, max_length=512, description='Библиотека для hot-reload (grpcio, requests)')
    reload_core_command: str = Field(None, max_length=255, description='Команда перезагрузки ядра')
    core_port: int | None = Field(gt=0, le=65535, description='Порт к апи ядра для взаимодействия через скрипты')
    config_file_path: str = Field(..., min_length=1, description='Путь к конфиг-файлу')
    custom_params: dict | None = Field(description='Зависимости для скрипта, которые идут отдельно от объекта пользователя')
    user_injectors: list["UserInjector"]

class UserInjector(BaseModel):
    """
    Схема для BaseUserCoreSchema.user_injectors. Это список вставок в конкретные массивы с помощью extractor_script.
    Массивы определяются flatten_array_cursor. Таких вставок может быть несколько.

    - Задача extractor_script сделать из объекта в buffer_storage тот, который нужен в впн ядре.
    - Позволяет сделать несколько операций(удаление/вставка) за одну операцию над пользователем
    """
    flatten_array_cursor: str = Field(description='indounds___0___users - массив')
    extractor_script: str = Field(description='скрипт-обработчик для трансформации user_obj под требования массива под flatten_array_cursor')
    libs: str | None = Field(None, max_length=512, description='Либы, нужные для скрипта-экстрактора объекта пользователя для впн-ядра из Суперобъекта')


class AddUserCoreSchema(BaseUserCoreSchema):
    """Схема для добавления пользователя в ядро протокола"""
    user_obj: dict = Field(..., description='Готовый объект пользователя для конфига')
    add_script: str | None = Field(None, description='Python скрипт для добавления через API')

class DeleteUserCoreSchema(BaseUserCoreSchema):
    """Схема для удаления пользователя из ядра протокола"""
    user_obj: dict = Field(..., description='Готовый объект пользователя для конфига')
    delete_script: str | None = Field(None, description='Python скрипт для удаления через API')

class BulkDeleteUserCoreSchema(BaseUserCoreSchema):
    bulk_delete_script: str | None
    users: list[dict] = Field(description='Список готовых объектов пользователей для конфига')

class BulkAddUserCoreSchema(BaseUserCoreSchema):
    bulk_add_script: str | None
    users: list[dict]
