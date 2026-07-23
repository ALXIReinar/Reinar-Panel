from decimal import Decimal

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config_dir.config import env
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.utils.keyboards import subs_intro_kb, fallback_user_subs, user_subs_slider, user_sub_plan_offers, \
    payment_kb, shop_subs_slider, shop_sub_plan_offers
from bot.core.utils.schemas import UserSubSchema, SubOfferSchema, ShopSubSchema


async def subscriptions_introduction(message: Message):
    text = env.message_templates.render('message_subscription_user_intro', message)
    await message.answer(text, reply_markup=subs_intro_kb())


class UserSubscriptions:
    @staticmethod
    async def user_subscriptions_slider(message: Message, state: FSMContext, aio_http: SubServiceConn):
        user_subs = await aio_http.user_subs.all(message.from_user.id)

        "Фоллбек. Нет подписок - не можем отобразить слайдер"
        if not user_subs:
            await message.answer('У Вас нет ни одной подписки', reply_markup=fallback_user_subs())
            return

        "Сохраняем подписки, отображаем слайдер"
        await state.update_data(user_subs=user_subs)

        text, kb = await UserSubscriptions.build_user_subs_slider_msg(0, message, state)
        await message.answer(text, reply_markup=kb)

    @staticmethod
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

    @staticmethod
    async def show_price_offers(user_sub_idx: int, message: Message, state: FSMContext, aio_http: SubServiceConn):
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            await UserSubscriptions.user_subscriptions_slider(message, state, aio_http)
            return None, None

        costs_days = user_subs[user_sub_idx]['offer_prices']
        us_preview = UserSubSchema.fast_create(user_subs[user_sub_idx])

        text = env.message_templates.render('message_subscriptions_offers_intro', message, us_preview)
        kb = user_sub_plan_offers(user_sub_idx, costs_days)
        return text, kb

    @staticmethod
    async def give_issued_payment(user_sub_idx: int, offer_idx: int, message: Message, state: FSMContext, aio_http: SubServiceConn):
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            await UserSubscriptions.user_subscriptions_slider(message, state, aio_http)
            return None, None

        "Запрос на формирование заказа, получим ссылку для оплаты"
        selected_sub = UserSubSchema.fast_create(user_subs[user_sub_idx])
        price_offer = selected_sub['offer_prices'][offer_idx]

        cost = Decimal(price_offer['cost']) / Decimal('100')
        order_success, payment_link = await aio_http.sub_plans.api_get_payment_link(
            message.from_user.id,
            selected_sub.sub_plan_id,
            str(cost),
            price_offer['ttl_days']
        )
        "Если ошибка на саб сервисе"
        if not order_success:
            return 'Не удалось сформировать заказ. Попробуйте позже', None

        text = env.message_templates.render('message_pay_window', message, selected_sub,
            pay_amount=cost
        )
        kb = payment_kb(payment_link)
        return text, kb



class ShopSubscriptions:
    @staticmethod
    async def shop_subscriptions_slider(message: Message, state: FSMContext, aio_http: SubServiceConn):
        shop_plans = await aio_http.sub_plans.all()

        "Фоллбек. Нет подписок - не можем отобразить слайдер"
        if not shop_plans:
            await message.answer('⚒️ К сожалению, провайдер не предоставляет ни одной подписки')
            return

        "Сохраняем подписки, отображаем слайдер"
        await state.update_data(shop_plans=shop_plans)

        text, kb = await ShopSubscriptions.build_shop_plans_slider_msg(0, message, state)
        await message.answer(text, reply_markup=kb)

    @staticmethod
    async def build_shop_plans_slider_msg(slider_idx: int, message: Message, state: FSMContext) -> tuple:
        """"""
        "Получаем подписки"
        shop_plans = (await state.get_data()).get('shop_plans')
        if not shop_plans:
            return None, None

        "Отображаем слайдер"
        us = shop_plans[slider_idx]
        us_preview = UserSubSchema.fast_create(us)

        text = env.message_templates.render('message_subscriptions_shop_extent', message, us_preview)
        kb = shop_subs_slider(slider_idx, len(shop_plans))
        return text, kb

    @staticmethod
    async def show_price_offers(sub_plan_idx: int, message: Message, state: FSMContext, aio_http: SubServiceConn):
        shop_plans = (await state.get_data()).get('shop_plans')
        if not shop_plans:
            await ShopSubscriptions.shop_subscriptions_slider(message, state, aio_http)
            return None, None

        price_offers = shop_plans[sub_plan_idx]['offer_prices']
        ss_preview = ShopSubSchema.fast_create(shop_plans[sub_plan_idx])

        text = env.message_templates.render('message_subscriptions_offers_intro', message, ss_preview)
        kb = shop_sub_plan_offers(sub_plan_idx, price_offers)
        return text, kb

    @staticmethod
    async def give_issued_payment(sub_plan_idx: int, offer_idx: int, message: Message, state: FSMContext, aio_http: SubServiceConn):
        shop_plans = (await state.get_data()).get('shop_plans')
        if not shop_plans:
            await ShopSubscriptions.shop_subscriptions_slider(message, state, aio_http)
            return None, None

        "Запрос на формирование заказа, получим ссылку для оплаты"
        selected_sub = ShopSubSchema.fast_create(shop_plans[sub_plan_idx])
        price_offer = selected_sub['offer_prices'][offer_idx]


        order_success, payment_link = await aio_http.sub_plans.api_get_payment_link(
            message.from_user.id,
            selected_sub.id,
            price_offer['offer_id']
        )
        "Если ошибка на саб сервисе"
        if not order_success:
            return 'Не удалось сформировать заказ. Попробуйте позже', None

        text = env.message_templates.render('message_pay_window', message, selected_sub,
            pay_amount=f'{price_offer['cost'] / 100: .2f}'
        )
        kb = payment_kb(payment_link)
        return text, kb