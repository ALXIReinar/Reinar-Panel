"""
Интеграционные тесты для POST /private/users/bulk/add
Тестируют bulk создание пользователей

КРИТИЧНЫЕ ПРОВЕРКИ:
1. Создание пользователей в таблице users
2. Валидация входных данных (tg_username, tg_id)
3. Обработка дубликатов через ON CONFLICT DO NOTHING
"""
import pytest


class TestBulkAddSuccess:
    """Тесты успешного создания пользователей"""
    
    @pytest.mark.asyncio
    async def test_bulk_add_creates_users(self, client, db_pool):
        """Успешное создание пользователей"""
        users_data = [
            {"tg_username": "new_user_1", "tg_id": 3000001},
            {"tg_username": "new_user_2", "tg_id": 3000002}
        ]
        
        response = await client.post(
            "/api/v1/private/users/bulk/add",
            json={"users": users_data}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "users" in data
        assert len(data["users"]) == 2
        
        # Проверяем что пользователи созданы в БД
        async with db_pool.acquire() as conn:
            users = await conn.fetch(
                "SELECT id, tg_username, tg_id FROM users WHERE tg_username = ANY($1) ORDER BY tg_username",
                ["new_user_1", "new_user_2"]
            )
            assert len(users) == 2
            assert users[0]["tg_username"] == "new_user_1"
            assert users[0]["tg_id"] == 3000001
            assert users[1]["tg_username"] == "new_user_2"
            assert users[1]["tg_id"] == 3000002
    
    @pytest.mark.asyncio
    async def test_bulk_add_returns_created_users(self, client, db_pool):
        """Проверка правильного формата возвращаемых данных"""
        users_data = [
            {"tg_username": "return_test_user", "tg_id": 3000200}
        ]
        
        response = await client.post(
            "/api/v1/private/users/bulk/add",
            json={"users": users_data}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Проверяем структуру ответа
        assert "success" in data
        assert "message" in data
        assert "users" in data
        
        users = data["users"]
        assert len(users) == 1
        
        # Проверяем что возвращённый пользователь содержит необходимые поля
        user = users[0]
        assert "id" in user
        assert "tg_username" in user
        assert user["tg_username"] == "return_test_user"


class TestBulkAddValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_bulk_add_empty_users_list(self, client):
        """Пустой массив users возвращает успешный ответ с пустым результатом"""
        response = await client.post(
            "/api/v1/private/users/bulk/add",
            json={"users": []}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["users"]) == 0
    
    @pytest.mark.asyncio
    async def test_bulk_add_duplicate_tg_username_in_request(self, client, db_pool):
        """Дубликаты tg_username в одном запросе - игнорируются через ON CONFLICT DO NOTHING"""
        # В запросе 2 пользователя с одинаковым tg_username
        users_data = [
            {"tg_username": "duplicate_user", "tg_id": 3000801},
            {"tg_username": "duplicate_user", "tg_id": 3000802}
        ]
        
        response = await client.post(
            "/api/v1/private/users/bulk/add",
            json={"users": users_data}
        )
        
        # ON CONFLICT DO NOTHING игнорирует дубликаты - создаётся только первый
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что создан только один пользователь (второй проигнорирован)
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE tg_username = $1",
                "duplicate_user"
            )
            assert count == 1  # Только первый создался, второй проигнорирован
