from pydantic import BaseModel, Field
from typing import Optional, Literal


class UserCreateItem(BaseModel):
    """Один пользователь для bulk insert"""
    tg_username: str = Field(..., max_length=32, description="Уникальный ник пользователя в ТГ")
    tg_id: Optional[int] = Field(None, description="Telegram ID (опционально)")


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
