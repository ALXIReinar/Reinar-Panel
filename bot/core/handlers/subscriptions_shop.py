from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config_dir.config import env
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.utils.keyboards import subs_intro_kb, fallback_user_subs, user_subs_slider
from bot.core.utils.schemas import UserSubSchema


async def subscription_introduction(message: Message):
    text = env.message_templates.render('message_subscriptions_intro', message)
    await message.answer(text, reply_markup=subs_intro_kb())


async def user_subscriptions_slider(message: Message, state: FSMContext, aio_http: SubServiceConn):
    user_subs = await aio_http.user_subs.all(message.from_user.id)

    "Фоллбек. Нет подписок - не можем отобразить слайдер"
    if not user_subs:
        await message.answer('У Вас нет ни одной подписки', reply_markup=fallback_user_subs())
        return

    "Сохраняем подписки, отображаем слайдер"
    await state.update_data(user_subs=user_subs)

    text, kb = await build_user_subs_slider_msg(0, message, state)
    await message.answer(text, reply_markup=kb)


async def build_user_subs_slider_msg(slider_idx: int, message: Message, state: FSMContext) -> tuple:
    """"""
    "Получаем подписки"
    user_subs = (await state.get_data()).get('user_subs')
    if not user_subs:
        return None, None

    "Отображаем слайдер"
    us = user_subs[slider_idx]
    us_preview = UserSubSchema.fast_create(us)

    text = env.message_templates.render('message_subscriptions_user_extent', message, us_preview)
    kb = user_subs_slider(slider_idx, len(user_subs))
    return text, kb