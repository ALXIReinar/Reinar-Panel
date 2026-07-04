"""
Схемы для управления пользователями в ядре протокола
"""
from pydantic import BaseModel, Field, field_validator


class BaseUserCoreSchema(BaseModel):
    node_proto_id: int = Field(..., gt=0, description='ID инстанса ядра (виртуальной ноды)')
    core_lib: str | None = Field(None, max_length=100, description='Библиотека для hot-reload (grpcio, requests)')
    reload_core_command: str = Field(None, max_length=255, description='Команда перезагрузки ядра')
    core_port: int | None = Field(gt=0, le=65535, description='Порт к апи ядра для взаимодействия через скрипты')
    config_file_path: str = Field(..., min_length=1, description='Путь к конфиг-файлу')
    flatten_json_users_key: str = Field(..., min_length=1, description='Flatten-json путь до массива clients')
    flatten_user_identifier_key: str = Field(..., min_length=1, description='Flatten-json путь до идентификатора пользователя'
                                                                            ' относительно массива clients')
    custom_params: dict | None = Field(description='Зависимости для скрипта, которые идут отдельно от объекта пользователя')

class UserCoreDeleteSchema(BaseModel):
    tg_username: str = Field(min_length=5, max_length=32)
    uuid: str = Field(max_length=36)

    sub_node_id: int = Field(description='ID ноды в группе подписок. Служебное, не для нод-кдиента')
    order_id: int = Field(description='ID купленной пользователем подписки. Служебное, не для нод-кдиента')


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
    users: list[UserCoreDeleteSchema]

class BulkAddUserCoreSchema(BaseUserCoreSchema):
    bulk_add_script: str | None
    users: list[dict]
