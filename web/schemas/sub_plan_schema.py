from pydantic import BaseModel, Field
from typing import Optional


class SubPlanCreateSchema(BaseModel):
    """Схема для создания группы подписок"""
    title: str = Field(..., min_length=1, max_length=128, description="Название группы")


class SubPlanUpdateSchema(BaseModel):
    """Схема для обновления группы подписок"""
    id: int = Field(..., description="ID группы")
    title: Optional[str] = Field(None, min_length=1, max_length=128, description="Название группы")
    description: Optional[str] = Field(None, description="Описание группы")
    ttl_days: Optional[int] = Field(None, gt=0, description="Длительность подписки в днях")
    cost: Optional[int] = Field(None, ge=0, description="Стоимость в копейках")
    traffic_limit_day: Optional[int] = Field(None, ge=-1, description="Лимит трафика в МБ (-1 = безлимит)")
    is_active: Optional[bool] = Field(None, description="Статус активности группы")
    add_node_proto_ids: Optional[list[int]] = Field(None, description="ID виртуальных нод для привязки")
    remove_node_proto_ids: Optional[list[int]] = Field(None, description="ID виртуальных нод для отвязки")


class SubPlanDeleteSchema(BaseModel):
    """Схема для удаления группы подписок"""
    id: int = Field(..., description="ID группы")
