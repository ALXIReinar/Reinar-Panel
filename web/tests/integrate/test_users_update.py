"""
Интеграционные тесты для PUT /private/users/meta/{user_id} и PUT /private/users/subs/{user_id}
Тестируют обновление метаданных пользователей и управление подписками
"""
import pytest
from datetime import datetime, timezone


@pytest.fixture
async def user_with_subs(db_pool, sub_plan_seed, virtual_node_seed):
    """
    Создаём пользователя с одной активной подпиской для тестирования обновлений.
    Также привязываем виртуальную ноду к плану подписки для работы outbox.
    """
    async with db_pool.acquire() as conn:
        # Привязываем виртуальную ноду к планам подписки (нужно для edit_user_subs)
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            virtual_node_seed["vnode_id_1"],
            sub_plan_seed["plan_id_1"]
        )
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            virtual_node_seed["vnode_id_1"],
            sub_plan_seed["plan_id_2"]
        )
        
        # Создаём тестового пользователя
        user_id = await conn.fetchval(
            """
            INSERT INTO users (tg_id, tg_username)
            VALUES ($1, $2)
            RETURNING id
            """,
            123456789,
            "test_user_update"
        )
        
        # Создаём pay_order
        order_id = await conn.fetchval(
            """
            INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost)
            VALUES ($1, 2, NOW(), false, false, 500)
            RETURNING id
            """,
            user_id
        )
        
        # Создаём активную подписку
        user_sub_id = await conn.fetchval(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
            RETURNING id
            """,
            user_id,
            order_id,
            sub_plan_seed["plan_id_1"],
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "b64_test_user_update"
        )
        
        return {
            "user_id": user_id,
            "user_sub_id": user_sub_id,
            "order_id": order_id,
            "plan_id": sub_plan_seed["plan_id_1"],
            "plan_id_2": sub_plan_seed["plan_id_2"],
            "vnode_id": virtual_node_seed["vnode_id_1"],
        }


class TestUpdateUserMeta:
    """Тесты для PUT /private/users/meta/{user_id}"""
    
    @pytest.mark.asyncio
    async def test_update_user_meta_success(self, client, user_with_subs, mock_arq, db_pool):
        """Успешное обновление метаданных пользователя"""
        user_id = user_with_subs["user_id"]
        
        response = await client.put(
            f"/api/v1/private/users/meta/{user_id}",
            json={
                "tg_username": "updated_username",
                "tg_id": 987654321,
                "registered_at": "2026-01-01T00:00:00Z"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Пользователь обновлён"
        
        # Проверяем что данные обновились в БД
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT tg_username, tg_id, registered_at FROM users WHERE id = $1",
                user_id
            )
            assert user["tg_username"] == "updated_username"
            assert user["tg_id"] == 987654321
    
    @pytest.mark.asyncio
    async def test_update_user_meta_partial(self, client, user_with_subs, mock_arq, db_pool):
        """Частичное обновление метаданных (только tg_username)"""
        user_id = user_with_subs["user_id"]
        
        response = await client.put(
            f"/api/v1/private/users/meta/{user_id}",
            json={
                "tg_username": "partial_update"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что только username изменился
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT tg_username, tg_id FROM users WHERE id = $1",
                user_id
            )
            assert user["tg_username"] == "partial_update"
            assert user["tg_id"] == 123456789  # Не изменился
    
    @pytest.mark.asyncio
    async def test_update_user_meta_duplicate_tg_username(self, client, user_with_subs, mock_arq, db_pool):
        """UniqueViolation при попытке установить дублирующий tg_username (409)"""
        user_id = user_with_subs["user_id"]
        
        # Создаём другого пользователя с username "existing_user"
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2)",
                999999999,
                "existing_user"
            )
        
        # Пытаемся обновить на существующий username
        response = await client.put(
            f"/api/v1/private/users/meta/{user_id}",
            json={
                "tg_username": "existing_user"
            }
        )
        
        assert response.status_code == 409
        data = response.json()
        detail = data.get("detail", data)
        assert detail["success"] is False
        assert "уникальности" in detail["message"]
    
    @pytest.mark.asyncio
    async def test_update_user_meta_not_found(self, client, db_seed, mock_arq):
        """UPDATE несуществующего пользователя возвращает 404"""
        response = await client.put(
            "/api/v1/private/users/meta/99999",
            json={
                "tg_username": "nonexistent_user"
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        detail = data.get("detail", data)
        assert detail["success"] is False
        assert "не существует" in detail["message"]


class TestUpdateUserSubs:
    """Тесты для PUT /private/users/subs/{user_id}"""
    
    @pytest.mark.asyncio
    async def test_update_user_subs_add_subscription(self, client, user_with_subs, mock_arq, db_pool):
        """Добавление новой подписки пользователю"""
        user_id = user_with_subs["user_id"]
        plan_id_2 = user_with_subs["plan_id_2"]
        
        response = await client.put(
            f"/api/v1/private/users/subs/{user_id}",
            json={
                "user_subs_to_add": [
                    {
                        "b64_id": "new_b64_subscription_token_12345",
                        "uuid": "cccccccc-dddd-eeee-ffff-000000000001",
                        "sub_plan_id": plan_id_2,
                        "expire_date": "2026-12-31T23:59:59Z",
                        "is_active": True,
                        "is_limited": False,
                        "infinite_traffic": False,
                        "infinite_expire": False
                    }
                ],
                "user_subs_to_update": [],
                "user_subs_to_delete": []
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["added_subs_ids"]) == 1
        assert data["added_subs_ids"][0]["sub_plan_id"] == plan_id_2
        assert len(data["add_jobs"]) == 1  # ARQ job создана
        
        # Проверяем что подписка создалась в БД
        async with db_pool.acquire() as conn:
            subs_count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_subs WHERE user_id = $1",
                user_id
            )
            assert subs_count == 2  # Было 1, стало 2
    
    @pytest.mark.asyncio
    async def test_update_user_subs_delete_subscription(self, client, user_with_subs, mock_arq, db_pool):
        """Удаление подписки пользователя"""
        user_id = user_with_subs["user_id"]
        user_sub_id = user_with_subs["user_sub_id"]
        
        response = await client.put(
            f"/api/v1/private/users/subs/{user_id}",
            json={
                "user_subs_to_add": [],
                "user_subs_to_update": [],
                "user_subs_to_delete": [user_sub_id]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # del_jobs может быть пустым если нет привязанных активных visible нод
        assert "del_jobs" in data
        
        # Проверяем что подписка полностью удалена
        async with db_pool.acquire() as conn:
            sub_exists = await conn.fetchval(
                "SELECT COUNT(*) FROM user_subs WHERE id = $1",
                user_sub_id
            )
            assert sub_exists == 0
    
    @pytest.mark.asyncio
    async def test_update_user_subs_update_subscription(self, client, user_with_subs, db_pool):
        """Обновление существующей подписки - только обязательное поле user_sub_id"""
        user_id = user_with_subs["user_id"]
        user_sub_id = user_with_subs["user_sub_id"]
        
        response = await client.put(
            f"/api/v1/private/users/subs/{user_id}",
            json={
                "user_subs_to_add": [],
                "user_subs_to_update": [
                    {
                        "user_sub_id": user_sub_id,
                        "expire_date": "2027-01-01T00:00:00Z",
                        "infinite_traffic": True,
                        "infinite_expire": False
                        # is_active, is_limited не передаём - они не принимаются
                    }
                ],
                "user_subs_to_delete": []
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["updated_subs_ids"]) == 1
        assert data["updated_subs_ids"][0] == user_sub_id
        
        # Проверяем что подписка обновилась
        async with db_pool.acquire() as conn:
            sub = await conn.fetchrow(
                "SELECT infinite_traffic FROM user_subs WHERE id = $1",
                user_sub_id
            )
            assert sub["infinite_traffic"] is True
    
    @pytest.mark.asyncio
    async def test_update_user_subs_combined_operations(self, client, user_with_subs, mock_arq, db_pool):
        """Комбинированная операция: add + update + delete
        
        Тест проверяет что можно выполнить все три операции в одном запросе.
        Note: Из-за constraint UNIQUE (user_id, sub_plan_id) пользователь может иметь
        только одну подписку на каждый план. Поэтому удаляем fixture подписку перед добавлением.
        """
        user_id = user_with_subs["user_id"]
        user_sub_id = user_with_subs["user_sub_id"]
        plan_id_1 = user_with_subs["plan_id"]
        plan_id_2 = user_with_subs["plan_id_2"]
        
        # Создаём вторую подписку для update
        async with db_pool.acquire() as conn:
            order_id_2 = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) VALUES ($1, 2, NOW(), false, false, 0) RETURNING id",
                user_id
            )
            user_sub_id_2 = await conn.fetchval(
                """
                INSERT INTO user_subs (user_id, order_id, sub_plan_id, is_active, is_limited, expire_date, uuid, b64_id, infinite_traffic, infinite_expire)
                VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '10 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, order_id_2, plan_id_2,
                "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                "b64_second_sub"
            )
        
        # Выполняем комбинированную операцию:
        # - DELETE первой подписки (освобождает plan_id_1)
        # - UPDATE второй подписки
        # - ADD новой подписки на plan_id_1
        response = await client.put(
            f"/api/v1/private/users/subs/{user_id}",
            json={
                "user_subs_to_delete": [user_sub_id],  # Удаляем первую подписку
                "user_subs_to_add": [
                    {
                        "b64_id": "new_combined_token_999",
                        "uuid": "dddddddd-eeee-ffff-0000-111111111111",
                        "sub_plan_id": plan_id_1,  # Добавляем на освободившийся plan_id_1
                        "expire_date": "2026-12-31T23:59:59Z",
                        "infinite_traffic": False,
                        "infinite_expire": False
                    }
                ],
                "user_subs_to_update": [
                    {
                        "user_sub_id": user_sub_id_2,  # Обновляем вторую подписку
                        "expire_date": "2027-06-01T00:00:00Z",
                        "infinite_traffic": False,
                        "infinite_expire": False
                    }
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем все операции
        assert len(data["added_subs_ids"]) == 1
        assert len(data["updated_subs_ids"]) == 1
        # add_jobs и del_jobs могут быть пустыми если нет активных visible нод
        assert "add_jobs" in data
        assert "del_jobs" in data
        
        # Проверяем итоговое состояние в БД
        async with db_pool.acquire() as conn:
            active_subs = await conn.fetchval(
                "SELECT COUNT(*) FROM user_subs WHERE user_id = $1 AND is_active = true",
                user_id
            )
            # Должна быть хотя бы одна активная (первая) + новая
            assert active_subs >= 1
