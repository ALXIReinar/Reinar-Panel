from typing import Any
from aiogram.types import Message

from bot.core.utils.schemas import UserSubSchema, ShopSubSchema, SubOfferSchema


class PlaceholderResolver:
    """
    Система подстановки плейсхолдеров в текстовые шаблоны.

    Поддерживает автоматический парсинг объектов aiogram (Message)
    и добавление кастомных плейсхолдеров.

    Пример использования:
        resolver = PlaceholderResolver()
        resolver.add_message(message).add_custom(user_api_sub_count=5)
        result = resolver.resolve(template)
    
    Поддерживает:
    - Автоматический парсинг Message (USER_TG_ID, USER_TG_USERNAME, etc.)
    - Добавление кастомных плейсхолдеров через add_custom()
    - Fluent API для цепочки вызовов
    
    Формат плейсхолдеров: {KEY_NAME}
    Пустые значения заменяются на пустую строку.
    """
    
    def __init__(self):
        self.context: dict[str, str] = {}
    
    def add_message(self, message: Message) -> 'PlaceholderResolver':
        """
        Автоматически извлекает данные из Message объекта.
        
        Доступные плейсхолдеры:
        - USER_TG_ID - Telegram ID пользователя
        - USER_TG_USERNAME - Username пользователя (без @)
        - USER_TG_FIRST_NAME - Имя пользователя
        - USER_TG_LAST_NAME - Фамилия пользователя
        
        Args:
            message: aiogram Message объект
        Returns:
            self для цепочки вызовов
        """
        if message and message.from_user:
            user = message.from_user
            self.context.update({
                'USER_TG_ID': user.id,
                'USER_TG_USERNAME': user.username or '',
                'USER_TG_FIRST_NAME': user.first_name or '',
                'USER_TG_LAST_NAME': user.last_name or '',
            })
        return self

    def add_user_sub(self, user_sub: UserSubSchema):
        """
        Автоматически извлекает данные из UserSubSchema.

        Доступные плейсхолдеры:
        - USER_SUB_ID - ID подписки пользователя
        - USER_SUB_PLAN_ID - ID тарифного плана
        - USER_SUB_TITLE/SUB_TITLE - название подписки, которое отображается в впн-клиенте пользователя
        - USER_SUB_STATUS - В зависимости от is_active, is_limited может быть: "🟢 Активна", "🔴 Приостановлена", "🟠 Ограничена"
        - USER_SUB_LINK - Ссылка на подписку, формируется из env:SUB_SERVICE_URL + /sub/{b64_id}
        - USER_SUB_B64 - b64_id подписки
        - USER_SUB_TRAFFIC_USED_DAY - Использовано трафика "сегодня"
        - USER_SUB_TRAFFIC_LIMIT_DAY - Лимит на ежедневный трафик. Если не включен, отображается _. Если безлимит - ♾️
        - USER_SUB_TRAFFIC_USED - всего использовано трафика подпиской
        - USER_SUB_TRAFFIC_LIMIT - Выделенная квота трафика на подписку. Если безлимит - ♾️
        - USER_SUB_EXPIRE - Дата истечения срока действия подписки. ♾️ если срок неограничен
        - USER_SUB_CREATED_AT - Дата истечения срока действия подписки. ♾️ если срок неограничен
        """
        self.context.update({
            'USER_SUB_ID': user_sub.id,
            'USER_SUB_PLAN_ID': user_sub.plan_id,
            'USER_SUB_TITLE': user_sub.title,
            'SUB_TITLE': user_sub.title,
            'USER_SUB_STATUS': user_sub.status,
            'USER_SUB_LINK': user_sub.sub_link,
            'USER_SUB_B64': user_sub.b64_id,
            'USER_SUB_TRAFFIC_USED_DAY': user_sub.traffic_used_day,
            'USER_SUB_TRAFFIC_LIMIT_DAY': user_sub.traffic_limit_day,
            'USER_SUB_TRAFFIC_USED': user_sub.traffic_used,
            'USER_SUB_TRAFFIC_LIMIT': user_sub.traffic_limit,
            'USER_SUB_EXPIRE': user_sub.expire,
            'USER_SUB_CREATED_AT': user_sub.created_at.strftime("%d-%m-%Y %H:%M"),
        })
        return self

    def add_shop_plan(self, shop_sub: ShopSubSchema):
        """
        Автоматически извлекает данные из ShopSubSchema.

        Доступные плейсхолдеры:
        - SUB_ID - sub_plan_id
        - USER_SUB_TITLE/SUB_TITLE - название подписки, которое отображается в впн-клиенте пользователя
        - SUB_DESCRIPTION - Описание тарифа. В нём можно подробнее описать тариф("Доступен безлимит, если купить подписку за 1000р" и т.п.)
        """
        self.context.update({
            'SUB_ID': shop_sub.id,
            'SUB_TITLE': shop_sub.title,
            'USER_SUB_TITLE': shop_sub.title,
            'SUB_DESCRIPTION': shop_sub.description,
        })
        return self

    def add_price_offer(self, offer: SubOfferSchema):
        """
        Автоматически извлекает данные из SubOfferSchema.

        Доступные плейсхолдеры:
        - SUB_COST - sub_plan_id
        - SUB_TTL_DAYS - Длительность подписки в днях после покупки/продления(прибавится к существующей подписке). ♾️ - если infinite_expire = true
        - SUB_TRAFFIC_LIMIT_DAY - лимит ГБ в день. Если None, то - (прочерк). Если infinite_traffic = true, то ♾️ НЕЗАВИСИМО от указанного значения.
        - SUB_TRAFFIC_LIMIT - Общий лимит ГБ. Если None, то - (прочерк). Если infinite_traffic = true, то ♾️ НЕЗАВИСИМО от указанного значения.
        """
        self.context.update({
            "SUB_COST": offer.cost,
            "SUB_TTL_DAYS": offer.ttl_days,
            "SUB_TRAFFIC_LIMIT_DAY": offer.traffic_limit_day,
            "SUB_TRAFFIC_LIMIT": offer.traffic_limit,
        })
        return self

    def add_custom(self, **kwargs: Any) -> 'PlaceholderResolver':
        """
        Добавляет кастомные плейсхолдеры.
        Ключи автоматически конвертируются в UPPER_CASE.
        Значения конвертируются в строки, None заменяется на ''.

        Returns:
            self для цепочки вызовов
            
        Example:
            resolver.add_custom(user_api_sub_count=5, server_name='prod')
            # Создаст плейсхолдеры {USER_API_SUB_COUNT} и {SERVER_NAME}
        """
        self.context.update({
            key.upper(): str(value) if value is not None else ''
            for key, value in kwargs.items()
        })
        return self


    def resolve(self, template: str) -> str:
        """
        Заменяет все плейсхолдеры {KEY} в шаблоне на значения из контекста.
        Плейсхолдеры, для которых нет значений, остаются без изменений.
        """
        result = template
        for key, value in self.context.items():
            placeholder = f'{{{key}}}'
            result = result.replace(placeholder, value)
        return result
