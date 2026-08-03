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


class UserSubUpdItem(BaseModel):
    """
    Такие поля как ... Не принимаются т.к.
    - sub_plan_id -
        смена sub_plan_id означает одновременное удаление и вставку новой подписки,
        но с тем же user_sub_id. По факту это миграция впн пользователей с одних нод на другие
        Слишком сложно и неприятно. Куда надёжнее и проще будет удалить и добавить подписку с другим sub_plan_id
        через add,delete функционал. Требует возни с arq - не задумано для операции обновления
    - uuid - его изменение в созданной подписке - потеря связи с впн-ядрами. Они не разберут, кто это. Это primary_key для впн-ядер
    - is_active, is_limited - та же ерунда. Возня с арком, функционал для изменения этих флагов есть
    """
    user_sub_id: int
    b64_id: Optional[str] = Field(None, max_length=90, min_length=10)
    order_id: int | None = Field(0, ge=0)
    traffic_used_day_mb: Optional[int] = None
    traffic_limit_day_mb: int | None = Field(0, ge=0)
    traffic_used_mb: Optional[int] = None
    traffic_limit_mb: int | None = Field(0, ge=0)
    infinite_traffic: Optional[bool] = None
    expire_date: Optional[datetime] = None
    infinite_expire: Optional[bool] = None

class UserSubAddItem(BaseModel):
    b64_id: str = Field(max_length=90, min_length=10)
    uuid: str = Field(max_length=36)
    order_id: Optional[int] = None
    sub_plan_id: int
    traffic_used_day_mb: Optional[int] = None
    traffic_limit_day_mb: Optional[int] = None
    traffic_used_mb: Optional[int] = None
    traffic_limit_mb: Optional[int] = None
    infinite_traffic: bool
    expire_date: Optional[datetime] = None
    infinite_expire: bool
    is_active: Optional[bool] = None
    is_limited: Optional[bool] = None

class UserSubsUpdateSchema(BaseModel):
    user_subs_to_delete: Optional[list[int]] = Field([])
    user_subs_to_add: Optional[list[UserSubAddItem]] = Field([])
    user_subs_to_update: Optional[list[UserSubUpdItem]] = Field([])
