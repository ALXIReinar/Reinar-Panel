from aiogram.types import ReplyKeyboardRemove, Message
from redis.asyncio import Redis

from bot.config_dir.config import bot, env
from bot.core.handlers.commands import set_commands
from bot.core.api.aiohttp_conn import ApiServerConn
from bot.core.utils.anything import MessageTemplates
from bot.core.utils.rate_limiter import rate_limit
from bot.config_dir.logger_config import log_event


async def on_startup():
    log_event('Бот запущен', level='WARNING')
    await bot.send_message(env.admin_id, 'Бот запущен!', reply_markup=ReplyKeyboardRemove())


@rate_limit(env.user_req_limit, env.user_req_window_seconds)
async def start_handler(message: Message, redis: Redis, aio_http: ApiServerConn):
    """Запрос на сохранение пользователя + Приветствие"""
    # Сохраняем пользователя
    user_data = await aio_http.users.save_user(message.from_user.id, message.from_user.username, return_data=True)

    # Рендерим сообщение с автоматической подстановкой плейсхолдеров
    text = env.message_templates.render('message_start', message, user_api_sub_count=user_data['sub_count'])
    
    await message.answer(text)
    await set_commands(bot)


async def helping(message: Message):
    await message.answer(MessageTemplates.help_msg)