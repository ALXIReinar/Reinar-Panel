from typing import Any
from aiogram.types import Message


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
