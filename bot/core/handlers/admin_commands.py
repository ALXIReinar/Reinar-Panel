from typing import Callable, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message
from redis.asyncio import Redis

from bot.config_dir.config import env
from bot.config_dir.logger_config import log_event
from bot.core.utils.anything import admin_commands, RedisKeys


class MiddlewareAdmin(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        """"""

        "Скоуп только на команды"
        if not event.text.startswith("/"):
            return await handler(event, data)

        "Если команда админская, но стучится не админ"
        command = event.text.split()[0]
        if command in admin_commands and event.from_user.id != env.admin_tg_id:
            log_event(f'Несанкционированный доступ к админ-командам | tg_id: \033[31m{event.from_user.id}\033[34m; username: \033[35m{event.from_user.username}\033[0m', level='WARNING')
            await event.answer('Операция доступна только администратору')
            return None

        "Допуск команды"
        return await handler(event, data)


async def reset_req_limit(message: Message, redis: Redis):
    inp_text = message.text.split()

    user_tg_id = int(inp_text[1]) if len(inp_text) == 2 and inp_text[1].isdigit() else None
    if not user_tg_id:
        await message.answer(f'❌ Не выполнено. Введите корректный числовой <b>tg_id</b> пользователя после команды')
        return

    res = await redis.delete(RedisKeys.rate_limit(user_tg_id))
    text = f'✅ Выполнено. Лимит запросов для пользователя <code>{user_tg_id}</code> сброшен'
    if not res:
        text = f'❌ Не выполнено. Пользователь с таким id не существует в Redis. <code>{user_tg_id}</code>'

    log_event(f'\033[31m[Admin Command]\033[0m Сброс блокировки по запросам | success: \033[34m{bool(res)}\033[0m; user_tg_id: \033[35m{user_tg_id}\033[0m; admin_id: \033[31m{message.from_user.id}\033[0m', level='WARNING')
    await message.answer(text)


async def flush_shop_cache(message: Message, redis: Redis):
    res = await redis.delete(RedisKeys.shop_sub_plans)
    text = f'✅ Выполнено. Кэш тарифных планов магазина очищен'
    if not res:
        text = f'❌ Не выполнено. Ключ тарифных планов не найден в Redis'

    log_event(f'\033[31m[Admin Command]\033[0m Команда очистки кэша магазина | success: \033[34m{bool(res)}\033[0m; admin_id: \033[31m{message.from_user.id}\033[0m', level='WARNING')
    await message.answer(text)