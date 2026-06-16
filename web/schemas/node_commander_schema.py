import re
from typing import Literal

from pydantic import BaseModel, IPvAnyAddress, Field, field_validator

from web.utils.anything import Constants
from web.utils.logger_config import log_event


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
            r'[;&|`$]',           # Command injection символы
            r'\$\(',              # Command substitution
            r'[\(\)]',            # Subshell execution
            r'[\{\}]',            # Brace expansion
            r'>+\s*/dev/',        # Запись/append в /dev/
            r'>+\s*/etc/',        # Запись/append в /etc/
            r'rm\s+-rf\s+/\*?',   # Рекурсивное удаление от корня
            r':\(\)\{',           # Fork bomb
            r'curl.*\|.*sh',      # Curl pipe to shell
            r'wget.*\|.*sh',      # Wget pipe to shell
            r'\\x[0-9a-fA-F]{2}', # Hex encoding обход
            r'[\n\r]',            # Newline injection
            r'\$IFS',             # IFS injection
        ]

        "Откидываем sudo и т.п. команды перед валидацией"
        splitted_cmd = v.split() + [' '] # для splitted_cmd[1:], чтобы избежать IndexError
        cmd = v if splitted_cmd[0] not in Constants.excluded_commands_words else ' '.join(splitted_cmd[1:])

        "Проверка на опасные паттерны"
        for pattern in dangerous_patterns:
            if re.search(pattern, cmd):
                raise ValueError(f"Команда содержит опасный паттерн: {pattern}")

        return v


    @field_validator('private_ip', mode='after')
    @classmethod
    def validate_private_ip(cls, v: str):
        return str(v)

class ReadConfigSchema(BaseModel):
    node_proto_id: int
    flatten_json_users_key: str | None = Field(default=None, description="Ключ к списку пользователей в конфиге. При чтении с админки этот объект вырезается во избежание лишних сетевых расходов")



class WriteConfigSchema(RemoteExecBaseSchema):
    file_path: str
    file_content: str
    flatten_json_users_key: str | None = Field(description='Ключ к списку пользователей в конфиге. При записи этот объект переносится из старого файла')


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
