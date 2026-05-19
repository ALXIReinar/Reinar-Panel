from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GetTmpSchema(BaseModel):
    last_id: int | None = None
    sort_by: Literal['asc', 'desc'] = 'desc'
    limit: int = Field(default=20, gt=0, le=100)


class AddTmpSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=32, description='Имя шаблона')


class UpdateTmpSchema(BaseModel):
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
    url_tmp: str | None = Field(None, min_length=1, description='Шаблон URL конфиг-ссылки')
    reload_core_command: str | None = Field(None, min_length=2, max_length=256, description='Команда перезагрузки ядра')
    required_user_data_obj: dict | None = Field(None, description='Обязательные данные пользователя с маркерами')
    constant_user_data_obj: dict | None = Field(None, description='Константные данные пользователя')
    api_add_user_script: str | None = Field(None, description='Python скрипт для добавления пользователя через API')
    api_delete_user_script: str | None = Field(None, description='Python скрипт для удаления пользователя через API')
    proto_python_lib: str | None = Field(None, max_length=32, description='Библиотека для hot-reload (grpcio, requests)')
    flatten_json_users_key: str | None = Field(None, max_length=1024, description='Путь до массива clients (flatten-json)')
    flatten_json_delete_user_key: str | None = Field(None, max_length=128, description='Путь до параметра-идентификатора пользователя в clients (flatten-json)')
    is_accepted: bool | None = Field(None, description='Принят ли шаблон администратором')

    @field_validator('url_tmp')
    @classmethod
    def tmp_url_validator(cls, v):
        if v is not None and '{user_uuid}' not in v:
            raise ValueError('Необходимо обязательно указать плейсхолдер {user_uuid}')
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


class DeleteTmpSchema(BaseModel):
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
