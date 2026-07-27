from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from bot.config_dir.config import bot
from bot.config_dir.logger_config import log_event
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.handlers.start import start_handler
from bot.core.handlers.subscriptions_shop import UserSubscriptions, ShopSubscriptions


async def callback_factory(call: CallbackQuery, redis: Redis, state: FSMContext, aio_http: SubServiceConn):
    call_data = call.data
    tg_id = call.from_user.id
    mess_id = call.message.message_id

    if call_data == 'back':
        await bot.delete_message(call.message.chat.id, mess_id)
        # Передаём CallbackQuery вместо call.message, чтобы получить данные пользователя
        await start_handler(call, redis, aio_http)

    # Раздел Подписок магазина
    elif call_data == 'subs-shop-intro':
        "Отобразить слайдер подписок провайдера ('➕ Купить новую')"
        # Вызываем хендлер, который выдаёт каталог тарифных планов
        await ShopSubscriptions.shop_subscriptions_slider(call, redis, aio_http)


    elif call_data.startswith('subs-shop-pagen'):
        "Перемещение по слайдеру подписок пользователя (слайдер нажатия '➕ Купить новую')"
        # нажатия на стрелочки "<", ">"
        sub_plan_idx = int(call_data.split('_')[1])
        text, kb = await ShopSubscriptions.build_shop_plans_slider_msg(sub_plan_idx, call, redis)

        if text and kb:
            await call.message.edit_text(text, reply_markup=kb)
            log_event(f'[Call Center] Тарифы магазина. Обновили слайдер | tg_id: \033[35m{tg_id}\033[0m')


    elif call_data.startswith('subs-shop-offer'):
        "Обработка выбранного предложения. Выдаём ссылку на оплату"
        call_data_split = call_data.split('_')
        sub_plan_idx, offer_idx = int(call_data_split[1]), int(call_data_split[2])

        text, kb = await ShopSubscriptions.give_issued_payment(call, redis, aio_http, sub_plan_idx, offer_idx)
        # 1. В случае пропажи подписок в state слайдер отобразится снова
        # 2. Сообщение об ошибке формирования заказа
        if text:
            log_event(f"Выдали ссылку на оплату. Покупка тарифного плана из магазина | tg_id: \033[33m{tg_id}\033[0m")
            await call.message.edit_text(text, reply_markup=kb)



    # Раздел подписок пользователя
    elif call_data == 'subs-upd-intro':
        "Отобразить слайдер подписок для продления"
        await UserSubscriptions.user_subscriptions_slider(call, redis, state, aio_http)


    elif call_data.startswith('subs-user-pagen'):
        "Перемещение по слайдеру подписок пользователя (слайдер нажатия '🔄 Продлить')"
        # нажатия на стрелочки "<", ">"
        user_sub_idx = int(call_data.split('_')[1])
        text, kb = await UserSubscriptions.build_user_subs_slider_msg(user_sub_idx, call, state)

        # В случае пропажи подписок в state слайдер отобразится снова
        if text and kb:
            log_event(f'[Call Center] Подписки пользователя. Обновили слайдер | tg_id: \033[32m{tg_id}\033[0m')
            await call.message.edit_text(text, reply_markup=kb)


    elif call_data.startswith('subs-user-upd'):
        "Продление подписки после нажатия '🔄 Продлить' в подписке слайдера. Отображаем предложения по подписке"
        user_sub_idx = int(call_data.split('_')[1])
        text, kb = await UserSubscriptions.show_price_offers(user_sub_idx, redis, call, state, aio_http)

        # В случае пропажи подписок в state слайдер отобразится снова
        if text and kb:
            log_event(f"Отобразили предложения для продления подписки пользователя | tg_id: \033[36m{tg_id}\033[0m")
            await call.message.edit_text(text, reply_markup=kb)


    elif call_data.startswith('subs-user-offer'):
        "Обработка выбранного предложения. Выдаём ссылку на оплату"
        call_data_split = call_data.split('_')
        user_sub_idx, offer_idx = int(call_data_split[1]), int(call_data_split[2])

        text, kb = await UserSubscriptions.give_issued_payment(call, redis, state, aio_http, user_sub_idx, offer_idx)
        # 1. В случае пропажи подписок в state слайдер отобразится снова
        # 2. Сообщение об ошибке формирования заказа
        if text:
            log_event(f"Выдали ссылку на оплату. Продление из подписок пользователя | tg_id: \033[31m{tg_id}\033[0m")
            await call.message.edit_text(text, reply_markup=kb)


    await call.answer()