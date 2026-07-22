from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from bot.config_dir.config import env, bot
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.handlers.start import start_handler
from bot.core.handlers.subscriptions_shop import build_user_subs_slider_msg, user_subscriptions_slider
from bot.core.utils.keyboards import user_sub_plan_offers, payment_kb
from bot.core.utils.rate_limiter import rate_limit
from bot.core.utils.schemas import UserSubSchema


@rate_limit(env.user_req_limit, env.user_req_window_seconds)
async def callback_factory(call: CallbackQuery, redis: Redis, state: FSMContext, aio_http: SubServiceConn):
    call_data = call.data
    chat_id = call.message.chat.id
    mess_id = call.message.message_id

    if call_data == 'back':
        await bot.delete_message(chat_id, mess_id)
        await start_handler(call.message, redis, aio_http)

    elif call_data == 'subs-shop':
        # Вызываем хендлер, который выдаёт каталог тарифных планов
        ...

    elif call_data.startswith('subs-user-pagen'):
        "Перемещение по слайдеру"
        # нажатия на стрелочки "<", ">"
        user_sub_idx = int(call_data.split('_')[1])
        text, kb = await build_user_subs_slider_msg(user_sub_idx, call.message, state)
        await call.message.edit_text(text, reply_markup=kb)

    elif call_data.startswith('subs-user-upd'):
        "Продление подписки"
        # Продление подписки. Должны отдать ссылку на оплату
        user_sub_idx = int(call_data.split('_')[1])
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            await user_subscriptions_slider(call.message, state, aio_http)
        else:
            costs_days = user_subs[user_sub_idx]['price_offers']
            us_preview = UserSubSchema.fast_create(user_subs[user_sub_idx])

            text = env.message_templates.render('message_user_subscription_extent', call.message, us_preview)
            await call.message.edit_text(text, reply_markup=user_sub_plan_offers(user_sub_idx, costs_days))

    elif call_data.startswith('subs-user-offer'):
        *_, user_sub_idx, offer_idx = call.data.split('_')
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            await user_subscriptions_slider(call.message, state, aio_http)
        else:
            "Запрос на формирование заказа, получим ссылку для оплаты"
            selected_sub = UserSubSchema.fast_create(user_subs[user_sub_idx])
            price_offer = selected_sub['price_offers'][offer_idx]

            order_success, payment_link = await aio_http.user_subs.get_payment_link(
                call.message.from_user.id,
                selected_sub.sub_plan_id,
                price_offer['cost'],
                price_offer['ttl_days']
            )
            if not order_success:
                await call.message.edit_text('Не удалось сформировать заказ. Попробуйте позже')
                await call.answer()
                return

            text = env.message_templates.render('message_pay_window', call.message, selected_sub,
                pay_amount=price_offer['cost']
            )
            await call.message.edit_text(text, reply_markup=payment_kb(payment_link))




    await call.answer()