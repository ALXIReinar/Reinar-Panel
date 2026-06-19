from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from pydantic_core.core_schema import ValidationInfo


class GetNodeProtoSchema(BaseModel):
    node_id: int
    limit: int = Field(le=30)
    offset: int = Field(0, ge=0)

class NodeProtocolCreateSchema(BaseModel):
    """Схема для добавления протокола на ноду"""
    node_id: int = Field(..., gt=0, description="ID физической ноды")
    proto_id: int = Field(..., gt=0, description="ID протокола")
    sub_node_address: str | None = Field(None, min_length=4, max_length=255, description="Домен протокола в конфиге клиентов")
    title: str = Field(min_length=1, max_length=128, description='Описание виртуальной ноды (инстанса протокола)')


class UpdateNodeProtoSchema(BaseModel):
    """Схема для обновления виртуальной ноды"""
    node_proto_id: int = Field(..., gt=0, description="ID виртуальной ноды")
    config_path: str | None = Field(None, min_length=1, description="Путь к конфигу протокола")
    title: str | None = Field(None, min_length=1, max_length=128, description="Название виртуальной ноды")
    metrics_port: int | None = Field(None, ge=1024, le=65535, description="Порт для сбора метрик трафика")
    proto_port: int | None = Field(None, ge=1024, le=65535, description="Порт протокола для клиентов")
    sub_node_address: str | None = Field(None, min_length=4, max_length=255, description="Домен протокола в конфиге клиентов")
    user_visible: bool | None = Field(None, description="Видимость для пользователей")

    @field_validator('proto_port', mode='after')
    @classmethod
    def proto_port_validator(cls, v, info: ValidationInfo):
        if v is not None and info.data.get('metrics_port') is not None:
            if v == info.data['metrics_port']:
                raise ValueError('Порт протокола не может быть равен порту для сбора статистики трафика!')
        return v

