from datetime import datetime
from pydantic import Field, BaseModel, IPvAnyAddress, field_validator


class NodeCreateSchema(BaseModel):
    """Схема для создания физической ноды"""
    ip: IPvAnyAddress = Field(description="Публичный IP адрес")
    private_ip: IPvAnyAddress = Field(description="Приватный IP адрес (WireGuard)")
    api_port: int = Field(..., gt=0, le=65535, description="Порт Node Client API")
    title: str = Field(..., min_length=1, max_length=200, description="Название ноды")
    is_active: bool = Field(default=True, description="Активна ли нода")

    @field_validator('ip', 'private_ip', mode='after')
    @classmethod
    def ipvany2str(cls, v):
        return str(v)

class NodesGetSchema(BaseModel):
    is_active: bool | None = None
    limit: int = Field(le=50)
    offset: int = Field(0, ge=0)

class NodeUpdateSchema(BaseModel):
    """Схема для обновления физической ноды"""
    node_id: int = Field(description='ID физической ноды')
    ip: str | None = Field(None, description="Публичный IP адрес")
    private_ip: str | None = Field(None, description="Приватный IP адрес")
    api_port: int | None = Field(None, gt=0, le=65535, description="Порт Node Client API")
    title: str | None = Field(None, min_length=1, max_length=200, description="Название ноды")
    is_active: bool | None = Field(None, description="Активна ли нода")

