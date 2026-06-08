from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class SubUrlSchema(BaseModel):
    b64_id: str = Field(min_length=16, max_length=90)


class CreateRoboPayLinkSchema(BaseModel):
    user_id: int
    sub_plan_id: int
    ttl_days: int
    amount: str = Field(description='Стоимость подписки в рублях')
    description: str = Field(description='Описание для окна платежа. Например, тарифный план подписки')


class WebhookRoboPayload(BaseModel):
    """
    Пример тела(формы) запроса от Робокассы

    OutSum='345.00',
    InvId=37,
    SignatureValue='178a931e0ebd63530c7377999e45c4f1826a361e7180db9c4d0d206f34445108',
    Shp_user_id=1,
    Shp_csrf_token='NCHwWjvxh97Ml6vyh0HW-w',
    Shp_sub_plan_id=1,
    Shp_expire_date=datetime.datetime(2026, 8, 15, 6, 51, 4, 820826, tzinfo=TzInfo(0)),
    IsTest='1',
    Culture='ru'
    """
    OutSum: str = Field(description="Сумма (Робокасса присылает строкой, например '150.00')")
    InvId: int = Field(description="ID заказа")
    SignatureValue: str = Field(description="Хеш от Робокассы для проверки")

    Shp_user_id: int = Field(description="Кастомный параметр пользователя")
    Shp_csrf_token: str = Field(description='Токен для идемпотентной обработки платежа')
    Shp_sub_plan_id: int = Field(description='Приобретённый тарифный план')
    Shp_expire_date: datetime = Field(description='Дата окончания действия подписки')

    model_config = ConfigDict(extra='allow')
    # Эти поля Робокасса шлет опционально
    # Fee: Optional[str] = None
    # PaymentMethod: Optional[str] = None