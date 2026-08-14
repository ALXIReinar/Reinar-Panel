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
    
    
    async def test_webhook_enqueues_arq_job(self, test_payment_client, payment_seed, db_pool):
        """
        Webhook ставит задачу action_on_core_proto_by_sub_plan в Arq с корректными параметрами.
        
        Проверяет:
        1. Задача вызвана с правильным именем
        2. Параметры содержат корректные данные пользователя (uuid, sub_id)
        3. sub_nodes содержит все необходимые поля из proto_templates
        4. sub_nodes_outbox создан для всех нод из vnodes_sub_plans
        5. Структура данных соответствует ожиданиям ARQ воркера
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
        response = await test_payment_client.post('/api/v1/robokassa/webhook', data=webhook_data)
        assert response.status_code == 200
        
        # Assert 1: Задача поставлена в очередь
        test_payment_client.mock_arq.enqueue_job.assert_called_once()
        call_args = test_payment_client.mock_arq.enqueue_job.call_args
        
        # Assert 2: Название задачи корректно
        task_name = call_args[0][0]
        assert task_name == 'action_on_core_proto_by_sub_plan', \
            f"Ожидалось название задачи 'action_on_core_proto_by_sub_plan', получено: {task_name}"
        
        # Assert 3: Структура параметров (user_uuid, user_sub_id, sub_nodes, operation)
        assert len(call_args[0]) == 5, \
            f"Ожидалось 5 параметров (task_name, user_uuid, user_sub_id, sub_nodes, operation), получено: {len(call_args[0])}"
        
        user_uuid = call_args[0][1]
        user_sub_id = call_args[0][2]
        sub_nodes = call_args[0][3]
        operation = call_args[0][4]
        
        # Assert 4: user_uuid - валидный UUID
        import uuid as uuid_lib
        try:
            uuid_lib.UUID(user_uuid)
        except ValueError:
            pytest.fail(f"user_uuid не является валидным UUID: {user_uuid}")
        
        # Assert 5: user_sub_id - положительное целое число
        assert isinstance(user_sub_id, int) and user_sub_id > 0, \
            f"user_sub_id должен быть положительным int, получено: {user_sub_id} ({type(user_sub_id)})"
        
        # Assert 6: operation - ADD (1 или 'add')
        assert operation in (1, 'add'), \
            f"operation должна быть ADD (1 или 'add'), получено: {operation}"
        
        # Assert 7: sub_nodes - непустой список
        assert isinstance(sub_nodes, list) and len(sub_nodes) > 0, \
            f"sub_nodes должен быть непустым списком, получено: {type(sub_nodes)} с длиной {len(sub_nodes) if isinstance(sub_nodes, list) else 'N/A'}"
        
        # Assert 8: Каждая нода содержит все обязательные поля
        required_fields = {
            'node_proto_id', 'private_ip', 'api_port', 'metrics_port',
            'proto_python_lib', 'api_bulk_add_user_script', 'api_bulk_delete_user_script',
            'bulk_add_script_custom_params', 'bulk_delete_script_custom_params',
            'reload_core_command', 'config_path',
            'constant_user_data_obj', 'required_user_data_obj',
            'user_injectors', 'event_id'
        }
        
        for idx, node in enumerate(sub_nodes):
            missing_fields = required_fields - set(node.keys())
            assert not missing_fields, \
                f"Нода #{idx} ({node.get('node_proto_id', '?')}) не содержит обязательные поля: {missing_fields}"
            
            # Проверяем типы критичных полей
            assert isinstance(node['node_proto_id'], int), \
                f"node_proto_id должен быть int, получено: {type(node['node_proto_id'])}"
            assert isinstance(node['private_ip'], str) and len(node['private_ip']) > 0, \
                f"private_ip должен быть непустой строкой"
            assert isinstance(node['api_port'], int) and node['api_port'] > 0, \
                f"api_port должен быть положительным int"
            assert isinstance(node['proto_python_lib'], str), \
                f"proto_python_lib должен быть строкой"
            assert isinstance(node['user_injectors'], list), \
                f"user_injectors должен быть списком (может быть пустым)"
            assert isinstance(node['event_id'], int) and node['event_id'] > 0, \
                f"event_id должен быть положительным int (outbox record id)"
        
        # Assert 9: Проверяем что outbox записи созданы только для активных видимых нод
        async with db_pool.acquire() as conn:
            # Получаем ожидаемые node_proto_id - только активные видимые ноды
            # Фильтрация совпадает с get_core_proto_deps_by_user_id
            expected_node_ids = await conn.fetch("""
                SELECT vsp.node_proto_id
                FROM vnodes_sub_plans vsp
                JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
                JOIN nodes n ON n.id = np.node_id AND n.is_active = true
                WHERE vsp.sub_plan_id = $1
                ORDER BY vsp.node_proto_id
            """, payment_seed['plan_id'])
            
            expected_node_ids_set = {row['node_proto_id'] for row in expected_node_ids}
            actual_node_ids_set = {node['node_proto_id'] for node in sub_nodes}
            
            assert expected_node_ids_set == actual_node_ids_set, \
                f"sub_nodes содержит не те ноды. Ожидалось: {expected_node_ids_set}, получено: {actual_node_ids_set}"
            
            # Проверяем что outbox записи действительно созданы
            outbox_records = await conn.fetch("""
                SELECT id, user_uuid, user_sub_id, operation, node_proto_id
                FROM sub_nodes_outbox
                WHERE user_sub_id = $1
                ORDER BY node_proto_id
            """, user_sub_id)
            
            assert len(outbox_records) == len(sub_nodes), \
                f"Количество outbox записей ({len(outbox_records)}) не совпадает с количеством нод ({len(sub_nodes)})"
            
            outbox_node_ids = {rec['node_proto_id'] for rec in outbox_records}
            assert outbox_node_ids == expected_node_ids_set, \
                f"outbox записи созданы не для всех нод. Ожидалось: {expected_node_ids_set}, получено: {outbox_node_ids}"
            
            # Проверяем что outbox записи содержат корректные данные
            for rec in outbox_records:
                assert rec['user_uuid'] == user_uuid, \
                    f"outbox.user_uuid не совпадает с переданным в ARQ"
                assert rec['user_sub_id'] == user_sub_id, \
                    f"outbox.user_sub_id не совпадает с переданным в ARQ"
                assert rec['operation'] == 1, \
                    f"outbox.operation должна быть ADD (1), получено: {rec['operation']}"

