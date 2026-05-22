from typing import Optional

from pydantic import BaseModel, Field


class CreateRoboPayLinkSchema(BaseModel):
    user_id: int
    sub_plan_id: int
    ttl_days: int
    amount: int = Field(description='Стоимость подписки в копейках')
    description: str = Field(description='Описание для окна платежа. Например, тарифный план подписки')


class WebhookRoboPayload(BaseModel):
    OutSum: str = Field(description="Сумма (Робокасса присылает строкой, например '150.00')")
    InvId: int = Field(description="ID заказа")
    SignatureValue: str = Field(description="Хеш от Робокассы для проверки")

    Shp_user_id: int = Field(description="Кастомный параметр пользователя")
    Shp_csrf_token: str = Field(description='Токен для идемпотентной обработки платежа')
    Shp_sub_plan_id: int = Field(description='Приобретённый тарифный план')
    Shp_ttl_days: int = Field(description='Срок действия подписки в днях')

    # Эти поля Робокасса шлет опционально
    # Fee: Optional[str] = None
    # PaymentMethod: Optional[str] = None