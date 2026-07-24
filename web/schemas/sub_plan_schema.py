from pydantic import BaseModel, Field
from typing import Optional


class SubPlanCreateSchema(BaseModel):
    """Схема для создания группы подписок"""
    title: str = Field(..., min_length=1, max_length=128, description="Название группы")


class SubPlanUpdateSchema(BaseModel):
    """Схема для обновления группы подписок"""
    title: Optional[str] = Field(None, min_length=1, max_length=128, description="Название группы")
    description: Optional[str] = Field(None, description="Описание группы")
    is_active: Optional[bool] = Field(None, description="Статус активности группы")
    position: int | None = Field(None)
    add_node_proto_ids: Optional[list[int]] = Field(None, description="ID виртуальных нод для привязки")
    remove_node_proto_ids: Optional[list[int]] = Field(None, description="ID виртуальных нод для отвязки")
    offers: list["SubPlanOfferSchema"]


class SubPlanOfferSchema(BaseModel):
    id: int
    ttl_days: Optional[int] = Field(None, gt=0, description="Длительность подписки в днях")
    cost: Optional[int] = Field(None, ge=0, description="Стоимость в копейках")
    traffic_limit_day: Optional[int] = Field(None, ge=-1, description="Лимит трафика в МБ (-1 = безлимит)")
    traffic_limit_total: int | None = Field(None)
    infinite_traffic: bool | None = Field(None)
    infinite_expire: bool | None = Field(None)
    is_active: bool | None = Field(None)
    position: int | None = Field(None)