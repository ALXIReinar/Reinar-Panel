"""
Integration тесты для Robokassa Payment API.

Тестируем 2 эндпоинта:
1. POST /api/v1/robokassa/get_pay_link - генерация ссылки на оплату
2. POST /api/v1/robokassa/webhook - обработка постбэка от Robokassa

Используем имитацию webhook с правильной сигнатурой вместо реального взаимодействия.
"""
import pytest
from urllib.parse import urlparse, parse_qs
import httpx

from fastapi import FastAPI

from web.sub.api.robo_payment.payment_api import router
from web.sub.api.robo_payment.handlers import create_signature, payment_meta4signature_string, crypt_strategy
from web.sub.config_dir.config import env
from web.sub.anything import Constants


pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def test_payment_app():
    """
    FastAPI приложение для тестирования payment API (создаётся один раз на сессию).
    """
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture(scope="function")
async def test_payment_client(test_payment_app, db_pool, redis_pool, payment_seed):
    """
    HTTP клиент для тестирования payment API.
    
    Setup:
    1. Устанавливает db_pool, redis, mock arq_pool в app.state
    2. Создаёт httpx.AsyncClient с ASGITransport
    
    Teardown:
    1. Закрывает AsyncClient
    2. Очищает state
    """
    from unittest.mock import AsyncMock, MagicMock
    
    # Mock arq_pool
    mock_arq = AsyncMock()
    mock_job = MagicMock()
    mock_job.job_id = "test-payment-job-id"
    mock_arq.enqueue_job = AsyncMock(return_value=mock_job)
    
    try:
        # Setup: устанавливаем зависимости
        test_payment_app.state.pg_pool = db_pool
        test_payment_app.state.redis = redis_pool
        test_payment_app.state.arq_pool = mock_arq
        
        # Создаём HTTP клиент
        transport = httpx.ASGITransport(app=test_payment_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            ac.mock_arq = mock_arq  # Добавляем mock для доступа в тестах
            yield ac
    finally:
        # Teardown: очищаем state
        for attr in ['pg_pool', 'redis', 'arq_pool']:
            if hasattr(test_payment_app.state, attr):
                delattr(test_payment_app.state, attr)


def create_valid_webhook_payload_dict(order_id: int, user_id: int, sub_plan_id: int, offer_id: int, csrf_token: str, amount: str = "500.00", sub_days: int = 30):
    """
    Генерирует валидный webhook payload с правильной сигнатурой.
    
    Использует те же алгоритмы что и продакшн код для генерации валидной подписи.
    Возвращает dict для form data (не Pydantic модель).
    
    ВАЖНО: Shp_offer_id - обязательное поле в схеме WebhookRoboPayload.
    """
    # Формируем payment_meta для подписи
    payment_meta_for_signature = {
        'Shp_csrf_token': csrf_token,
        'Shp_offer_id': offer_id,
        'Shp_sub_plan_id': sub_plan_id,
        'Shp_user_id': user_id,
    }
    
    # Создаём сигнатуру (используем robo_passw_2 для webhook)
    meta_str = payment_meta4signature_string(payment_meta_for_signature)
    signature_string = create_signature(env.robo_passw_2, amount, order_id, meta_str, merchant_login='')
    signature_hash = crypt_strategy[env.robo_crypt_algorithm](signature_string.encode('utf-8')).hexdigest()
    
    # Возвращаем dict для form data
    return {
        'OutSum': amount,
        'InvId': order_id,
        'SignatureValue': signature_hash,
        'Shp_user_id': user_id,
        'Shp_csrf_token': csrf_token,
        'Shp_sub_plan_id': sub_plan_id,
        'Shp_offer_id': offer_id,
    }


class TestCreatePaymentLink:
    """Integration тесты для POST /api/v1/robokassa/get_pay_link"""
    
    async def test_create_pay_link_success(self, test_payment_client, payment_seed, redis_pool):
        """
        Успешное создание ссылки на оплату.
        
        Проверяем:
        - Статус 200
        - Формат ответа (success, message, payment_url)
        - Структуру payment_url
        - Токен идемпотентности в Redis
        - Создание записи в payed_subs
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'Тестовая подписка Premium',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert data['success'] is True
        assert 'payment_url' in data
        assert 'message' in data
        
        # Проверяем URL
        payment_url = data['payment_url']
        parsed_url = urlparse(payment_url)
        query_params = parse_qs(parsed_url.query)
        
        # Проверяем параметры в URL
        assert 'MerchantLogin' in query_params
        # OutSum может быть '5' или '5.00' (зависит от форматирования Decimal)
        assert query_params['OutSum'][0] in ['5', '5.00']  # 500 копеек = 5.00 рублей
        assert 'InvId' in query_params
        assert 'SignatureValue' in query_params
        assert 'Shp_user_id' in query_params
        assert 'Shp_csrf_token' in query_params
        
        # Проверяем что токен есть в Redis
        csrf_token = query_params['Shp_csrf_token'][0]
        redis_key = Constants.payment_robo_lock(csrf_token)
        redis_value = await redis_pool.get(redis_key)
        assert redis_value is not None
        
        # Проверяем TTL (должен быть ~930 секунд)
        ttl = await redis_pool.ttl(redis_key)
        assert 920 < ttl <= 930
    
    
    async def test_create_pay_link_invalid_user(self, test_payment_client, payment_seed):
        """
        Несуществующий user_id → 404.
        """
        # Arrange
        payload = {
            'user_id': 999999,  # Несуществующий
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'Тест',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert
        assert response.status_code == 404
        data = response.json()
        assert 'detail' in data
        assert data['detail']['success'] is False
    
    
    async def test_create_pay_link_invalid_plan(self, test_payment_client, payment_seed):
        """
        Несуществующий offer_id → 404.
        API валидирует существование оффера при создании ссылки через order_subscription.
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': 999999,  # Несуществующий
            'description': 'Тест',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert - 404 так как оффер не найден
        assert response.status_code == 404
        data = response.json()
        assert data['detail']['success'] is False
    
    
    async def test_create_pay_link_signature_valid(self, test_payment_client, payment_seed):
        """
        Проверяем что сигнатура в URL валидна.
        
        Пересчитываем сигнатуру и сравниваем с той что в URL.
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'Premium план',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert
        data = response.json()
        parsed_url = urlparse(data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        
        # Извлекаем данные из URL
        out_sum = query_params['OutSum'][0]
        inv_id = int(query_params['InvId'][0])
        signature_from_url = query_params['SignatureValue'][0]
        
        # Собираем Shp_ параметры
        shp_params = {k: v[0] for k, v in query_params.items() if k.startswith('Shp_')}
        
        # Пересчитываем сигнатуру
        meta_str = payment_meta4signature_string(shp_params)
        signature_string = create_signature(
            env.robo_passw_1, out_sum, inv_id, meta_str, merchant_login=env.robo_shop_login
        )
        expected_signature = crypt_strategy[env.robo_crypt_algorithm](signature_string.encode('utf-8')).hexdigest()
        
        # Сравниваем
        assert signature_from_url.lower() == expected_signature.lower()
    
    
    async def test_create_pay_link_creates_order_in_db(self, test_payment_client, payment_seed, db_pool):
        """
        Проверяем что создаётся запись в pay_orders со статусом pending.
        user_subs создаётся только при обработке webhook, а не при создании ссылки.
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'VIP план',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert
        data = response.json()
        parsed_url = urlparse(data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        order_id = int(query_params['InvId'][0])
        
        # Проверяем запись в БД (только pay_orders, user_subs ещё нет)
        async with db_pool.acquire() as conn:
            order = await conn.fetchrow("""
                SELECT po.id, po.user_id, po.status
                FROM pay_orders po
                WHERE po.id = $1
            """, order_id)
        
        assert order is not None
        assert order['user_id'] == payment_seed['user_id']
        assert order['status'] == 1  # PayStatuses.pending


class TestWebhookProcessing:
    """Integration тесты для POST /api/v1/robokassa/webhook"""
    
    async def test_webhook_success(self, test_payment_client, payment_seed, redis_pool, db_pool):
        """
        Успешная обработка webhook с валидной сигнатурой.
        
        Проверяем:
        - Статус 200
        - Ответ OK{InvId}
        - Активация подписки
        - Удаление токена из Redis
        """
        # Arrange - создаём order
        create_link_payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'Test',
        }
        link_response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=create_link_payload)
        link_data = link_response.json()
        parsed_url = urlparse(link_data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        
        order_id = int(query_params['InvId'][0])
        csrf_token = query_params['Shp_csrf_token'][0]
        
        # Создаём валидный webhook payload
        webhook_data = create_valid_webhook_payload_dict(
            order_id=order_id,
            user_id=payment_seed['user_id'],
            sub_plan_id=payment_seed['plan_id'],
            offer_id=payment_seed['offer_id'],
            csrf_token=csrf_token,
            amount='5.00'  # 500 копеек = 5.00 рублей
        )
        
        # Act
        response = await test_payment_client.post(
            '/api/v1/robokassa/webhook',
            data=webhook_data  # Form data
        )
        
        # Assert
        assert response.status_code == 200
        # FastAPI может вернуть либо plain text либо JSON-encoded
        assert response.text in [f"OK{order_id}", f'"OK{order_id}"']
        
        # Проверяем что подписка активирована
        async with db_pool.acquire() as conn:
            order = await conn.fetchrow("""
                SELECT us.is_active, us.expire_date, po.status
                FROM user_subs us
                JOIN pay_orders po ON po.id = us.order_id
                WHERE us.order_id = $1
            """, order_id)
        
        assert order['is_active'] is True
        assert order['status'] == 2  # success
        assert order['expire_date'] is not None
        
        # Проверяем что токен удалён из Redis
        redis_key = Constants.payment_robo_lock(csrf_token)
        redis_value = await redis_pool.get(redis_key)
        assert redis_value is None
    
    
    async def test_webhook_invalid_signature(self, test_payment_client, payment_seed):
        """
        Невалидная сигнатура → 400.
        """
        # Arrange
        webhook_data = {
            'OutSum': '5.00',  # 500 копеек = 5.00 рублей
            'InvId': 999,
            'SignatureValue': 'invalid_signature_hash_12345',
            'Shp_user_id': payment_seed['user_id'],
            'Shp_csrf_token': 'fake_token',
            'Shp_sub_plan_id': payment_seed['plan_id'],
            'Shp_offer_id': payment_seed['offer_id'],
        }
        
        # Act
        response = await test_payment_client.post(
            '/api/v1/robokassa/webhook',
            data=webhook_data
        )
        
        # Assert
        assert response.status_code == 400
        data = response.json()
        assert 'Signature verification failed' in data['detail']
    
    
    async def test_webhook_idempotency(self, test_payment_client, payment_seed, redis_pool):
        """
        Идемпотентность: повторный webhook с тем же токеном не обрабатывается.
        
        Проверяем:
        - Первый запрос: OK{InvId}
        - Второй запрос: OK{InvId} (но без обработки)
        - Токен удалён после первого запроса
        """
        # Arrange - создаём order
        create_link_payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'Test idempotency',
        }
        link_response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=create_link_payload)
        link_data = link_response.json()
        parsed_url = urlparse(link_data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        
        order_id = int(query_params['InvId'][0])
        csrf_token = query_params['Shp_csrf_token'][0]
        
        webhook_data = create_valid_webhook_payload_dict(
            order_id=order_id,
            user_id=payment_seed['user_id'],
            sub_plan_id=payment_seed['plan_id'],
            offer_id=payment_seed['offer_id'],
            csrf_token=csrf_token,
            amount='5.00'  # 500 копеек = 5.00 рублей
        )
        
        # Act - первый запрос
        response1 = await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        
        # Проверяем что токен удалён
        redis_key = Constants.payment_robo_lock(csrf_token)
        redis_value = await redis_pool.get(redis_key)
        assert redis_value is None
        
        # Act - второй запрос (повторный)
        response2 = await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        
        # Assert
        assert response1.status_code == 200
        assert response2.status_code == 200
        # FastAPI может вернуть либо plain text либо JSON-encoded
        assert response1.text in [f"OK{order_id}", f'"OK{order_id}"']
        assert response2.text in [f"OK{order_id}", f'"OK{order_id}"']
    
    
    async def test_webhook_deactivates_old_subscription(self, test_payment_client, payment_seed, db_pool):
        """
        При активации новой подписки с тем же планом старая ОБНОВЛЯЕТСЯ (продлевается) через UPSERT.
        CONSTRAINT: (user_id, sub_plan_id) UNIQUE - у пользователя может быть только одна подписка на план.
        """
        # Arrange - создаём старую активную подписку
        async with db_pool.acquire() as conn:
            # Создаём pay_order с полными данными
            old_pay_order = await conn.fetchval("""
                INSERT INTO pay_orders (
                    user_id, status, 
                    infinite_expire, infinite_traffic,
                    traffic_limit_mb, traffic_limit_day_mb,
                    ttl_days, cost
                )
                SELECT $1, 2,
                    infinite_expire, infinite_traffic,
                    traffic_limit_mb, traffic_limit_day_mb,
                    ttl_days, cost
                FROM sub_plan_offers
                WHERE id = $2
                RETURNING id
            """, payment_seed['user_id'], payment_seed['offer_id'])
            
            old_order_id = await conn.fetchval("""
                INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, 
                                       uuid, b64_id, infinite_traffic, infinite_expire, 
                                       traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited)
                VALUES ($1, $2, $3, true, now() + interval '10 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
                RETURNING id
            """, payment_seed['user_id'], payment_seed['plan_id'], old_pay_order, 
                 'uuid-old-sub', 'b64-old-sub')
        
        # Создаём новый order через API
        create_link_payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'New subscription',
        }
        link_response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=create_link_payload)
        link_data = link_response.json()
        parsed_url = urlparse(link_data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        
        new_order_id = int(query_params['InvId'][0])
        csrf_token = query_params['Shp_csrf_token'][0]
        
        webhook_data = create_valid_webhook_payload_dict(
            order_id=new_order_id,
            user_id=payment_seed['user_id'],
            sub_plan_id=payment_seed['plan_id'],
            offer_id=payment_seed['offer_id'],
            csrf_token=csrf_token,
            amount='5.00'  # 500 копеек = 5.00 рублей
        )
        
        # Act
        await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        
        # Assert - старая подписка ОБНОВЛЕНА (не создана новая запись)
        async with db_pool.acquire() as conn:
            updated_sub = await conn.fetchrow("""
                SELECT id, is_active, order_id FROM user_subs WHERE id = $1
            """, old_order_id)
        
        # Подписка осталась с тем же ID, но обновлён order_id и is_active=true
        assert updated_sub is not None
        assert updated_sub['id'] == old_order_id
        assert updated_sub['is_active'] is True
        assert updated_sub['order_id'] == new_order_id  # Обновлён на новый заказ
    
    
    async def test_webhook_enqueues_arq_job(self, test_payment_client, payment_seed):
        """
        Webhook ставит задачу action_on_core_proto_by_sub_plan в Arq.
        """
        # Arrange
        create_link_payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'offer_id': payment_seed['offer_id'],
            'description': 'Test ARQ',
        }
        link_response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=create_link_payload)
        link_data = link_response.json()
        parsed_url = urlparse(link_data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        
        order_id = int(query_params['InvId'][0])
        csrf_token = query_params['Shp_csrf_token'][0]
        
        webhook_data = create_valid_webhook_payload_dict(
            order_id=order_id,
            user_id=payment_seed['user_id'],
            sub_plan_id=payment_seed['plan_id'],
            offer_id=payment_seed['offer_id'],
            csrf_token=csrf_token,
            amount='5.00'  # 500 копеек = 5.00 рублей
        )
        
        # Act
        await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        
        # Assert - проверяем что задача была поставлена в Arq
        test_payment_client.mock_arq.enqueue_job.assert_called_once()
        call_args = test_payment_client.mock_arq.enqueue_job.call_args
        assert call_args[0][0] == 'action_on_core_proto_by_sub_plan'
