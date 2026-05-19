import re
from typing import Literal

from pydantic import BaseModel, IPvAnyAddress, Field, field_validator


class RemoteExecBaseSchema(BaseModel):
    node_proto_id: int
    private_ip: IPvAnyAddress
    api_port: int = Field(gt=0, le=65535)


class ExecCMDNodeSchema(RemoteExecBaseSchema):
    cmd: str = Field(..., min_length=2, max_length=100)

    @field_validator('cmd', mode='after')
    @classmethod
    def validate_command(cls, v: str):
        """
        Валидация команды на безопасность

        Returns:
            (is_valid, error_message)
        """
        dangerous_patterns = [
            r'[;&|`$]',  # Command injection символы
            r'\$\(',  # Command substitution
            r'>\s*/dev/',  # Запись в /dev/
            r'rm\s+-rf\s+/',  # Рекурсивное удаление от корня
            r':\(\)\{',  # Fork bomb
            r'>\s*/etc/',  # Запись в /etc/
            r'curl.*\|.*sh',  # Curl pipe to shell
            r'wget.*\|.*sh',  # Wget pipe to shell
        ]

        "Проверка на опасные паттерны"
        for pattern in dangerous_patterns:
            if re.search(pattern, v):
                raise ValueError(f"Команда содержит опасный паттерн: {pattern}")

        return v


class ReadConfigSchema(BaseModel):
    node_proto_id: int


class WriteConfigSchema(RemoteExecBaseSchema):
    file_path: str
    file_content: str


class AddUserCoreProtoSchema(BaseModel):
    tg_username: str = Field(max_length=32)
    uuid: str = Field(min_length=36, max_length=36)
    additional_fields: dict = Field(
        description='Словарь для объектов, которые добавляются в user_obj для пользователей в конфиг-файле ядра'
                    'Значения подставляются пользователем. Например, если этот объект будет {"add_must_have_field": "super_field"}, то'
                    'Конечный user_obj будет выглядеть: {**required_user_data_obj, **constant_user_data_obj, "add_must_have_field": "super_field"}'
    )

class DeleteUserCoreProtoSchema(BaseModel):
    uuid: str = Field(min_length=36, max_length=36)
