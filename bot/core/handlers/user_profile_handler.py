from datetime import datetime

from aiogram.types import Message
from redis.asyncio import Redis

from bot.config_dir.config import env
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.utils.keyboards import profile_kb
from bot.core.utils.rate_limiter import rate_limit


@rate_limit(env.user_req_limit, env.user_req_window_seconds)
async def show_user_profile(message: Message, redis: Redis, aio_http: SubServiceConn):
    _, user_info = await aio_http.users.get_user_info(message.from_user.id)
    text = env.message_templates.render('message_profile', message,
        user_sub_count=user_info.get('sub_count', 0),
        user_registered_date=user_info.get('registered_at', datetime.now()).strftime('%d-%m-%Y %H:%M'),
    )
    await message.answer(text, reply_markup=profile_kb())