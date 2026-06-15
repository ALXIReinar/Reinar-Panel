from datetime import datetime

from pydantic import BaseModel, Field


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
    proto_id: int
    commands: list[CommandUpdateItemSchema] = Field(..., min_length=1, description="Список команд для обновления")


class CommandsBulkDeleteSchema(BaseModel):
    """Схема для массового удаления команд"""
    proto_id: int
    cmd_ids: list[int] = Field(..., min_length=1, description="Список ID команд для удаления")
