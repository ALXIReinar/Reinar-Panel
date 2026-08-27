from typing import Literal, Annotated

from fastapi.params import Depends
from pydantic import BaseModel, Field, field_validator


class GetTmpSchema(BaseModel):
    last_id: int | None = None
    sort_by: Literal['asc', 'desc'] = 'desc'
    limit: int = Field(default=20, gt=0, le=100)
GetTmpSchema = Annotated[GetTmpSchema, Depends()]

class AddTmpSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=32, description='Имя шаблона')


class UpdateTmpSchema(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=32, description='Имя шаблона')
    url_tmp: str | None = Field(None, min_length=1, description='Шаблон URL конфиг-ссылки')
    reload_core_command: str | None | int = Field(0, min_length=2, max_length=256, description='Команда перезагрузки ядра')
    required_user_data_obj: dict | None = Field(None, description='Обязательные данные пользователя с маркерами')
    constant_user_data_obj: dict | None = Field(None, description='Константные данные пользователя')
    proto_python_lib: str | None | int = Field(0, max_length=512, description='Библиотека для hot-reload (grpcio, requests)')
    sub_prepare_script: str | None | int = Field(0, description='Скрипт подготовки подписки')
    sub_required_libs: list[str] | str | None | int = Field(0, max_length=512, description='Требуемые библиотеки для подписки')
    api_bulk_delete_user_script: str | None | int = Field(0, description='Python скрипт для bulk удаления пользователей')
    api_bulk_add_user_script: str | None | int = Field(0, description='Python скрипт для bulk добавления пользователей')
    metrics_parser_code: str | None = Field(None, description='Код парсера метрик')
    metrics_command: str | None = Field(None, description='Команда получения метрик')
    bulk_delete_script_custom_params: dict | None = Field(None, description='Кастомные параметры для bulk delete скрипта')
    bulk_add_script_custom_params: dict | None = Field(None, description='Кастомные параметры для bulk add скрипта')
    api_metrics_script: str | None | int = Field(0, description='Python скрипт для получения метрик через API')
    is_accepted: bool | None = Field(None, description='Принят ли шаблон администратором')
    config2json_script: str | None | int = Field(0, description='Конвертер-скрпт конфига из его формата в json-структуру(python dict)')
    json2config_script: str | None | int = Field(0, description='Конвертер-скрпт из json-структуры в dict')
    conf_converter_libs: str | None | int = Field(0)

    @field_validator('url_tmp')
    @classmethod
    def tmp_url_validator(cls, v):
        if v is not None and not all(item in v for item in ['{{node___title}}', '{{node___address}}']):
            raise ValueError('Обязательные плейсхолдеры не добавлены! ({{node___title}}, {{node___address}})')
        return v

    @field_validator('required_user_data_obj')
    @classmethod
    def required_user_data_validator(cls, v):
        if v is not None:
            # Проверка, что все значения - строки с маркерами или обычные значения
            for key, value in v.items():
                if not isinstance(value, str):
                    raise ValueError(f'Значение поля "{key}" должно быть строкой с маркером или обычным значением')
        return v

    @field_validator('sub_required_libs', mode='after')
    @classmethod
    def sub_required_libs_validator(cls, v):
        if isinstance(v, list):
            return ','.join(v)
        return v


class EditUserInjectorsSchema(BaseModel):
    user_injectors: list["UserInjector"] = Field(description='State инжекторов шаблона. Передавать Итоговое состояние ВСЕХ инжекторов, если произошло хотя бы одно изменение')


class UserInjector(BaseModel):
    flatten_array_cursor: str = Field(max_length=1024)
    extractor_script: str
    libs: list[str] | str | None = Field(None, description='Требуемые библиотеки для подписки')

    @field_validator('libs', mode='after')
    @classmethod
    def libs_validator(cls, v):
        if isinstance(v, list):
            return ','.join(v)
        return v

    @field_validator('extractor_script', mode='after')
    @classmethod
    def extractor_script_validator(cls, v):
        # Проверяем что скрипт содержит def transform( и return, но НЕ содержит async
        if 'def transform(' not in v or 'return' not in v:
            raise ValueError('Extractor Script должен содержать функцию transform (def transform(user_obj):) с оператором return')
        if 'async' in v:
            raise ValueError('Extractor Script должен быть синхронным (не async)')
        return v

class DeleteTmpSchema(BaseModel):
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
