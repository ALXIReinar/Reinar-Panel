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
    sub_nodes_count: int = 0
    offer_prices: list[dict]

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
        if isinstance(v, int):
            return v // 1024
        # Но может быть общий лимит, так что _; не ♾️
        return '-'

    @field_validator('traffic_limit', mode='after')
    @classmethod
    def validate_traffic_limit(cls, v: datetime, info: ValidationInfo):
        if info.data['infinite_traffic']:
            return '♾️'

        # Если None, ограничение не включено
        if isinstance(v, int):
            return v // 1024
        # Но может быть общий лимит, так что _; не ♾️
        return '-'


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
            "traffic_used_day": us["traffic_used_day_mb"],
            "traffic_limit_day": us["traffic_limit_day"],
            "traffic_used": us["used_mb"],
            "traffic_limit": us["used_mb_limit"],
            "infinite_expire": us["infinite_expire"],
            "infinite_traffic": us["infinite_traffic"],
            "expire_date": us["expire_date"],
            "created_at": us["created_at"],
            "sub_nodes_count": us["sub_nodes_count"],
            "offer_prices": us["offer_prices"],
        }
        return cls.model_validate(mapped_data)


class ShopSubSchema(BaseModel):
    id: int
    title: str
    description: str
    offer_prices: list[dict]
    sub_nodes_count: int = 0


    @classmethod
    def fast_create(cls, us: dict) -> "ShopSubSchema":
        """Преобразует сырой словарь БД в формат схемы и валидирует его."""
        mapped_data = {
            "id": us["id"],
            "title": us["title"],
            "description": us["description"],
            "sub_nodes_count": us["sub_nodes_count"],
            "offer_prices": us["offer_prices"],
        }
        return cls.model_validate(mapped_data)


class SubOfferSchema(BaseModel):
    id: int
    cost: int
    ttl_days: int
    traffic_limit_day: int | str | None
    traffic_limit: int | str | None
    infinite_traffic: bool
    infinite_expire: bool

    field_validator('cost', mode='after')
    @classmethod
    def transform_cost(cls, v):
        return f'{v / 100: .2f}'

    @field_validator('ttl_days', mode='after')
    @classmethod
    def validate_expire_date(cls, v, info: ValidationInfo):
        if info.data['infinite_expire']:
            return '♾️'
        return v

    @field_validator('traffic_limit_day', mode='after')
    @classmethod
    def validate_traffic_limit_day(cls, v: datetime, info: ValidationInfo):

        if info.data['infinite_traffic']:
            return '♾️'

        # Если None, ограничение не включено
        if isinstance(v, int):
            return v // 1024
        # Но может быть общий лимит, так что _; не ♾️
        return '-'

    @field_validator('traffic_limit', mode='after')
    @classmethod
    def validate_traffic_limit(cls, v: datetime, info: ValidationInfo):
        if info.data['infinite_traffic']:
            return '♾️'

        # Если None, ограничение не включено
        if isinstance(v, int):
            return v // 1024
        # Но может быть общий лимит, так что _; не ♾️
        return '-'

    @classmethod
    def fast_create(cls, so: dict) -> "SubOfferSchema":
        """
        so - json объект из столбца "offer_price" sql-запроса на пользовательские подписки
        """
        mapped_data = {
            "id": so["offer_id"],
            "cost": so["cost"],
            "ttl_days": so["ttl_days"],
            "traffic_limit_day": so["traffic_day_limit"],
            "traffic_limit": so["traffic_limit"],
            "infinite_expire": so["infinite_expire"],
            "infinite_traffic": so["infinite_traffic"],
        }
        return cls.model_validate(mapped_data)