from datetime import datetime

from pydantic import BaseModel, field_validator
from pydantic_core.core_schema import ValidationInfo

from bot.config_dir.config import env


class UserSubSchema(BaseModel):
    id: int
    b64_id: str
    sub_plan_id: int
    title: str
    is_active: bool
    is_limited: bool

    infinite_expire: bool
    expire_date: datetime | str
    created_at: datetime

    infinite_traffic: bool
    traffic_used_day: int
    traffic_limit_day: int | None |str
    traffic_used: int
    traffic_limit: int | None | str

    sub_link: str = None
    status: str = None

    @field_validator('expire_date', mode='after')
    @classmethod
    def validate_expire_date(cls, v: datetime, info: ValidationInfo):
        if info.data['infinite_expire']:
            return '♾️'
        return v.strftime('%d-%m-Y %H:%M')

    @field_validator('traffic_limit_day', mode='after')
    @classmethod
    def validate_traffic_limit_day(cls, v: datetime, info: ValidationInfo):

        if info.data['infinite_traffic']:
            return '♾️'
        # Если None, ограничение не включено
        # Но может быть общий лимит, так что _; не ♾️
        return v or '_'

    @field_validator('traffic_limit', mode='after')
    @classmethod
    def validate_traffic_limit(cls, v: datetime, info: ValidationInfo):
        if info.data['infinite_traffic']:
            return '♾️'
        # Если None, ограничение не включено
        # При этом может быть ежедневный лимит, так что _; не ♾️
        return v or '_'


    @field_validator('sub_link', mode='after')
    @classmethod
    def validate_b64_id(cls, v, info: ValidationInfo):
        return f'{env.sub_service_url}/sub/{info.data['b64_id']}'

    @field_validator('status', mode='after')
    @classmethod
    def validate_is_limited(cls, v, info: ValidationInfo):
        status = '🔴 Приостановлена'

        if info.data['is_active']:
            status = '🟢 Активна'

        if info.data['is_limited']:
            status = '🟠 Ограничена'
        return status

    @classmethod
    def fast_create(cls, us: dict) -> "UserSubSchema":
        """Преобразует сырой словарь БД в формат схемы и валидирует его."""
        mapped_data = {
            "id": us["user_sub_id"],
            "b64_id": us["b64_id"],
            "sub_plan_id": us["sub_plan_id"],
            "title": us["title"],
            "is_active": us["is_active"],
            "is_limited": us["is_limited"],
            "traffic_used_day": us["traffic_day_used"],
            "traffic_limit_day": us["traffic_day_limit"],
            "traffic_used": us["traffic_used"],
            "traffic_limit": us["traffic_limit"],
            "infinite_expire": us["infinite_expire"],
            "infinite_traffic": us["infinite_traffic"],
            "expire_date": us["expire_date"],
            "created_at": us["created_at"],
        }
        return cls.model_validate(mapped_data)
