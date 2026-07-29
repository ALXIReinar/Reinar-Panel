from functools import wraps
from typing import Union
from redis.asyncio import Redis
from aiogram.types import Message, CallbackQuery

from bot.core.utils.anything import RedisKeys


def rate_limit(max_requests: int = 25, window_seconds: int = 60):
    """
    Декоратор для ограничения пользовательских запросов на APIService. Ограничение происходит по tg_id
    Использовать на бот-хэндлерах с aio_http соединением
    ВАЖНО! Необходимо указывать аргумент redis в бот-хендлере с этим декоратором
    ВАЖНО! Необходимо передавать redis вторым позиционным аргументом!
    
    Поддерживает как Message, так и CallbackQuery.
    Приоритет извлечения user_id: CallbackQuery.from_user > Message.from_user

    Пример использования:
        @rate_limit(max_requests=5, window_seconds=60)
        async def my_handler(message: Message, redis: Redis, ...):
            ...
        
        @rate_limit(max_requests=5, window_seconds=60)
        async def my_callback(callback: CallbackQuery, redis: Redis, ...):
            ...
    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(event: Union[Message, CallbackQuery], redis: Redis, *args, **kwargs):
            # Извлекаем user_id в зависимости от типа события
            user_id = event.from_user.id
            
            key = RedisKeys.rate_limit(user_id)

            "Редис транзакция"
            pipe = await redis.pipeline()

            pipe.incr(key)
            pipe.expire(key, window_seconds)

            results = await pipe.execute()

            current_count = results[0]  # ответ от инкремента
            if current_count > max_requests:
                warning_message = f"⏳ Слишком много запросов. Подождите некоторое время"
                
                # Отправляем предупреждение в зависимости от типа события
                if isinstance(event, Message):
                    await event.answer(warning_message)
                elif isinstance(event, CallbackQuery):
                    await event.answer(warning_message, show_alert=True)
                
                return

            return await handler(event, redis, *args, **kwargs)
        return wrapper
    return decorator
