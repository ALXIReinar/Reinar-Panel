"""
Integration тесты для Robokassa Payment API.

Тестируем 2 эндпоинта:
1. POST /api/v1/robokassa/get_pay_link - генерация ссылки на оплату
2. POST /api/v1/robokassa/webhook - обработка постбэка от Robokassa

Используем имитацию webhook с правильной сигнатурой вместо реального взаимодействия.
"""
import pytest
import hashlib
import secrets
from datetime import datetime, timedelta
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
async def test_payment_client(test_payment_app, db_pool, redis_pool, arq_pool, payment_seed):
    """
    HTTP клиент для тестирования payment API.
    
    Setup:
    1. Устанавливает db_pool, redis, arq_pool в app.state
    2. Создаёт httpx.AsyncClient с ASGITransport
    
    Teardown:
    1. Закрывает AsyncClient
    2. Очищает state
    """
    try:
        # Setup: устанавливаем зависимости
        test_payment_app.state.pg_pool = db_pool
        test_payment_app.state.redis = redis_pool
        test_payment_app.state.arq_pool = arq_pool
        
        # Создаём HTTP клиент
        transport = httpx.ASGITransport(app=test_payment_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        # Teardown: очищаем state
        for attr in ['pg_pool', 'redis', 'arq_pool']:
            if hasattr(test_payment_app.state, attr):
                delattr(test_payment_app.state, attr)


def create_valid_webhook_payload_dict(order_id: int, user_id: int, sub_plan_id: int, csrf_token: str, amount: str = "500.00"):
    """
    Генерирует валидный webhook payload с правильной сигнатурой.
    
    Использует те же алгоритмы что и продакшн код для генерации валидной подписи.
    Возвращает dict для form data (не Pydantic модель).
    
    ВАЖНО: Shp_expire_date должен быть datetime объектом для payment_meta4signature_string,
    но ISO строкой в form data (FastAPI/Pydantic автоматически парсит обратно в datetime).
    """
    expire_date = datetime.now() + timedelta(days=30)
    
    # Формируем payment_meta для подписи (с datetime объектом)
    payment_meta_for_signature = {
        'Shp_csrf_token': csrf_token,
        'Shp_expire_date': expire_date,  # datetime объект
        'Shp_sub_plan_id': sub_plan_id,
        'Shp_user_id': user_id,
    }
    
    # Создаём сигнатуру (используем robo_passw_2 для webhook)
    meta_str = payment_meta4signature_string(payment_meta_for_signature)
    signature_string = create_signature(env.robo_passw_2, amount, order_id, meta_str, merchant_login='')
    signature_hash = crypt_strategy[env.robo_crypt_algorithm](signature_string.encode('utf-8')).hexdigest()
    
    # Возвращаем dict для form data (Shp_expire_date как ISO строка)
    return {
        'OutSum': amount,
        'InvId': order_id,
        'SignatureValue': signature_hash,
        'Shp_user_id': user_id,
        'Shp_csrf_token': csrf_token,
        'Shp_sub_plan_id': sub_plan_id,
        'Shp_expire_date': expire_date.isoformat(),  # ISO строка для form data
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
            'ttl_days': 30,
            'amount': '500.00',
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
        assert query_params['OutSum'][0] == '500.00'
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
            'ttl_days': 30,
            'amount': '500.00',
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
        Несуществующий sub_plan_id → 404.
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': 999999,  # Несуществующий
            'ttl_days': 30,
            'amount': '500.00',
            'description': 'Тест',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert
        assert response.status_code == 404
    
    
    async def test_create_pay_link_signature_valid(self, test_payment_client, payment_seed):
        """
        Проверяем что сигнатура в URL валидна.
        
        Пересчитываем сигнатуру и сравниваем с той что в URL.
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'ttl_days': 30,
            'amount': '750.50',
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
        Проверяем что создаётся запись в payed_subs со статусом pending.
        """
        # Arrange
        payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'ttl_days': 30,
            'amount': '1000.00',
            'description': 'VIP план',
        }
        
        # Act
        response = await test_payment_client.post('/api/v1/robokassa/get_pay_link', json=payload)
        
        # Assert
        data = response.json()
        parsed_url = urlparse(data['payment_url'])
        query_params = parse_qs(parsed_url.query)
        order_id = int(query_params['InvId'][0])
        
        # Проверяем запись в БД
        async with db_pool.acquire() as conn:
            order = await conn.fetchrow("""
                SELECT id, user_id, sub_plan_id, is_active, status
                FROM payed_subs
                WHERE id = $1
            """, order_id)
        
        assert order is not None
        assert order['user_id'] == payment_seed['user_id']
        assert order['sub_plan_id'] == payment_seed['plan_id']
        assert order['is_active'] is False  # Ещё не активна
        assert order['status'] == 1  # pending


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
            'ttl_days': 30,
            'amount': '500.00',
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
            csrf_token=csrf_token,
            amount='500.00'
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
                SELECT is_active, status, expire_date
                FROM payed_subs
                WHERE id = $1
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
            'OutSum': '500.00',
            'InvId': 999,
            'SignatureValue': 'invalid_signature_hash_12345',
            'Shp_user_id': payment_seed['user_id'],
            'Shp_csrf_token': 'fake_token',
            'Shp_sub_plan_id': payment_seed['plan_id'],
            'Shp_expire_date': datetime.now().isoformat(),
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
            'ttl_days': 30,
            'amount': '500.00',
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
            csrf_token=csrf_token,
            amount='500.00'
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
        При активации новой подписки старая деактивируется.
        """
        # Arrange - создаём старую активную подписку
        async with db_pool.acquire() as conn:
            old_order_id = await conn.fetchval("""
                INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
                VALUES ($1, $2, true, 2, now() + interval '10 days')
                RETURNING id
            """, payment_seed['user_id'], payment_seed['plan_id'])
        
        # Создаём новый order через API
        create_link_payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'ttl_days': 30,
            'amount': '500.00',
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
            csrf_token=csrf_token,
            amount='500.00'
        )
        
        # Act
        await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        
        # Assert - старая подписка деактивирована
        async with db_pool.acquire() as conn:
            old_order = await conn.fetchrow("""
                SELECT is_active FROM payed_subs WHERE id = $1
            """, old_order_id)
            
            new_order = await conn.fetchrow("""
                SELECT is_active FROM payed_subs WHERE id = $1
            """, new_order_id)
        
        assert old_order['is_active'] is False
        assert new_order['is_active'] is True
    
    
    async def test_webhook_enqueues_arq_job(self, test_payment_client, payment_seed, arq_pool):
        """
        Webhook ставит задачу action_on_core_proto_by_sub_plan в Arq.
        """
        # Arrange
        create_link_payload = {
            'user_id': payment_seed['user_id'],
            'sub_plan_id': payment_seed['plan_id'],
            'ttl_days': 30,
            'amount': '500.00',
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
            csrf_token=csrf_token,
            amount='500.00'
        )
        
        # Act
        await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        
        # Assert - проверяем что задача в Arq
        # Получаем последнюю задачу из очереди
        jobs = await arq_pool.queued_jobs()
        assert len(jobs) > 0
        
        # Проверяем что последняя задача - это action_on_core_proto_by_sub_plan
        last_job = jobs[-1]
        assert last_job.function == 'action_on_core_proto_by_sub_plan'
