import secrets
from datetime import timedelta, datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Form
from starlette.requests import Request

from web.sub.anything import Constants, RobokassaUrls, CoreProtoActions
from web.sub.api.robo_payment.handlers import crypt_strategy, create_signature, payment_meta4signature_string
from web.sub.config_dir.config import env, ArqDep
from web.sub.config_dir.env_modes import AppMode
from web.sub.config_dir.logger_config import log_event
from web.sub.data.postgres import PgSqlDep
from web.sub.data.redis_storage import RedisDep
from web.sub.schemas import CreateRoboPayLinkSchema, WebhookRoboPayload

router = APIRouter(prefix='/api/v1', tags=['🤖 RoboKassa Payment'])



@router.post('/robokassa/get_pay_link')
async def create_payment_give_link(body: CreateRoboPayLinkSchema, request: Request, db: PgSqlDep, redis: RedisDep):
    """Генерация ссылки для оплаты. Фиксация начала платежка в нашей БД"""
    "Создаём InvId(для нас payed_subs.id)"
    order_meta = await db.users_subs.order_subscription(body.user_id, body.sub_plan_id)
    if order_meta is None:
        log_event(f'\033[37m[Robokassa]\033[0m Были переданы несуществующие ID, не удалось выдать подписку | sub_plan_id: \033[33m{body.sub_plan_id}\033[0m | user_id: \033[31m{body.user_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Такого тарифного плана или пользователя не существует'})

    "Метаданные. Для наших потребностей. Должны начинаться с 'Shp_'"
    anti_csrf_token = secrets.token_urlsafe(16) # токен для идемпотентной обработки в вебхуке
    payment_meta = {
        'Shp_user_id': body.user_id,
        'Shp_sub_plan_id': body.sub_plan_id,
        'Shp_csrf_token': anti_csrf_token,
        'Shp_expire_date': order_meta['old_expire_date'] + timedelta(days=body.ttl_days),
    }
    "Сохраняем токен"
    await redis.set(Constants.payment_robo_lock(anti_csrf_token), order_meta['order_id'], ex=930) # 16 минут
    log_event(f'\033[37m[Robokassa]\033[0m Токен идемпотентности | anti_csrf: \033[31m{anti_csrf_token[:10]}\033[0m; order_id: \033[32m{order_meta['order_id']}\033[0m')

    "Составляем сигнатуру для платежа"
    signature_string = create_signature(env.robo_passw_1, body.amount, order_meta['order_id'], payment_meta4signature_string(payment_meta), merchant_login=env.robo_shop_login)
    signature = crypt_strategy[env.robo_crypt_algorithm](signature_string.encode('utf-8')).hexdigest()

    "Отдаём готовую ссылку"
    payment_params = {
        "MerchantLogin": env.robo_shop_login,
        "OutSum": str(body.amount),
        "InvId": order_meta['order_id'],
        "Description": body.description,
        "SignatureValue": signature,
        "IsTest": 0 if env.app_mode == AppMode.PROD else 1,
        "ExpirationDate": datetime.now() + timedelta(seconds=900),
        **payment_meta,
    }
    payment_url = f'{RobokassaUrls.create_payment}?{urlencode(payment_params)}'
    log_event(f'\033[37m[Robokassa]\033[0m Выдали ссылку на оплату | user_id: \033[32m{body.user_id}\033[0m; cost: \033[35m{body.amount}\033[0m; order_id: \033[36m{order_meta['order_id']}\033[0m; csrf_string: {anti_csrf_token}', request=request)
    return {'success': True, 'message': 'Ссылка на оплату', 'payment_url': payment_url}



@router.post('/robokassa/webhook')
async def processing_pay_result(form: Annotated[WebhookRoboPayload, Form()], request: Request, db: PgSqlDep, redis: RedisDep, arq: ArqDep):
    """Обработка вебхука после оплаты пользователем"""
    log_event(f'{repr(form)}', request=request, level='DEBUG')

    "1. Проверяем сигнатуру"
    payment_meta = {k: v for k,v in form.model_dump().items() if k.startswith('Shp_')}
    expected_signature = create_signature(env.robo_passw_2, form.OutSum, form.InvId, payment_meta4signature_string(payment_meta))
    expected_hash = crypt_strategy[env.robo_crypt_algorithm](expected_signature.encode('utf-8')).hexdigest()
    if not secrets.compare_digest(
            expected_hash.lower(),
            form.SignatureValue.lower()
    ):
        log_event(f'[Robokassa] Попытка подмены сигнатуры | order_id: \033[31m{form.InvId}\033[0m; csrf_string: {form.Shp_csrf_token}', request=request)
        raise HTTPException(status_code=400, detail="Signature verification failed")

    "2. Реализуем ключ идемпотентности"
    if not await redis.delete(Constants.payment_robo_lock(form.Shp_csrf_token)):
        log_event(f'\033[37m[Robokassa]\033[0m Повторная обработка вебхука | order_id: \033[33m{form.InvId}\033[0m', request=request, level='WARNING')
        return f"OK{form.InvId}"

    "3.1. Активация подписку пользователя"
    await db.users_subs.activate_subscription(form.InvId, form.Shp_expire_date, form.Shp_user_id)

    "3.2. Запускаем в фон таску на добавление пользователя в ядра нод, указанных в подписке"
    # User Meta
    user_info = await db.users_subs.get_user_info(form.Shp_user_id)
    # Находим ноды по подписке, фиксируем попытку вставки пользователя в ядра протоколов
    sub_nodes = await db.sub.get_core_proto_deps_by_user_id(
        form.Shp_user_id, user_info['uuid'], user_info['tg_username'], form.InvId, CoreProtoActions.word_add
    )
    # Преобразуем asyncpg.Record в dict для сериализации
    sub_nodes_serializable = [dict(node) for node in sub_nodes]
    
    job = await arq.enqueue_job(
        'action_on_core_proto_by_sub_plan', user_info['uuid'], user_info['tg_username'], sub_nodes_serializable, CoreProtoActions.word_add
    )

    log_event(f'Кинули добавление пользователя на впн-ноды в Arq | job_id: \033[33m{job.job_id}\033[0m; user_id: \033[31m{form.Shp_user_id}\033[0m; user_uuid: \033[35m{user_info['uuid']}\033[0m; order_id: \033[33m{form.InvId}\033[0m', request=request)
    return f"OK{form.InvId}"
