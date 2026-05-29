from pydantic import BaseModel, Field


class ConfigReadSchema(BaseModel):
    """Схема для чтения конфига"""
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    flatten_json_users_key: str | None = Field(default=None, description="Ключ к списку пользователей в конфиге. При чтении с админки этот объект вырезается во избежание лишних сетевых расходов")


class ConfigWriteSchema(BaseModel):
    """Схема для записи конфига"""
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    content: str = Field(..., description="Содержимое файла")
    flatten_json_users_key: str | None = Field(description='Ключ к списку пользователей в конфиге. При записи этот объект переносится из старого файла')



class ConfigReadResponseSchema(BaseModel):
    """Схема ответа при чтении конфига"""
    success: bool
    content: str
    path: str


class ConfigWriteResponseSchema(BaseModel):
    """Схема ответа при записи конфига"""
    success: bool
    message: str
    path: str
