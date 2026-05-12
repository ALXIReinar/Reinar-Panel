import re

from pydantic import BaseModel, IPvAnyAddress, Field, field_validator


class RemoteExecBaseSchema(BaseModel):
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
