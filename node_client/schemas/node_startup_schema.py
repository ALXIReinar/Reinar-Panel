"""
Схемы данных инициализации от админки (ответ POST /api/v1/server/nodes/{node_title}/startup)

Зеркало web/schemas/node_schema.py (VnodeServiceData), но строже там, где без поля нода не работает:
пустой курсор или экстрактор инжектора — ошибка регистрации, а не молча падающая запись конфига.
"""

from pydantic import BaseModel, ConfigDict, Field


class UserInjectorSchema(BaseModel):
    model_config = ConfigDict(extra='ignore')

    flatten_array_cursor: str = Field(min_length=1, description='Flatten-путь к массиву пользователей в конфиге ядра')
    extractor_script: str = Field(min_length=1, description='Скрипт с функцией transform(user_obj)')
    libs: str | None = Field(None, description='Библиотеки экстрактора через запятую')


class VnodeServiceDataSchema(BaseModel):
    """Служебные данные одной виртуальной ноды: скрипты, команды, путь к конфигу"""

    model_config = ConfigDict(extra='ignore')

    node_proto_id: int = Field(gt=0)
    filepath: str = Field(min_length=1)
    user_injectors: list[UserInjectorSchema] = Field(default_factory=list)
    reload_command: str | None = None
    config2json_script: str | None = None
    json2config_script: str | None = None
    conf_converter_libs: str | None = None
    api_bulk_add_user_script: str | None = None
    api_bulk_delete_user_script: str | None = None
    metrics_command: str | None = None
    api_metrics_script: str | None = None
    proto_python_lib: str | None = None
    metrics_parser_code: str | None = None


class ReinitRequestSchema(BaseModel):
    """Запрос на реинициализацию виртуальных нод"""

    node_proto_ids: list[int] = Field(default_factory=list, description="Пустой список = все зарегистрированные ноды")
