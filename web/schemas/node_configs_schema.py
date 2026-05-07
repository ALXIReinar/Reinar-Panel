from datetime import datetime
from pydantic import BaseModel, Field



class BaseProtoConfigSchema(BaseModel):
    node_id: int = Field(..., gt=0, description="ID ноды (уже содержит привязку к протоколу)")
    proto_id: int = Field(..., gt=0, description="ID протокола")


class ProtoConfigCreateSchema(BaseProtoConfigSchema):
    """Схема для создания конфигурации протокола на ноде"""
    path: str | None = Field(..., description="Путь к конфигурационному файлу на ноде")


class ProtoConfigUpdateSchema(BaseModel):
    """Схема для обновления конфигурации"""
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу на ноде")


class ProtoConfigSchema(BaseModel):
    """Схема конфигурации протокола"""
    id: int
    node_id: int
    path: str
    created_at: datetime
    # Данные из JOIN'ов
    proto_id: int | None = None
    proto_name: str | None = None
    node_title: str | None = None
    node_ip: str | None = None
    node_status: int | None = None
