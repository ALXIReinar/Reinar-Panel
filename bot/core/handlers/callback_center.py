from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from bot.config_dir.config import bot
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.handlers.start import start_handler
from bot.core.handlers.subscriptions_shop import UserSubscriptions




async def callback_factory(call: CallbackQuery, redis: Redis, state: FSMContext, aio_http: SubServiceConn):
    call_data = call.data
    chat_id = call.message.chat.id
    mess_id = call.message.message_id

    if call_data == 'back':
        await bot.delete_message(chat_id, mess_id)
        await start_handler(call.message, redis, aio_http)

    elif call_data == 'subs-shop':
        "Отобразить слайдер подписок провайдера ('➕ Купить новую')"
        # Вызываем хендлер, который выдаёт каталог тарифных планов
        ...

    elif call_data == 'subs-upd-intro':
        "Отобразить слайдер подписок для продления"
        await UserSubscriptions.user_subscriptions_slider(call.message, state, aio_http)

    elif call_data.startswith('subs-user-pagen'):
        "Перемещение по слайдеру подписок пользователя (слайдер нажатия '🔄 Продлить')"
        # нажатия на стрелочки "<", ">"
        user_sub_idx = int(call_data.split('_')[1])
        text, kb = await UserSubscriptions.build_user_subs_slider_msg(user_sub_idx, call.message, state)
        await call.message.edit_text(text, reply_markup=kb)

    elif call_data.startswith('subs-user-upd'):
        "Продление подписки после нажатия '🔄 Продлить' в подписке слайдера. Отображаем предложения по подписке"
        user_sub_idx = int(call_data.split('_')[1])
        text, kb = await UserSubscriptions.show_price_offers(user_sub_idx, call.message, state, aio_http)

        # В случае пропажи подписок в state слайдер отобразится снова
        if text and kb:
            await call.message.edit_text(text, reply_markup=kb)

    elif call_data.startswith('subs-user-offer'):
        "Обработка выбранного предложения. Выдаём ссылку на оплату"
        call_data_split = call_data.split('_')
        user_sub_idx, offer_idx = int(call_data_split[1]), int(call_data_split[2])

        text, kb = UserSubscriptions.give_issued_payment(user_sub_idx, offer_idx, call.message, state, aio_http)
        # 1. В случае пропажи подписок в state слайдер отобразится снова
        # 2. Сообщение об ошибке формирования заказа
        if text:    
            await call.message.edit_text(text, reply_markup=kb)


    await call.answer()