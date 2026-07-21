from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from bot.config_dir.config import env
from bot.core.api.aiohttp_conn import ApiServerConn
from bot.core.utils.rate_limiter import rate_limit


@rate_limit(env.user_req_limit, env.user_req_window_seconds)
async def callback_factory(call: CallbackQuery, redis: Redis, state: FSMContext, aio_http: ApiServerConn):
    call_data = call.data

    if call_data.startswith('history-next'):
        # нажатие на стрелочку ">>>", перелистнуть страницу
        ...

    elif call_data.startswith('history-prev'):
        # нажатие на стрелочку "<<<", перелистнуть страницу
        ...

    elif call_data.startswith('history'):
        # по задумке, "отобразить сообщение с фоткой, текстом, оценкой пользователя(если есть), время"
        ...

    await call.answer()