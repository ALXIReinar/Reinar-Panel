from pydantic import BaseModel, Field


class ConfigReadSchema(BaseModel):
    """Схема для чтения конфига"""
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")


class ConfigWriteSchema(BaseModel):
    """Схема для записи конфига"""
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    content: str = Field(..., description="Содержимое файла")


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
