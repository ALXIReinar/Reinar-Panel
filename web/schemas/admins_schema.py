import html
import re

from pydantic import BaseModel, Field, field_validator


class ValidatePasswSchema(BaseModel):
    passw: str
    @field_validator('passw', check_fields=False, mode='before')
    @classmethod
    def validate_password(cls, value):
        passw = value.strip()
        if len(passw) < 8:
            raise ValueError('String shorter 8 characters')

        if len(passw.encode('utf-8')) > 72:
            raise ValueError('Password too long (max 72 bytes)')
        spec_spell = digit = uppercase = False

        for ch in passw:
            if re.match(r'[А-Яа-я]', ch):
                raise ValueError('Password must consist of English chars only')
            if ch == ' ':
                raise ValueError('Password must not contain spaces')

            if ch.isdigit():
                digit = True
            elif ch in {'.', ';', '\\', '!', '_', '/', '&', ')', '>', '$', '*', '}', '=', ',', '[', '#', '%', '~', ':',
                        '{', ']', '?', '@', "'", '(', '`', '"', '^', '|', '<', '-', '+', '№'}:
                spec_spell = True
            elif ch == ch.upper():
                uppercase = True

        if spec_spell and digit and uppercase:
            return passw
        raise ValueError('Password does not match the conditions: 1 Spec char, 1 digit, 1 Uppercase letter')

class TokenPayloadSchema(BaseModel):
    id: int
    user_agent: str = Field(max_length=200)
    ip: str = Field(max_length=45)  # IPv6 может быть до 45 символов

    @field_validator('user_agent')
    @classmethod
    def sanitize_user_agent(cls, value: str) -> str:
        # Экранируем HTML и удаляем потенциально опасные символы
        sanitized = html.escape(value)
        # Удаляем управляющие символы
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32)
        return sanitized[:200]  # Обрезаем до максимума


class UpdatePasswSchema(ValidatePasswSchema):
    user_id: int

class AdminLogInSchema(BaseModel):
    login: str = Field(max_length=128, min_length=3)
    passw: str

class AdminRegSchema(ValidatePasswSchema):
    login: str = Field(max_length=128, min_length=3)
