"""
Интеграционные тесты для GET /private/users/all и GET /private/users/{user_id}
Тестируют получение списка пользователей с пагинацией и получение одного пользователя

КРИТИЧНЫЕ ПРОВЕРКИ:
1. Пагинация работает корректно (курсор last_id)
2. Сортировка asc/desc
3. Формат ответа: пользователь + массив subscriptions
4. Все поля корректны и агрегированы через JSON
"""
import pytest


@pytest.fixture
async def users_for_get(db_pool, sub_plan_seed):
    """
    Создаём тестовых пользователей с подписками для GET endpoints:
    - 5 пользователей
    - У некоторых будет несколько подписок (проверка агрегации)
    """
    async with db_pool.acquire() as conn:
        plan_id_1 = sub_plan_seed["plan_id_1"]
        plan_id_2 = sub_plan_seed["plan_id_2"]
        
        user_ids = []
        
        # Создаём 5 пользователей
        for i in range(5):
            user_id = await conn.fetchval(
                """
                INSERT INTO users (tg_id, tg_username)
                VALUES ($1, $2)
                RETURNING id
                """,
                5000000 + i,
                f"get_user_{i}"
            )
            user_ids.append(user_id)
            
            # Создаём pay_order для пользователя
            order_id = await conn.fetchval(
                """
                INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost)
                VALUES ($1, 2, NOW(), false, false, 0)
                RETURNING id
                """,
                user_id
            )
            
            # Создаём активную подписку
            await conn.execute(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited, 
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                """,
                user_id, order_id, plan_id_1,
                f"uuid-get-{i:04d}-1111-2222-33333333",
                f"b64_get_user_{i}_token"
            )
        
        # Пользователь 0: добавляем вторую подписку (inactive) 
        order_id_inactive = await conn.fetchval(
            """
            INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) 
            VALUES ($1, 3, NOW(), false, false, 0) 
            RETURNING id
            """,
            user_ids[0]
        )
        await conn.execute(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, false, false, NOW() + INTERVAL '60 days', $4, $5, false, false)
            """,
            user_ids[0], order_id_inactive, plan_id_2,
            "uuid-get-0000-2222-3333-44444444",
            "b64_get_user_0_inactive"
        )
        
        # Пользователь 1: добавляем вторую активную подписку (newer)
        order_id_new = await conn.fetchval(
            """
            INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) 
            VALUES ($1, 2, NOW(), false, false, 0) 
            RETURNING id
            """,
            user_ids[1]
        )
        await conn.execute(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '90 days', $4, $5, false, false)
            """,
            user_ids[1], order_id_new, plan_id_2,
            "uuid-get-0001-2222-3333-55555555",
            "b64_get_user_1_new"
        )
        
        return {
            "user_ids": user_ids,
            "plan_id_1": plan_id_1,
            "plan_id_2": plan_id_2,
        }


class TestGetUsers:
    """Тесты GET /private/users/all (список пользователей с пагинацией)"""
    
    @pytest.mark.asyncio
    async def test_get_users_default(self, client, users_for_get):
        """Получить список пользователей с параметрами по умолчанию"""
        response = await client.get("/api/v1/private/users/all")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "users" in data
        
        users = data["users"]
        assert len(users) == 5  # Все 5 пользователей
        
        # Проверяем формат записи
        first_user = users[0]
        assert "user_id" in first_user
        assert "tg_username" in first_user
        assert "online_status" in first_user
        assert "last_activity" in first_user
        assert "registered_at" in first_user
        assert "subscriptions" in first_user
        assert isinstance(first_user["subscriptions"], list)
    
    @pytest.mark.asyncio
    async def test_get_users_subscriptions_aggregated(self, client, users_for_get):
        """Проверка что subscriptions агрегированы в JSON массив"""
        response = await client.get("/api/v1/private/users/all")
        
        assert response.status_code == 200
        data = response.json()
        users = data["users"]
        
        # Находим пользователя 0 (у него 2 подписки)
        user_0 = next(u for u in users if u["user_id"] == users_for_get["user_ids"][0])
        assert len(user_0["subscriptions"]) == 2
        
        # Проверяем структуру подписки
        first_sub = user_0["subscriptions"][0]
        assert "sub_id" in first_sub
        assert "sub_plan_title" in first_sub
        assert "is_active" in first_sub
        assert "is_limited" in first_sub
        assert "expire_date" in first_sub
        assert "traffic_used_total" in first_sub
        assert "traffic_used_today" in first_sub
        assert "infinite_traffic" in first_sub
        assert "infinite_expire" in first_sub
        
        # Пользователь 1 (2 подписки)
        user_1 = next(u for u in users if u["user_id"] == users_for_get["user_ids"][1])
        assert len(user_1["subscriptions"]) == 2
        
        # Остальные пользователи (по 1 подписке)
        for i in range(2, 5):
            user = next(u for u in users if u["user_id"] == users_for_get["user_ids"][i])
            assert len(user["subscriptions"]) == 1
    
    @pytest.mark.asyncio
    async def test_get_users_pagination_desc(self, client, users_for_get):
        """Пагинация работает корректно (desc сортировка)"""
        # Первая страница: limit=2, sort=desc
        response1 = await client.get("/api/v1/private/users/all?limit=2&sort_by=desc")
        
        assert response1.status_code == 200
        data1 = response1.json()
        users1 = data1["users"]
        assert len(users1) == 2
        
        # Проверяем что сортировка desc (больший user_id первым)
        assert users1[0]["user_id"] > users1[1]["user_id"]
        
        # Вторая страница: используем last_id из первой страницы
        last_id = users1[-1]["user_id"]
        response2 = await client.get(f"/api/v1/private/users/all?limit=2&sort_by=desc&last_id={last_id}")
        
        assert response2.status_code == 200
        data2 = response2.json()
        users2 = data2["users"]
        assert len(users2) == 2
        
        # Проверяем что нет дубликатов
        user_ids_page1 = {u["user_id"] for u in users1}
        user_ids_page2 = {u["user_id"] for u in users2}
        assert len(user_ids_page1 & user_ids_page2) == 0
        
        # Проверяем что user_id на второй странице меньше
        assert all(u["user_id"] < last_id for u in users2)
    
    @pytest.mark.asyncio
    async def test_get_users_pagination_asc(self, client, users_for_get):
        """Пагинация работает корректно (asc сортировка)"""
        # Первая страница: limit=2, sort=asc
        response1 = await client.get("/api/v1/private/users/all?limit=2&sort_by=asc")
        
        assert response1.status_code == 200
        data1 = response1.json()
        users1 = data1["users"]
        assert len(users1) == 2
        
        # Проверяем что сортировка asc (меньший user_id первым)
        assert users1[0]["user_id"] < users1[1]["user_id"]
        
        # Вторая страница
        last_id = users1[-1]["user_id"]
        response2 = await client.get(f"/api/v1/private/users/all?limit=2&sort_by=asc&last_id={last_id}")
        
        assert response2.status_code == 200
        data2 = response2.json()
        users2 = data2["users"]
        assert len(users2) == 2
        
        # Проверяем что user_id на второй странице больше
        assert all(u["user_id"] > last_id for u in users2)
    
    @pytest.mark.asyncio
    async def test_get_users_limit(self, client, users_for_get):
        """Лимит работает корректно"""
        response = await client.get("/api/v1/private/users/all?limit=3")
        
        assert response.status_code == 200
        data = response.json()
        users = data["users"]
        assert len(users) == 3
    
    @pytest.mark.asyncio
    async def test_get_users_empty_list(self, client, db_pool):
        """Пустой список если нет пользователей"""
        # Очищаем пользователей
        async with db_pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE")
        
        response = await client.get("/api/v1/private/users/all")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["users"] == []


class TestGetUserById:
    """Тесты GET /private/users/{user_id} (получить одного пользователя)"""
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_success(self, client, users_for_get):
        """Успешное получение пользователя по user_id"""
        user_id = users_for_get["user_ids"][0]
        
        response = await client.get(f"/api/v1/private/users/{user_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "user" in data
        assert "subscriptions" in data
        
        user = data["user"]
        assert user["user_id"] == user_id
        assert user["tg_username"] == "get_user_0"
        
        # Проверяем полноту данных пользователя
        assert "tg_id" in user
        assert "online_status" in user
        assert "last_activity" in user
        assert "registered_at" in user
        
        # Проверяем массив подписок
        subscriptions = data["subscriptions"]
        assert isinstance(subscriptions, list)
        assert len(subscriptions) == 2  # У пользователя 0 две подписки
        
        # Проверяем структуру подписки
        first_sub = subscriptions[0]
        assert "user_sub_id" in first_sub
        assert "order_id" in first_sub
        assert "b64_id" in first_sub
        assert "uuid" in first_sub
        assert "traffic_used_day_mb" in first_sub
        assert "traffic_limit_day" in first_sub
        assert "infinite_traffic" in first_sub
        assert "expire_date" in first_sub
        assert "infinite_expire" in first_sub
        assert "is_active" in first_sub
        assert "is_limited" in first_sub
        assert "sub_bought_at" in first_sub
        assert "sub_plan_id" in first_sub
        assert "sub_plan_title" in first_sub
        assert "sub_plan_active" in first_sub
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, client):
        """404 для несуществующего user_id"""
        response = await client.get("/api/v1/private/users/99999")
        
        assert response.status_code == 404
        data = response.json()
        assert "success" in data["detail"]
        assert data["detail"]["success"] is False
        assert "message" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_all_fields(self, client, users_for_get):
        """Проверка корректности всех полей"""
        user_id = users_for_get["user_ids"][2]
        
        response = await client.get(f"/api/v1/private/users/{user_id}")
        
        assert response.status_code == 200
        data = response.json()
        user = data["user"]
        subscriptions = data["subscriptions"]
        
        # Проверяем типы данных пользователя
        assert isinstance(user["user_id"], int)
        assert isinstance(user["tg_username"], str)
        assert isinstance(user["tg_id"], int)
        
        # Проверяем значения
        assert user["user_id"] == user_id
        assert user["tg_username"] == "get_user_2"
        assert user["tg_id"] == 5000002
        
        # Проверяем подписки
        assert len(subscriptions) == 1
        sub = subscriptions[0]
        assert isinstance(sub["user_sub_id"], int)
        assert isinstance(sub["sub_plan_id"], int)
        assert isinstance(sub["is_active"], bool)
        assert isinstance(sub["is_limited"], bool)
        assert sub["is_active"] is True
        assert sub["is_limited"] is False
