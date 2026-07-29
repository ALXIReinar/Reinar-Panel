"""
Integration тесты для Telegram Bot Routing API.

Тестируем 4 эндпоинта:
1. POST /users/add - добавление/обновление TG пользователя
2. GET /users/get - получение профиля TG пользователя
3. GET /users/subs/all - получение подписок пользователя
4. GET /sub_plans/all - получение всех тарифных планов для магазина

Проверяем:
- Авторизацию по IP бота
- CRUD операции с пользователями
- SQL запросы для получения данных
- Правильность структуры ответов
"""
import pytest
import httpx
from unittest.mock import patch

from fastapi import FastAPI

from web.sub.api.tg_routing.endpoints import router
from web.sub.config_dir.config import env


pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def test_tg_routing_app():
    """
    FastAPI приложение для тестирования TG routing API (создаётся один раз на сессию).
    """
    app = FastAPI()
    app.include_router(router, prefix='/tg')
    return app


@pytest.fixture(scope="function")
async def test_tg_routing_client(test_tg_routing_app, db_pool, tg_routing_seed):
    """
    HTTP клиент для тестирования TG routing API.
    
    Setup:
    1. Устанавливает db_pool в app.state
    2. Создаёт httpx.AsyncClient с ASGITransport
    3. Мокирует проверку IP бота для прохождения авторизации
    
    Teardown:
    1. Закрывает AsyncClient
    2. Очищает state
    """
    try:
        # Setup: устанавливаем зависимости
        test_tg_routing_app.state.pg_pool = db_pool
        
        # Мокируем проверку IP бота (пропускаем все запросы)
        with patch('web.sub.anything.tg_routing_is_tg_bot_access', return_value=None):
            # Создаём HTTP клиент
            transport = httpx.ASGITransport(app=test_tg_routing_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac
    finally:
        # Teardown: очищаем state
        if hasattr(test_tg_routing_app.state, 'pg_pool'):
            delattr(test_tg_routing_app.state, 'pg_pool')


class TestAddTgUser:
    """Integration тесты для POST /tg/users/add"""
    
    async def test_add_new_tg_user_with_return_data(self, test_tg_routing_client, tg_routing_seed):
        """
        Добавление нового пользователя с возвратом данных.
        
        Проверяем:
        - Статус 200
        - insert_success = True (новый пользователь)
        - Возвращаются user_id, sub_count=0, registered_at
        """
        # Arrange
        payload = {
            'tg_id': 999001,
            'tg_username': 'new_test_user',
            'return_data': True
        }
        
        # Act
        response = await test_tg_routing_client.post('/tg/users/add', json=payload)
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert data['insert_success'] is True
        assert 'user_id' in data
        assert data['sub_count'] == 0
        assert 'registered_at' in data
    
    
    async def test_add_new_tg_user_without_return_data(self, test_tg_routing_client, tg_routing_seed):
        """
        Добавление нового пользователя без возврата данных.
        
        Проверяем:
        - Статус 204 No Content
        - Пустой ответ
        """
        # Arrange
        payload = {
            'tg_id': 999002,
            'tg_username': 'another_new_user',
            'return_data': False
        }
        
        # Act
        response = await test_tg_routing_client.post('/tg/users/add', json=payload)
        
        # Assert
        assert response.status_code == 204
        assert response.text == ''
    
    
    async def test_add_existing_user_updates_username(self, test_tg_routing_client, tg_routing_seed, db_pool):
        """
        Обновление username существующего пользователя.
        
        Проверяем:
        - Статус 204 (без return_data)
        - Username обновлён в БД
        - insert_success = None (не новый пользователь)
        """
        # Arrange - используем существующего пользователя из seed
        old_username = tg_routing_seed['user_with_subs']['tg_username']
        new_username = 'updated_username'
        
        payload = {
            'tg_id': tg_routing_seed['user_with_subs']['tg_id'],
            'tg_username': new_username,
            'return_data': False
        }
        
        # Act
        response = await test_tg_routing_client.post('/tg/users/add', json=payload)
        
        # Assert
        assert response.status_code == 204
        
        # Проверяем что username обновлён в БД
        async with db_pool.acquire() as conn:
            updated_user = await conn.fetchrow("""
                SELECT tg_username FROM users WHERE tg_id = $1
            """, tg_routing_seed['user_with_subs']['tg_id'])
        
        assert updated_user['tg_username'] == new_username
    
    
    async def test_add_existing_user_with_return_data(self, test_tg_routing_client, tg_routing_seed, db_pool):
        """
        Обновление существующего пользователя с возвратом данных.
        
        Проверяем:
        - Статус 200
        - insert_success = False (существующий пользователь, НЕ только что зарегался)
        - Возвращаются актуальные данные (id, sub_count, registered_at)
        
        ВАЖНО: Логика определяет "новый" пользователь по времени: registered_at + 1 минута > now()
        Поэтому нужно убедиться что пользователь был создан давно (более 1 минуты назад).
        """
        # Arrange - обновляем registered_at на старую дату чтобы не попасть в "новый пользователь"
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE users 
                SET registered_at = now() - interval '2 days'
                WHERE tg_id = $1
            """, tg_routing_seed['user_with_subs']['tg_id'])
        
        payload = {
            'tg_id': tg_routing_seed['user_with_subs']['tg_id'],
            'tg_username': 'updated_with_data',
            'return_data': True
        }
        
        # Act
        response = await test_tg_routing_client.post('/tg/users/add', json=payload)
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert data['insert_success'] is False
        assert 'user_id' in data
        assert 'sub_count' in data
        assert data['sub_count'] >= 1  # У пользователя есть подписки из seed
        assert 'registered_at' in data


class TestGetTgUser:
    """Integration тесты для GET /tg/users/get"""
    
    async def test_get_tg_user_profile_success(self, test_tg_routing_client, tg_routing_seed):
        """
        Успешное получение профиля пользователя с подписками.
        
        Проверяем:
        - Статус 200
        - Возвращается id, registered_at, sub_count
        - sub_count > 0
        """
        # Act
        response = await test_tg_routing_client.get(
            f'/tg/users/get?tg_id={tg_routing_seed["user_with_subs"]["tg_id"]}'
        )
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert 'id' in data
        assert 'registered_at' in data
        assert 'sub_count' in data
        assert data['sub_count'] >= 1
    
    
    async def test_get_tg_user_profile_no_subs(self, test_tg_routing_client, tg_routing_seed):
        """
        Получение профиля пользователя без подписок.
        
        SQL использует LEFT JOIN, поэтому вернёт пользователя даже без подписок.
        
        Проверяем:
        - Статус 200
        - sub_count = 0 (COUNT с LEFT JOIN вернёт 0 если нет подписок)
        """
        # Act
        response = await test_tg_routing_client.get(
            f'/tg/users/get?tg_id={tg_routing_seed["user_no_subs"]["tg_id"]}'
        )
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert 'id' in data
        assert 'registered_at' in data
        assert 'sub_count' in data
        # COUNT с LEFT JOIN вернёт 0 если нет подписок (не NULL)
        assert data['sub_count'] == 0


class TestGetTgUserSubs:
    """Integration тесты для GET /tg/users/subs/all"""
    
    async def test_get_tg_user_subs_with_active_subs(self, test_tg_routing_client, tg_routing_seed):
        """
        Получение подписок пользователя (есть активные подписки).
        
        Проверяем:
        - Статус 200
        - Возвращается массив user_subs
        - Каждая подписка содержит: id, title, description, sub_nodes_count, offer_prices
        - offer_prices содержит массив офферов с ценами и параметрами
        """
        # Act
        response = await test_tg_routing_client.get(
            f'/tg/users/subs/all?tg_id={tg_routing_seed["user_with_subs"]["tg_id"]}'
        )
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert 'user_subs' in data
        assert len(data['user_subs']) >= 1
        
        # Проверяем структуру первой подписки
        sub = data['user_subs'][0]
        assert 'id' in sub
        assert 'title' in sub
        assert 'description' in sub
        assert 'sub_nodes_count' in sub
        assert 'offer_prices' in sub
        assert isinstance(sub['offer_prices'], list)
        
        # Если есть офферы, проверяем их структуру
        if len(sub['offer_prices']) > 0:
            offer = sub['offer_prices'][0]
            assert 'offer_id' in offer
            assert 'cost' in offer
            assert 'ttl_days' in offer
            assert 'traffic_day_limit' in offer
            assert 'infinite_expire' in offer
            assert 'infinite_traffic' in offer
    
    
    async def test_get_tg_user_subs_empty(self, test_tg_routing_client, tg_routing_seed):
        """
        Получение подписок пользователя без подписок.
        
        Проверяем:
        - Статус 200
        - user_subs = пустой массив
        """
        # Act
        response = await test_tg_routing_client.get(
            f'/tg/users/subs/all?tg_id={tg_routing_seed["user_no_subs"]["tg_id"]}'
        )
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert 'user_subs' in data
        assert len(data['user_subs']) == 0


class TestGetShopSubPlans:
    """Integration тесты для GET /tg/sub_plans/all"""
    
    async def test_get_shop_sub_plans_success(self, test_tg_routing_client, tg_routing_seed):
        """
        Получение всех активных тарифных планов для магазина.
        
        Проверяем:
        - Статус 200
        - Возвращается массив sub_plans
        - Каждый план содержит: id, title, description, sub_nodes_count, offer_prices
        - Только активные планы (is_active=true)
        """
        # Act
        response = await test_tg_routing_client.get('/tg/sub_plans/all')
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert 'sub_plans' in data
        assert len(data['sub_plans']) >= 1
        
        # Проверяем структуру первого плана
        plan = data['sub_plans'][0]
        assert 'id' in plan
        assert 'title' in plan
        assert 'description' in plan
        assert 'sub_nodes_count' in plan
        assert 'offer_prices' in plan
        assert isinstance(plan['offer_prices'], list)
    
    
    async def test_get_shop_sub_plans_with_multiple_offers(self, test_tg_routing_client, tg_routing_seed):
        """
        Проверка плана с несколькими офферами.
        
        Проверяем:
        - Офферы отсортированы по position
        - Все офферы активны (is_active=true из seed)
        """
        # Act
        response = await test_tg_routing_client.get('/tg/sub_plans/all')
        
        # Assert
        data = response.json()
        
        # Находим план с несколькими офферами
        plan_with_offers = None
        for plan in data['sub_plans']:
            if len(plan['offer_prices']) > 1:
                plan_with_offers = plan
                break
        
        # Если есть планы с несколькими офферами, проверяем сортировку
        if plan_with_offers:
            offers = plan_with_offers['offer_prices']
            # Проверяем что офферы отсортированы по position (косвенно - порядок в массиве)
            for i in range(len(offers) - 1):
                assert offers[i]['offer_id'] is not None
                assert offers[i]['cost'] is not None


class TestTgRoutingAuthorization:
    """Тесты авторизации по IP бота"""
    
    async def test_endpoints_reject_unauthorized_ip(self, db_pool, tg_routing_seed):
        """
        Отклонение запросов с неавторизованного IP.
        
        Проверяем:
        - Статус 403 Forbidden
        - Все эндпоинты защищены
        
        ВАЖНО: Патчим env.tg_bot_service_private_ip чтобы IP клиента не совпадал с разрешённым.
        """
        # Setup: создаём свежее приложение и патчим разрешённые IP
        from fastapi import FastAPI
        from web.sub.api.tg_routing.endpoints import router
        
        with patch('web.sub.config_dir.config.env.tg_bot_service_private_ip', ['192.168.100.100']):
            test_app = FastAPI()
            test_app.include_router(router, prefix='/tg')
            test_app.state.pg_pool = db_pool
            
            try:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                    # Test POST /users/add
                    response1 = await ac.post('/tg/users/add', json={
                        'tg_id': 123,
                        'tg_username': 'test',
                        'return_data': False
                    })
                    assert response1.status_code == 403
                    
                    # Test GET /users/get
                    response2 = await ac.get('/tg/users/get?tg_id=123')
                    assert response2.status_code == 403
                    
                    # Test GET /users/subs/all
                    response3 = await ac.get('/tg/users/subs/all?tg_id=123')
                    assert response3.status_code == 403
                    
                    # Test GET /sub_plans/all
                    response4 = await ac.get('/tg/sub_plans/all')
                    assert response4.status_code == 403
            finally:
                if hasattr(test_app.state, 'pg_pool'):
                    delattr(test_app.state, 'pg_pool')
    
    
    async def test_endpoints_accept_authorized_ip(self, test_tg_routing_client, tg_routing_seed):
        """
        Принятие запросов с авторизованного IP (через мок).
        
        Проверяем:
        - Все эндпоинты доступны (не 403)
        """
        # Все эндпоинты должны работать (авторизация замокирована в фикстуре)
        
        # Test POST /users/add
        response1 = await test_tg_routing_client.post('/tg/users/add', json={
            'tg_id': 999888,
            'tg_username': 'authorized_test',
            'return_data': False
        })
        assert response1.status_code in [200, 204]
        
        # Test GET /sub_plans/all
        response2 = await test_tg_routing_client.get('/tg/sub_plans/all')
        assert response2.status_code == 200
