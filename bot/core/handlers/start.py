from datetime import datetime

from aiogram.types import ReplyKeyboardRemove, Message
from redis.asyncio import Redis

from bot.config_dir.config import bot, env
from bot.core.handlers.commands import set_commands
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.utils.keyboards import main_kb
from bot.core.utils.rate_limiter import rate_limit
from bot.config_dir.logger_config import log_event


async def on_startup():
    log_event('Бот запущен', level='WARNING')
    await bot.send_message(env.admin_id, 'Бот запущен!', reply_markup=ReplyKeyboardRemove())


@rate_limit(env.user_req_limit, env.user_req_window_seconds)
async def start_handler(message: Message, redis: Redis, aio_http: SubServiceConn):
    """Запрос на сохранение пользователя + Приветствие"""
    # Сохраняем пользователя
    ok, user_data = await aio_http.users.save_user(message.from_user.id, message.from_user.username, return_data=True)

    # Рендерим сообщение с автоматической подстановкой плейсхолдеров
    text = env.message_templates.render('message_start', message,
        user_sub_count=user_data.get('sub_count', 0),
        user_registered_date=user_data.get('registered_at', datetime.now()).strftime('%d-%m-%Y %H:%M'),
    )
    
    await message.answer(text, reply_markup=main_kb())
    await set_commands(bot)


async def helping(message: Message):
    text = env.message_templates.render('message_help', message)
    await message.answer(text)