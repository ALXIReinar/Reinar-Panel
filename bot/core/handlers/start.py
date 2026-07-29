from datetime import datetime
from typing import Union

from aiogram.types import Message, CallbackQuery
from redis.asyncio import Redis

from bot.config_dir.config import bot, env
from bot.core.handlers.commands import set_commands
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.utils.keyboards import main_kb
from bot.core.utils.rate_limiter import rate_limit
from bot.config_dir.logger_config import log_event
from bot.core.utils.schemas import UserSchema


async def on_startup():
    log_event('Бот запущен', level='WARNING')
    await bot.send_message(env.admin_tg_id, 'Бот запущен!')


@rate_limit(env.user_req_limit, env.user_req_window_seconds)
async def start_handler(event: Union[Message, CallbackQuery], redis: Redis, aio_http: SubServiceConn):
    """Запрос на сохранение пользователя + Приветствие"""
    
    # Сохраняем пользователя
    ok, user_data = await aio_http.users.save_user(
        event.from_user.id, event.from_user.username, return_data=True
    )
    text = '🛠 Что-то пошло не так. Попробуйте позже'
    if ok:
        user_preview = UserSchema.fast_create(user_data)

        text = env.message_templates.render('message_start', event, user=user_preview)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=main_kb())
    else:  # CallbackQuery
        await event.message.answer(text, reply_markup=main_kb())
    
    await set_commands(bot)


async def helping(message: Message):
    text = env.message_templates.render('message_help', message)
    await message.answer(text)