from datetime import datetime

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


class UserUpdateSchema(BaseModel):
    tg_username: str | None = Field(None, max_length=32, min_length=5, description="Telegram username")
    tg_id: int | None = Field(None, gt=0)
    online_status: int | None = Field(None, ge=1, le=3, description="Online status: 1 - Not connect yet, 2 - Offline, 3 - Online")
    registered_at: datetime | None = None


class UserSubItem(BaseModel):
    user_sub_id: int
    order_id: Optional[int]
    sub_plan_id: Optional[int]
    traffic_used_day_mb: Optional[int]
    traffic_limit_day_mb: Optional[int]
    infinite_traffic: Optional[bool]
    expire_date: Optional[datetime]
    infinite_expire: Optional[bool]
    is_active: Optional[bool]
    is_limited: Optional[bool]

class UserSubsUpdateSchema(BaseModel):
    user_subs_to_delete: list[int]
    user_subs_to_add: list[UserSubItem]
    user_subs_to_update: list[UserSubItem]
