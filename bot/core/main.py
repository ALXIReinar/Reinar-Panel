import asyncio

from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiohttp import ClientSession
from redis.asyncio import Redis

from bot.config_dir.config import bot, redis_settings, env
from bot.core.handlers.about_handler import show_about
from bot.core.handlers.callback_center import callback_factory
from bot.core.api.aiohttp_conn import SubServiceConn

from bot.core.handlers.start import helping, on_startup, start_handler
from bot.core.handlers.subscriptions_shop import subscriptions_introduction
from bot.core.handlers.user_profile_handler import show_user_profile

dp = Dispatcher()


async def main():
    """"""
    "AioHttp"
    aio_http_session = ClientSession(
        base_url=env.sub_service_url,
    )
    
    "Redis"
    redis_conn = Redis(**redis_settings, decode_responses=True)

    "Команды"
    dp.message.register(start_handler, Command('start'))
    dp.message.register(helping, Command('help'))

    dp.message.register(subscriptions_introduction, F.text == '💎 Купить/Продлить')
    dp.message.register(show_user_profile, F.text == '👤 Личный кабинет')
    dp.message.register(show_about, F.text == '🔗 Наши ссылки')

    "Коллбэки"
    dp.callback_query.register(callback_factory)

    dp.startup.register(on_startup)
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            aio_http=SubServiceConn(aio_http_session),
            redis=redis_conn
        )
    finally:
        await aio_http_session.close()
        await redis_conn.aclose()



if __name__ == '__main__':
    asyncio.run(main())