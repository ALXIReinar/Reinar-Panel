"""
Интеграционные тесты для GET /private/users/get и GET /private/users/get_by_id
Тестируют получение списка пользователей с пагинацией и получение одного пользователя

КРИТИЧНЫЕ ПРОВЕРКИ:
1. Пагинация работает корректно (курсор last_id)
2. Сортировка asc/desc
3. Ровно 1 запись на пользователя (latest subscription priority)
4. Формат ответа и все поля корректны
"""
import pytest


@pytest.fixture
async def users_for_get(pg_pool, virtual_node_seed, sub_plan_seed):
    """
    Создаём тестовых пользователей с подписками для GET endpoints:
    - 5 пользователей с активными подписками
    - У некоторых будет несколько подписок (проверка latest priority)
    """
    async with pg_pool.acquire() as conn:
        # Привязываем vnode к плану
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        plan_id_1 = sub_plan_seed["plan_id_1"]
        plan_id_2 = sub_plan_seed["plan_id_2"]
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2), ($1, $3) ON CONFLICT DO NOTHING",
            vnode_id_1, plan_id_1, plan_id_2
        )
        
        user_ids = []
        order_ids = []
        
        # Создаём 5 пользователей
        for i in range(5):
            user_id = await conn.fetchval(
                """
                INSERT INTO users (tg_id, tg_username, uuid, b64_id, traffic_used_day_mb)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                5000000 + i,
                f"get_user_{i}",
                f"uuid-get-{i:04d}-1111-2222-33333333",
                f"b64_get_user_{i}_token",
                i * 100  # разный трафик
            )
            user_ids.append(user_id)
            
            # Создаём активную подписку
            order_id = await conn.fetchval(
                """
                INSERT INTO payed_subs (user_id, sub_plan_id, is_active, is_limited, expire_date, status)
                VALUES ($1, $2, true, false, NOW() + INTERVAL '30 days', 2)
                RETURNING id
                """,
                user_id, plan_id_1
            )
            order_ids.append(order_id)
        
        # Пользователь 0: добавляем вторую подписку (newer id, but inactive) - должна быть выбрана активная
        order_id_inactive = await conn.fetchval(
            """
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, is_limited, expire_date, status)
            VALUES ($1, $2, false, false, NOW() + INTERVAL '60 days', 3)
            RETURNING id
            """,
            user_ids[0], plan_id_2
        )
        
        # Пользователь 1: добавляем вторую активную подписку (newer id) - должна быть выбрана она
        order_id_new = await conn.fetchval(
            """
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, is_limited, expire_date, status)
            VALUES ($1, $2, true, false, NOW() + INTERVAL '90 days', 2)
            RETURNING id
            """,
            user_ids[1], plan_id_2
        )
        
        return {
            "user_ids": user_ids,
            "order_ids": order_ids,
            "plan_id_1": plan_id_1,
            "plan_id_2": plan_id_2,
            "order_id_inactive": order_id_inactive,
            "order_id_new": order_id_new,
        }


class TestGetUsers:
    """Тесты GET /private/users/get (список пользователей с пагинацией)"""
    
    @pytest.mark.asyncio
    async def test_get_users_default(self, client, users_for_get):
        """Получить список пользователей с параметрами по умолчанию"""
        response = await client.get("/api/v1/private/users/get")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "users" in data
        
        users = data["users"]
        assert len(users) == 5  # Все 5 пользователей
        
        # Проверяем формат записи
        first_user = users[0]
        assert "user_id" in first_user
        assert "order_id" in first_user
        assert "tg_username" in first_user
        assert "traffic_used_day_mb" in first_user
        assert "traffic_limit_day" in first_user
        assert "expire_date" in first_user
        assert "created_at" in first_user
        assert "sub_active" in first_user
        assert "sub_limited" in first_user
        assert "online_status" in first_user
        assert "last_activity" in first_user
    
    @pytest.mark.asyncio
    async def test_get_users_pagination_desc(self, client, users_for_get):
        """Пагинация работает корректно (desc сортировка)"""
        # Первая страница: limit=2, sort=desc
        response1 = await client.get("/api/v1/private/users/get?limit=2&sort_by=desc")
        
        assert response1.status_code == 200
        data1 = response1.json()
        users1 = data1["users"]
        assert len(users1) == 2
        
        # Проверяем что сортировка desc (больший user_id первым)
        assert users1[0]["user_id"] > users1[1]["user_id"]
        
        # Вторая страница: используем last_id из первой страницы
        last_id = users1[-1]["user_id"]
        response2 = await client.get(f"/api/v1/private/users/get?limit=2&sort_by=desc&last_id={last_id}")
        
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
        response1 = await client.get("/api/v1/private/users/get?limit=2&sort_by=asc")
        
        assert response1.status_code == 200
        data1 = response1.json()
        users1 = data1["users"]
        assert len(users1) == 2
        
        # Проверяем что сортировка asc (меньший user_id первым)
        assert users1[0]["user_id"] < users1[1]["user_id"]
        
        # Вторая страница
        last_id = users1[-1]["user_id"]
        response2 = await client.get(f"/api/v1/private/users/get?limit=2&sort_by=asc&last_id={last_id}")
        
        assert response2.status_code == 200
        data2 = response2.json()
        users2 = data2["users"]
        assert len(users2) == 2
        
        # Проверяем что user_id на второй странице больше
        assert all(u["user_id"] > last_id for u in users2)
    
    @pytest.mark.asyncio
    async def test_get_users_limit(self, client, users_for_get):
        """Лимит работает корректно"""
        response = await client.get("/api/v1/private/users/get?limit=3")
        
        assert response.status_code == 200
        data = response.json()
        users = data["users"]
        assert len(users) == 3
    
    @pytest.mark.asyncio
    async def test_get_users_one_record_per_user(self, client, users_for_get):
        """Возвращается ровно 1 запись на пользователя (latest subscription)"""
        response = await client.get("/api/v1/private/users/get")
        
        assert response.status_code == 200
        data = response.json()
        users = data["users"]
        
        # Проверяем что нет дубликатов user_id
        user_ids = [u["user_id"] for u in users]
        assert len(user_ids) == len(set(user_ids))  # Уникальные user_id
        
        # Проверяем user 0: должна быть выбрана активная подписка (не inactive)
        user_0 = next(u for u in users if u["user_id"] == users_for_get["user_ids"][0])
        assert user_0["order_id"] == users_for_get["order_ids"][0]  # Первая подписка (активная)
        assert user_0["sub_active"] is True
        
        # Проверяем user 1: должна быть выбрана новая активная подписка (больший id)
        user_1 = next(u for u in users if u["user_id"] == users_for_get["user_ids"][1])
        assert user_1["order_id"] == users_for_get["order_id_new"]  # Новая подписка
        assert user_1["sub_active"] is True
    
    @pytest.mark.asyncio
    async def test_get_users_empty_list(self, client, pg_pool):
        """Пустой список если нет пользователей"""
        # Очищаем пользователей
        async with pg_pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE")
        
        response = await client.get("/api/v1/private/users/get")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["users"] == []


class TestGetUserById:
    """Тесты GET /private/users/get_by_id (получить одного пользователя)"""
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_success(self, client, users_for_get, pg_pool):
        """Успешное получение пользователя по order_id"""
        order_id = users_for_get["order_ids"][0]
        
        response = await client.get(f"/api/v1/private/users/get_by_id?oid={order_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "user" in data
        
        user = data["user"]
        assert user["order_id"] == order_id
        assert user["user_id"] == users_for_get["user_ids"][0]
        assert user["tg_username"] == "get_user_0"
        
        # Проверяем полноту данных (расширенная информация)
        assert "uuid" in user
        assert "b64_id" in user
        assert "sub_plan_id" in user
        assert "sub_plan_name" in user
        assert "traffic_used_day_mb" in user
        assert "total_traffic_day" in user
        assert "online_status" in user
        assert "last_activity" in user
        assert "registered_at" in user
        assert "expire_date" in user
        assert "sub_created_at" in user
        assert "sub_active" in user
        assert "sub_limited" in user
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, client):
        """404 для несуществующего order_id"""
        response = await client.get("/api/v1/private/users/get_by_id?oid=99999")
        
        assert response.status_code == 404
        data = response.json()
        assert "success" in data["detail"]
        assert data["detail"]["success"] is False
        assert "message" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_get_user_by_id_all_fields(self, client, users_for_get, pg_pool):
        """Проверка корректности всех полей"""
        order_id = users_for_get["order_ids"][2]
        
        response = await client.get(f"/api/v1/private/users/get_by_id?oid={order_id}")
        
        assert response.status_code == 200
        data = response.json()
        user = data["user"]
        
        # Проверяем типы данных
        assert isinstance(user["user_id"], int)
        assert isinstance(user["order_id"], int)
        assert isinstance(user["tg_username"], str)
        assert isinstance(user["uuid"], str)
        assert isinstance(user["b64_id"], str)
        assert isinstance(user["sub_plan_id"], int)
        assert isinstance(user["sub_plan_name"], str)
        assert isinstance(user["traffic_used_day_mb"], int)
        assert isinstance(user["total_traffic_day"], int)
        assert isinstance(user["sub_active"], bool)
        assert isinstance(user["sub_limited"], bool)
        
        # Проверяем значения
        assert user["user_id"] == users_for_get["user_ids"][2]
        assert user["tg_username"] == "get_user_2"
        assert user["traffic_used_day_mb"] == 200  # i * 100 где i=2
        assert user["sub_plan_id"] == users_for_get["plan_id_1"]
        assert user["sub_active"] is True
        assert user["sub_limited"] is False
