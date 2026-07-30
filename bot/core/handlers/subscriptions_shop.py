import orjson
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from redis.asyncio import Redis

from bot.config_dir.config import env
from bot.config_dir.logger_config import log_event
from bot.core.api.aiohttp_conn import SubServiceConn
from bot.core.utils.anything import RedisKeys
from bot.core.utils.keyboards import subs_intro_kb, fallback_user_subs, user_subs_slider, user_sub_plan_offers, \
    payment_kb, shop_subs_slider
from bot.core.utils.rate_limiter import rate_limit
from bot.core.utils.schemas import UserSubSchema, ShopSubSchema


async def subscriptions_introduction(message: Message):
    text = env.message_templates.render('message_subscriptions_shop_intro', message)
    await message.answer(text, reply_markup=subs_intro_kb())


class UserSubscriptions:

    @staticmethod
    @rate_limit(env.user_req_limit, env.user_req_window_seconds)
    async def user_subscriptions_slider(call: CallbackQuery, redis: Redis, state: FSMContext, aio_http: SubServiceConn):
        """
        Возможен сценарий, при котором state после первоначальных проверок в user_subscriptions_slider, при вызове
        build_user_subs_slider_msg получит None для text, из-за чего будет исключение.
        Такое учтено в ShopSubscriptions, т.к. используется Редис с TTL. С FSMContext(In-Memory) такого не должно быть: нет ТТЛ + внутренний механизм

        File "bot/core/handlers/subscriptions_shop.py", line 148, in shop_subscriptions_slider
                await call.message.answer(text, reply_markup=kb)
        File ".venv/Lib/site-packages/aiogram/types/message.py", line 2238, in answer
                return SendMessage(
        File ".venv/Lib/site-packages/pydantic/main.py", line 250, in __init__
                validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
        pydantic_core._pydantic_core.ValidationError: 1 validation error for SendMessage
            text
        Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]        
        """
        ok, user_subs = await aio_http.user_subs.all(call.from_user.id)

        "Фоллбек. Нет подписок - не можем отобразить слайдер"
        if not ok:
            log_event(f'Саб сервис недоступен | tg_id: \033[33m{call.from_user.id}\033[0m', level='CRITICAL')
            await call.message.answer('⚒️ Технический перерыв. Попробуйте позже')
            return

        "Фоллбек. Нет подписок - не можем отобразить слайдер"
        if not user_subs:
            log_event(f'У пользователя нет ни одной подписки | tg_id: \033[33m{call.from_user.id}\033[0m', level='WARNING')
            await call.message.answer('У Вас нет ни одной подписки', reply_markup=fallback_user_subs())
            return

        log_event(f'Получили подписки пользователя | tg_id: \033[33m{call.from_user.id}\033[0m; sub_len: \033[34m{len(user_subs)}\033[0m')

        "Сохраняем подписки, отображаем слайдер"
        await state.update_data(user_subs=user_subs)

        text, kb = await UserSubscriptions.build_user_subs_slider_msg(0, call, state)
        log_event(f'Отдали слайдер user-подписок пользователю | tg_id: \033[34m{call.from_user.id}\033[0m; sub_len: \033[33m{len(user_subs)}\033[0m')
        await call.message.answer(text, reply_markup=kb)


    @staticmethod
    async def build_user_subs_slider_msg(slider_idx: int, call: CallbackQuery, state: FSMContext) -> tuple:
        """"""
        "Получаем подписки"
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            log_event(f'Подписки пользователя Пропали из Стейта! | tg_id: \033[33m{call.from_user.id}\033[0m')
            return None, None

        "Отображаем слайдер"
        us = user_subs[slider_idx]
        us_preview = UserSubSchema.fast_create(us)

        text = env.message_templates.render('message_subscriptions_user_extent', call, us_preview)
        kb = user_subs_slider(slider_idx, len(user_subs))
        return text, kb


    @staticmethod
    async def show_price_offers(user_sub_idx: int, redis: Redis, call: CallbackQuery, state: FSMContext, aio_http: SubServiceConn):
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            await UserSubscriptions.user_subscriptions_slider(call, redis, state, aio_http)
            return None, None

        us_preview = UserSubSchema.fast_create(user_subs[user_sub_idx])
        offer_prices = us_preview.offer_prices
        log_event(f'Предложений по подписке пользователя | offers_len: \033[34m{len(offer_prices)}\033[0m; offers: \033[34m{str(offer_prices)[:150]}\033[0m')

        text = env.message_templates.render('message_subscriptions_offers_intro', call, us_preview)
        kb = user_sub_plan_offers(user_sub_idx, offer_prices)
        return text, kb


    @staticmethod
    @rate_limit(env.user_req_limit, env.user_req_window_seconds)
    async def give_issued_payment(call: CallbackQuery, redis: Redis, state: FSMContext, aio_http: SubServiceConn, user_sub_idx: int, offer_idx: int):
        user_subs = (await state.get_data()).get('user_subs')
        if not user_subs:
            log_event(f'Подписки пользователя Пропали из Стейта! | tg_id: \033[33m{call.from_user.id}\033[0m')
            await UserSubscriptions.user_subscriptions_slider(call, redis, state, aio_http)
            return None, None

        "Запрос на формирование заказа, получим ссылку для оплаты"
        selected_sub = UserSubSchema.fast_create(user_subs[user_sub_idx])
        price_offer = selected_sub.offer_prices[offer_idx]

        log_event(f'Запросили ссылку на оплату с саб сервиса | tg_id: \033[31m{call.from_user.id}\033[0m; sub_plan_id: \033[34m{selected_sub.sub_plan_id}\033[0m; offer_id: \033[36m{price_offer['offer_id']}\033[0m')
        order_success, payment_link = await aio_http.sub_plans.api_get_payment_link(
            call.from_user.id,
            selected_sub.sub_plan_id,
            price_offer['offer_id'],
            selected_sub.title
        )
        "Если ошибка на саб сервисе"
        if not order_success:
            log_event(f"Саб сервис не смог отдать ссылку на оплату! | tg_id: \033[31m{call.from_user.id}\033[0m; sub_plan_id: \033[34m{selected_sub.sub_plan_id}\033[0m; offer_id: \033[36m{price_offer['offer_id']}\033[0m", level='CRITICAL')
            return 'Не удалось сформировать заказ. Попробуйте позже', None

        text = env.message_templates.render('message_pay_window', call, selected_sub,
            pay_amount=f'{price_offer['cost'] / 100: .2f}'
        )
        kb = payment_kb(payment_link)
        return text, kb



