from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, IPvAnyAddress


class NodeStatus(str, Enum):
    """Статусы нод"""
    MAIN = "main"
    VPN_WORKER = "vpn_worker"
    BALANCER = "balancer"


# ============= Protocols =============

class ProtocolCreateSchema(BaseModel):
    """Схема для создания протокола"""
    name: str = Field(..., min_length=1, max_length=100, description="Название протокола")


class ProtocolSchema(BaseModel):
    """Схема протокола"""
    id: int
    name: str
    created_at: datetime

class ProtoPagenSchema(BaseModel):
    offset: int = Field(0)
    limit: int = Field(le=15)

# ============= Protocol Commands =============

class ProtocolCommandCreateSchema(BaseModel):
    """Схема для создания команды протокола"""
    proto_id: int = Field(..., gt=0, description="ID протокола")
    cmd_title: str = Field(..., min_length=1, max_length=200, description="Название команды")
    command: str = Field(..., min_length=1, description="CLI команда для выполнения")


class CommandInsertItemSchema(BaseModel):
    """Схема элемента для bulk insert"""
    cmd_title: str = Field(..., min_length=1, max_length=200, description="Название команды")
    command: str = Field(..., min_length=1, description="CLI команда для выполнения")


class CommandsBulkInsertSchema(BaseModel):
    """Схема для массовой вставки команд"""
    proto_id: int = Field(..., gt=0, description="ID протокола")
    commands: list[CommandInsertItemSchema] = Field(..., min_length=1, description="Список команд для вставки")


class CommandUpdateItemSchema(BaseModel):
    """Схема элемента для bulk update"""
    id: int = Field(..., gt=0, description="ID команды")
    cmd_title: str = Field(..., min_length=1, max_length=200, description="Название команды")
    command: str = Field(..., min_length=1, description="CLI команда для выполнения")


class CommandsBulkUpdateSchema(BaseModel):
    """Схема для массового обновления команд"""
    commands: list[CommandUpdateItemSchema] = Field(..., min_length=1, description="Список команд для обновления")


class CommandsBulkDeleteSchema(BaseModel):
    """Схема для массового удаления команд"""
    cmd_ids: list[int] = Field(..., min_length=1, description="Список ID команд для удаления")


class ProtocolCommandSchema(BaseModel):
    """Схема команды протокола"""
    id: int
    proto_id: int
    cmd_title: str
    command: str
    created_at: datetime


# ============= Nodes =============

class NodeCreateSchema(BaseModel):
    """Схема для создания ноды"""
    proto_id: int = Field(..., gt=0, description="ID протокола")
    ip: str = Field(..., description="IP адрес физического сервера")
    port: int | None = Field(None, gt=0, le=65535, description="Порт протокола")
    title: str = Field(..., min_length=1, max_length=200, description="Название ноды")
    status: NodeStatus = Field(default=NodeStatus.VPN_WORKER, description="Статус ноды")


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
    port: int | None
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    proto_name: str | None = None  # Для JOIN запросов


# ============= Protocol Configs =============

class ProtoConfigCreateSchema(BaseModel):
    """Схема для создания конфигурации протокола на ноде"""
    node_id: int = Field(..., gt=0, description="ID ноды (уже содержит привязку к протоколу)")
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу на ноде")


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
    node_port: int | None = None
    node_status: str | None = None
