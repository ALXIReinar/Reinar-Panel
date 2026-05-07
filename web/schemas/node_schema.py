from datetime import datetime
from pydantic import Field, BaseModel, IPvAnyAddress

from web.utils.anything import NodeStatus


class NodeIPSchema(BaseModel):
    ip: IPvAnyAddress

class NodeCreateSchema(BaseModel):
    """Схема для создания ноды"""
    proto_id: int = Field(..., gt=0, description="ID протокола")
    ip: str = Field(..., description="IP адрес физического сервера")
    title: str = Field(..., min_length=1, max_length=200, description="Название ноды")
    status: NodeStatus = Field(default=NodeStatus.vpn_worker, description="Статус ноды")

class NodeUpdateSchema(BaseModel):
    """Схема для обновления ноды"""
    proto_id: int | None = Field(None, gt=0, description="ID протокола")
    ip: str | None = Field(None, description="IP адрес физического сервера")
    port: int | None = Field(None, gt=0, le=65535, description="Порт протокола")
    title: str | None = Field(None, min_length=1, max_length=200, description="Название ноды")
    status: NodeStatus | None = Field(None, description="Статус ноды")

class NodeSchema(BaseModel):
    """Схема ноды"""
    id: int
    proto_id: int
    ip: str
    title: str
    status: int
    created_at: datetime
    updated_at: datetime
    proto_name: str | None = None  # Для JOIN запросов