class ShopSubscriptions:
    @staticmethod
    @rate_limit(env.user_req_limit, env.user_req_window_seconds)
    async def shop_subscriptions_slider(call: CallbackQuery, redis: Redis, aio_http: SubServiceConn):
        ok, sub_plans = await aio_http.sub_plans.all()

        "Саб сервис недоступен"
        if not ok:
            log_event(f'Не удалось связаться с саб-сервисом | tg_id: \033[33m{call.from_user.id}\033[0m', level='CRITICAL')
            await call.message.answer('⚒️ Технический перерыв. Попробуйте позже')
            return

        "Фоллбек. Нет подписок - не можем отобразить слайдер"
        if not sub_plans:
            log_event(f'Нет ни одного активированного тарифного плана! | tg_id: \033[33m{call.from_user.id}\033[0m', level='CRITICAL')
            await call.message.answer('⚒️ К сожалению, провайдер не предоставляет ни одной подписки')
            return

        log_event(f'Получили Тарифные планы | tg_id: \033[33m{call.from_user.id}\033[0m; sub_plans_len: \033[34m{len(sub_plans)}\033[0m')

        "Сохраняем подписки, отображаем слайдер"
        shop_plans_json = orjson.dumps(sub_plans)
        await redis.set(RedisKeys.shop_sub_plans, shop_plans_json, ex=env.shop_sub_plans_ttl)

        text, kb = await ShopSubscriptions.build_shop_plans_slider_msg(0, call, redis)
        if not text:
            await ShopSubscriptions.shop_subscriptions_slider(call, redis, aio_http)
            return

        log_event(f'Отобразили слайдер тарифных планов | tg_id: \033[33m{call.from_user.id}\033[0m; sub_plans_len: \033[34m{len(sub_plans)}\033[0m')
        await call.message.answer(text, reply_markup=kb)


    @staticmethod
    async def build_shop_plans_slider_msg(slider_idx: int, call: CallbackQuery, redis: Redis) -> tuple:
        """"""
        "Получаем подписки"
        sp_redis = await redis.get(RedisKeys.shop_sub_plans) or '{}' # .get() отдаёт None -> JSONDecodeError, нужен фоллбек
        shop_plans = orjson.loads(sp_redis)
        if not shop_plans:
            log_event('Тарифные планы пропали из кэша')
            return None, None

        "Отображаем слайдер с offer_prices"
        ss = shop_plans[slider_idx]
        ss_preview = ShopSubSchema.fast_create(ss)

        text = env.message_templates.render('message_subscriptions_shop_extent', call, shop_plan=ss_preview)
        kb = shop_subs_slider(slider_idx, len(shop_plans), ss_preview.offer_prices)
        log_event(f'Собрали слайдер тарифных планов | cur_idx: {slider_idx}; offers_len: {len(ss_preview.offer_prices)}')
        return text, kb


    @staticmethod
    @rate_limit(env.user_req_limit, env.user_req_window_seconds)
    async def give_issued_payment(call: CallbackQuery, redis: Redis, aio_http: SubServiceConn, sub_plan_idx: int, offer_idx: int):
        sp_redis = await redis.get(RedisKeys.shop_sub_plans) or '{}'  # .get() отдаёт None -> JSONDecodeError, нужен фоллбек
        shop_plans = orjson.loads(sp_redis)

        if not shop_plans:
            log_event('Тарифные планы пропали из кэша')
            await ShopSubscriptions.shop_subscriptions_slider(call, redis, aio_http)
            return None, None

        "Запрос на формирование заказа, получим ссылку для оплаты"
        selected_sub = ShopSubSchema.fast_create(shop_plans[sub_plan_idx])
        price_offer = selected_sub.offer_prices[offer_idx]

        log_event(f'Запросили ссылку на оплату с саб сервиса | tg_id: \033[31m{call.from_user.id}\033[0m; sub_plan_id: \033[34m{selected_sub.id}\033[0m; offer_id: \033[36m{price_offer['offer_id']}\033[0m')
        order_success, payment_link = await aio_http.sub_plans.api_get_payment_link(
            call.from_user.id,
            selected_sub.id,
            price_offer['offer_id'],
            selected_sub.title
        )
        "Если ошибка на саб сервисе"
        if not order_success:
            return 'Не удалось сформировать заказ. Попробуйте позже', None

        text = env.message_templates.render('message_pay_window', call, shop_plan=selected_sub,
            pay_amount=f'{price_offer['cost'] / 100: .2f}'
        )
        kb = payment_kb(payment_link)
        return text, kb