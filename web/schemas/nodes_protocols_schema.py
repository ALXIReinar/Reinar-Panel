from pydantic import BaseModel, Field
from datetime import datetime

class NodeProtocolCreateSchema(BaseModel):
    """Схема для добавления протокола на ноду"""
    node_id: int = Field(..., gt=0, description="ID физической ноды")
    proto_id: int = Field(..., gt=0, description="ID протокола")
    config_path: str | None = Field(None, description="Путь к конфигу протокола на ноде")


class NodeProtocolUpdateSchema(BaseModel):
    """Схема для обновления виртуальной ноды"""
    config_path: str = Field(..., min_length=1, description="Путь к конфигу протокола")


class NodeProtocolSchema(BaseModel):
    """Схема виртуальной ноды (протокол на физической ноде)"""
    id: int
    node_id: int
    proto_id: int
    config_path: str | None
    created_at: datetime
    updated_at: datetime | None
    # Данные из JOIN'ов
    node_ip: str | None = None
    node_private_ip: str | None = None
    node_api_port: int | None = None
    node_title: str | None = None
    node_is_active: bool | None = None
    proto_name: str | None = None
