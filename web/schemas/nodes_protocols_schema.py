from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from pydantic_core.core_schema import ValidationInfo


class NodeProtocolCreateSchema(BaseModel):
    """Схема для добавления протокола на ноду"""
    node_id: int = Field(..., gt=0, description="ID физической ноды")
    proto_id: int = Field(..., gt=0, description="ID протокола")
    title: str = Field(min_length=1, max_length=128, description='Описание виртуальной ноды (инстанса протокола)')


class UpdateNodeProtoSchema(BaseModel):
    """Схема для обновления виртуальной ноды"""
    node_proto_id: int = Field(..., gt=0, description="ID виртуальной ноды")
    config_path: str | None = Field(None, min_length=1, description="Путь к конфигу протокола")
    title: str | None = Field(None, min_length=1, max_length=128, description="Название виртуальной ноды")
    metrics_port: int | None = Field(None, ge=1024, le=65535, description="Порт для сбора метрик трафика")
    proto_port: int | None = Field(None, ge=1024, le=65535, description="Порт протокола для клиентов")
    user_visible: bool | None = Field(None, description="Видимость для пользователей")

    @field_validator('proto_port', mode='after')
    @classmethod
    def proto_port_validator(cls, v, info: ValidationInfo):
        if v is not None and info.data.get('metrics_port') is not None:
            if v == info.data['metrics_port']:
                raise ValueError('Порт протокола не может быть равен порту для сбора статистики трафика!')
        return v


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
