from pydantic import BaseModel, Field
from typing import Optional, Literal


class UserCreateItem(BaseModel):
    """Один пользователь для bulk insert"""
    tg_username: str = Field(..., max_length=32, description="Уникальный ник пользователя в ТГ")
    tg_id: Optional[int] = Field(None, description="Telegram ID (опционально)")
    sub_plan_id: int = Field(..., description="ID тарифного плана")
    ttl_days: int = Field(..., gt=0, description="Длительность подписки в днях")
    is_active: bool = Field(True, description="Статус активации подписки")


class UserBulkCreateSchema(BaseModel):
    """Схема для bulk insert пользователей"""
    users: list[UserCreateItem]


class UserBulkUpdateSchema(BaseModel):
    """Схема для bulk update пользователей"""
    user_ids: list[int] = Field(..., description="ID пользователей для операции")
    action: Literal['activate', 'deactivate', 'reset_traffic'] = Field(..., description="Действие: activate | deactivate | reset_traffic")


class UserBulkDeleteSchema(BaseModel):
    """Схема для bulk delete пользователей"""
    user_ids: list[int]
