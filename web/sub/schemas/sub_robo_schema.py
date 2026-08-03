from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator


class SubUrlSchema(BaseModel):
    b64_id: str = Field(min_length=16, max_length=90)


class CreateRoboPayLinkSchema(BaseModel):
    user_id: Optional[int] = None
    tg_id: Optional[int] = None
    sub_plan_id: int
    offer_id: int
    description: str = Field(description='Описание для окна платежа. Например, тарифный план подписки')

    @model_validator(mode="after")
    def validate_user_or_tg_id(self):
        # Логика: только одно из двух полей должно быть заполнено
        has_user_id = self.user_id is not None
        has_tg_id = self.tg_id is not None

        if not (has_user_id ^ has_tg_id):  # Оператор XOR (исключающее ИЛИ)
            raise ValueError("Необходимо указать строго одно из полей: 'user_id' или 'tg_id'.")

        return self


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
    Shp_offer_id: int = Field(description='ID предложения по подписке')

    model_config = ConfigDict(extra='allow')
    # Эти поля Робокасса шлет опционально
    # Fee: Optional[str] = None
    # PaymentMethod: Optional[str] = None