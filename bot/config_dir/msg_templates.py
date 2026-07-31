from typing import Any, Union

from aiogram.types import Message, CallbackQuery
from pydantic import BaseModel, Field, ConfigDict

from bot.core.utils.placeholders import PlaceholderResolver
from bot.core.utils.schemas import UserSubSchema, SubOfferSchema, ShopSubSchema, UserSchema


class MessageTemplates(BaseModel):
    message_start: str = Field(description='Ответ бота на команду /start')
    message_profile: str
    message_about: str
    message_help: str

    message_subscriptions_shop_intro: str
    message_subscriptions_shop_extent: str

    message_user_profile_subs_intro: str
    message_subscriptions_user_extent: str

    message_subscriptions_offers_intro: str
    message_subscriptions_offers_extent: str

    message_pay_window: str

    model_config = ConfigDict(str_max_length=4096)

    def render(
            self,
            template_name: str,
            event: Union[Message, CallbackQuery, None] = None,
            user_sub: UserSubSchema = None,
            shop_plan: ShopSubSchema = None,
            sub_plan_offer: SubOfferSchema = None,
            user: UserSchema = None,
            **custom: Any
    ) -> str:
        """
        Рендерит шаблон с подстановкой плейсхолдеров.
        
        Автоматически извлекает данные из Message/CallbackQuery (USER_TG_ID, USER_TG_FIRST_NAME и т.д.)
        и позволяет добавить кастомные плейсхолдеры через kwargs.
        
        Args:
            template_name: Имя атрибута шаблона (например 'message_start')
            event: aiogram Message или CallbackQuery объект для автоматического парсинга (опционально)
            user_sub: Объект подписки пользователя (опционально)
            shop_plan: Объект тарифного плана из магазина (опционально)
            sub_plan_offer: Объект оффера тарифа (опционально)
            user: Объект пользователя (опционально)
            **custom: Дополнительные плейсхолдеры (например user_api_sub_count=5)
            
        Example:
            # Только Message
            text = msg_tmps.render('message_start', message)
            
            # CallbackQuery (правильно извлечёт USER_TG_* из callback.from_user)
            text = msg_tmps.render('message_start', callback)
            
            # Message + кастомные данные
            text = msg_tmps.render('message_start', message, user_api_sub_count=3)
            
            # Только кастомные данные
            text = msg_tmps.render('admin_notify', admin_name='Иван', status='OK')
        """
        
        template = getattr(self, template_name)
        resolver = PlaceholderResolver()
        
        if event:
            if isinstance(event, Message):
                resolver.add_message(event)
            elif isinstance(event, CallbackQuery):
                resolver.add_callback(event)

        if user_sub:
            resolver.add_user_sub(user_sub)

        if shop_plan:
            resolver.add_shop_plan(shop_plan)

        if sub_plan_offer:
            resolver.add_price_offer(sub_plan_offer)

        if user:
            resolver.add_user(user)

        if custom:
            resolver.add_custom(**custom)
        
        return resolver.resolve(template)