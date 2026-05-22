import secrets
from datetime import timedelta, datetime
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from web.sub.anything import Constants, RobokassaUrls
from web.sub.api.robo_payment.handlers import payment_meta4signature_string, crypt_strategy, create_signature
from web.sub.config_dir.config import RoboAiohttpDep, env, NodeCmdAiohttpDep
from web.sub.config_dir.env_modes import AppMode
from web.sub.config_dir.logger_config import log_event
from web.sub.data.postgres import PgSqlDep
from web.sub.data.redis_storage import RedisDep
from web.sub.schemas import CreateRoboPayLinkSchema, WebhookRoboPayload

router = APIRouter(prefix='/api/v1/')# payment/robokassa



@router.post('/public/robokassa/get_pay_link')
async def create_payment_give_link(body: CreateRoboPayLinkSchema, request: Request, db: PgSqlDep, redis: RedisDep, aio_http: RoboAiohttpDep):
    """Генерация ссылки для оплаты. Фиксация начала платежка в нашей БД"""
    "Создаём InvId(для нас payed_subs.id)"
    order_id = await db.users_subs.order_subscription(body.user_id, body.sub_plan_id, body.expire_date)
    if order_id is None:
        log_event(f'\033[37m[Robokassa]\033[0m Были переданы несуществующие ID, не удалось выдать подписку | sub_plan_id: \033[33m{body.sub_plan_id}\033[0m | user_id: \033[31m{body.user_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Такого тарифного плана или пользователя не существует'})

    "Метаданные. Для наших потребностей. Должны начинаться с 'Shp_'"
    anti_csrf_token = secrets.token_urlsafe(16) # токен для идемпотентной обработки в вебхуке
    payment_meta = {
        'Shp_user_id': body.user_id,
        'Shp_sub_plan_id': body.sub_plan_id,
        'Shp_ttl_days': body.ttl_days,
        'Shp_csrf_token': anti_csrf_token,
    }
    "Сохраняем токен"
    await redis.set(Constants.payment_robo_lock(anti_csrf_token), order_id, ex=930) # 16 минут

    "Составляем сигнатуру для платежа"
    signature_string = create_signature(env.robo_passw_1, body.amount, order_id, f'Shp_user_id={body.user_id}')
    signature = crypt_strategy[env.robo_crypt_algorithm](signature_string)

    "Отдаём готовую ссылку"
    out_sum = Decimal(body.amount) * Decimal(100) # копейки -> рубли
    payment_params = {
        "MerchantLogin": env.robo_shop_login,
        "OutSum": str(out_sum),
        "InvId": order_id,
        "Description": body.description,
        "SignatureValue": signature,
        "IsTest": True if env.app_mode == AppMode.PROD else False,
        "ExpirationDate": datetime.now() + timedelta(seconds=900),
        **payment_meta,
    }
    payment_url = f'{RobokassaUrls.create_payment}?{urlencode(payment_params)}'
    log_event(f'\033[37m[Robokassa]\033[0m Выдали ссылку на оплату | user_id: \033[32m{body.user_id}\033[0m; cost: \033[35m{body.amount * 100}\033[0m; order_id: \033[36m{order_id}\033[0m; csrf_string: {anti_csrf_token}', request=request)
    return {'success': True, 'message': 'Ссылка на оплату', 'payment_url': payment_url}



@router.post('/payment/robokassa/successful_webhook')
async def processing_pay_result(form: WebhookRoboPayload, request: Request, db: PgSqlDep, redis: RedisDep, aio_http: NodeCmdAiohttpDep):
    """Обработка вебхука после оплаты пользователем"""
    "1. Проверяем сигнатуру"
    amount = form.OutSum.replace('.', '') # 150.00 -> 15000
    expected_signature = create_signature(env.robo_passw_2, amount, form.InvId, f'Shp_user_id={form.Shp_user_id}')

    if not secrets.compare_digest(
            crypt_strategy[env.robo_crypt_algorithm](expected_signature).lower(), # Строка с использованием PASSW2
            form.SignatureValue.lower() # Строка с использованием PASSW1
    ):
        log_event(f'[Robokassa] Попытка подмены сигнатуры | order_id: \033[31m{form.InvId}\033[0m; csrf_string: {form.Shp_csrf_token}', request=request)
        raise HTTPException(status_code=400, detail="Signature verification failed")

    "2. Реализуем ключ идемпотентности"
    if not await redis.delete(Constants.payment_robo_lock(form.Shp_csrf_token)):
        log_event(f'\033[37m[Robokassa]\033[0m Повторная обработка вебхука | order_id: \033[33m{form.InvId}\033[0m', request=request, level='WARNING')
        return f"OK{form.InvId}"

    "3. Обработка успешного платежа, запрос на добавление пользователя в ядра протоколов"
    await db.users_subs.activate_subscription(form.InvId, form.Shp_ttl_days, form.Shp_user_id)
    user_info = await db.users_subs.get_user_info(form.Shp_user_id)

    "Антипаттерн, но операция  слишком тяжёлая для обработки на месте."
    "Возможно, нужно будет выносить в отдельный сервис исполнение фоновых задач."
    # # отправляем запрос н админку для регистрации пользователя в нодах
    # url = f'{env.admin_panel_url}/api/v1/private/cmd_center/core_protocol/user/add'
    # async with aio_http.post(url, json={'uuid': user_info['uuid'], 'tg_username': user_info['tg_username']}) as resp:
    #     resp.release()

    log_event(f'Попробовали добавить пользователя на впн-ноды | user_id: \033[31m{form.Shp_user_id}\033[0m; user_uuid: \033[35m{user_info['uuid']}\033[0m; order_id: \033[33m{form.InvId}\033[0m', request=request)
    return f"OK{form.InvId}"
