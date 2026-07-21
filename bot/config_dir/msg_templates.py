from typing import Any

from aiogram.types import Message
from pydantic import BaseModel, Field, ConfigDict

from bot.core.utils.placeholders import PlaceholderResolver


class MessageTemplates(BaseModel):
    message_start: str = Field(description='Ответ бота на команду /start')

    model_config = ConfigDict(str_max_length=4096)

    def render(self, template_name: str, message: Message = None, **custom: Any) -> str:
        """
        Рендерит шаблон с подстановкой плейсхолдеров.
        Автоматически извлекает данные из Message (USER_TG_ID, USER_TG_FIRST_NAME и т.д.)
        и позволяет добавить кастомные плейсхолдеры через kwargs.
        
        Args:
            template_name: Имя атрибута шаблона (например 'message_start')
            message: aiogram Message объект для автоматического парсинга (опционально)
            **custom: Дополнительные плейсхолдеры (например user_api_sub_count=5)
            
        Example:
            # Только Message
            text = msg_tmps.render('message_start', message)
            
            # Message + кастомные данные
            text = msg_tmps.render('message_start', message, user_api_sub_count=3)
            
            # Только кастомные данные
            text = msg_tmps.render('admin_notify', admin_name='Иван', status='OK')
        """
        
        template = getattr(self, template_name)
        resolver = PlaceholderResolver()
        
        if message:
            resolver.add_message(message)
        
        if custom:
            resolver.add_custom(**custom)
        
        return resolver.resolve(template)