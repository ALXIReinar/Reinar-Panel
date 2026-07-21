from dataclasses import dataclass
from typing import Literal

from bot.config_dir.config import env


class RedisKeys:
    @staticmethod
    def rate_limit(tg_id: str | int) -> str:
        return f'{env.app_mode}:{env.service_name}:rate_limit:user:tg_id={tg_id}:v1'


@dataclass
class MessageTemplates:
    start_msg: str = '''
    Добро пожаловать, {}!
    
    Этот бот может распознавать текст с картинок!
    Отправьте боту фото, выберите на каком языке изображён текст и дождитесь обработки изображения
    
    /profile - Покажет статистику и статус подписки
    /help - Помощь
    /history - Выдаст меню с историей изображений
    '''

    help_msg: str = '''
    Помощь.ехе
    '''