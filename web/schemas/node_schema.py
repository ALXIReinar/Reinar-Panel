from datetime import datetime
from pydantic import Field, BaseModel


class NodeCreateSchema(BaseModel):
    """Схема для создания физической ноды"""
    ip: str = Field(..., description="Публичный IP адрес")
    private_ip: str = Field(..., description="Приватный IP адрес (WireGuard)")
    api_port: int = Field(..., gt=0, le=65535, description="Порт Node Client API")
    title: str = Field(..., min_length=1, max_length=200, description="Название ноды")
    status: int = Field(default=1, description="Статус ноды(main, vpn_worker, balancer)")
    is_active: bool = Field(default=True, description="Активна ли нода")


class NodeUpdateSchema(BaseModel):
    """Схема для обновления физической ноды"""
    node_id: int = Field(description='ID физической ноды')
    ip: str | None = Field(None, description="Публичный IP адрес")
    private_ip: str | None = Field(None, description="Приватный IP адрес")
    api_port: int | None = Field(None, gt=0, le=65535, description="Порт Node Client API")
    title: str | None = Field(None, min_length=1, max_length=200, description="Название ноды")
    status: int | None = Field(None, description="Статус ноды(main, vpn_worker, balancer)")
    is_active: bool | None = Field(None, description="Активна ли нода")


class NodeSchema(BaseModel):
    """Схема физической ноды"""
    id: int
    ip: str
    private_ip: str | None
    api_port: int
    title: str | None
    status: int
    is_active: bool | None
    created_at: datetime
    updated_at: datetime | None
    status_name: str | None = None  # Из JOIN с node_statuses
