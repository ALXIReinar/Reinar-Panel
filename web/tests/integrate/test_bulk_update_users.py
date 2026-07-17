"""
Интеграционные тесты для PUT /private/users/bulk/update
Тестируют bulk операции над пользователями: activate, deactivate, reset_traffic

КРИТИЧНЫЕ ПРОВЕРКИ:
1. Запись в sub_nodes_outbox перед отправкой в ARQ
2. Порядок возвращаемых полей: order_id, sub_plan_id, user_id
3. Фильтрация: только user_visible=true и is_active=true ноды
4. Правильное маппирование action → ARQ task
"""
import pytest


@pytest.fixture
async def users_with_subs(db_pool, virtual_node_seed, sub_plan_seed):
    """
    Создаём тестовых пользователей с подписками для bulk update:
    - 2 пользователя с активными подписками (для deactivate теста)
    - 2 пользователя с неактивными подписками (для activate теста)
    - 1 пользователь с трафиком (для reset_traffic теста)
    """
    async with db_pool.acquire() as conn:
        # Создаём 5 тестовых пользователей
        user_ids = []
        for i in range(5):
            user_id = await conn.fetchval(
                """
                INSERT INTO users (tg_id, tg_username)
                VALUES ($1, $2)
                RETURNING id
                """,
                1000000 + i,  # tg_id
                f"bulk_user_{i}"  # tg_username
            )
            user_ids.append(user_id)
        
        # Привязываем vnode к плану подписки
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        plan_id_1 = sub_plan_seed["plan_id_1"]
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            vnode_id_1, plan_id_1
        )
        
        # Создаём подписки
        # Пользователи 0,1 - активные подписки (для deactivate)
        active_order_ids = []
        for i in range(2):
            # Создаём pay_order
            order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
                user_ids[i]
            )
            
            # Создаём подписку
            await conn.execute(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited, 
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                """,
                user_ids[i], order_id, plan_id_1,
                f"uuid-{i:04d}-1111-2222-333333333333",
                f"b64_bulk_user_{i}"
            )
            active_order_ids.append(order_id)
        
        # Пользователи 2,3 - неактивные подписки (для activate)
        inactive_order_ids = []
        for i in range(2, 4):
            order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 3, NOW()) RETURNING id",
                user_ids[i]
            )
            
            await conn.execute(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, false, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                """,
                user_ids[i], order_id, plan_id_1,
                f"uuid-{i:04d}-1111-2222-333333333333",
                f"b64_bulk_user_{i}"
            )
            inactive_order_ids.append(order_id)
        
        # Пользователь 4 - активная подписка с трафиком и is_limited=true (для reset_traffic)
        order_id_traffic = await conn.fetchval(
            "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
            user_ids[4]
        )
        
        traffic_order_id = await conn.execute(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, true, true, NOW() + INTERVAL '30 days', $4, $5, false, false, 500)
            """,
            user_ids[4], order_id_traffic, plan_id_1,
            f"uuid-{4:04d}-1111-2222-333333333333",
            f"b64_bulk_user_4"
        )
        
        return {
            "user_ids": user_ids,
            "active_user_ids": user_ids[:2],  # Для deactivate
            "inactive_user_ids": user_ids[2:4],  # Для activate
            "traffic_user_id": user_ids[4],  # Для reset_traffic
            "active_order_ids": active_order_ids,
            "inactive_order_ids": inactive_order_ids,
            "traffic_order_id": order_id_traffic,
            "sub_plan_id": plan_id_1,
            "vnode_id": vnode_id_1,
        }


class TestBulkUpdateActivate:
    """Тесты активации подписок (action='activate')"""
    
    @pytest.mark.asyncio
    async def test_activate_success(self, client, users_with_subs, mock_arq, db_pool):
        """Успешная активация неактивных подписок"""
        user_ids = users_with_subs["inactive_user_ids"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": user_ids,
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["affected_count"] == 2
        assert "arq_job_id" in data
        assert data["arq_job_id"] == "test-job-12345"
        
        # Проверяем что подписки активированы в БД
        async with db_pool.acquire() as conn:
            activated = await conn.fetch(
                "SELECT id, is_active FROM user_subs WHERE user_id = ANY($1) ORDER BY id",
                user_ids
            )
            assert len(activated) == 2
            for sub in activated:
                assert sub["is_active"] is True
    
    @pytest.mark.asyncio
    async def test_activate_creates_outbox_records(self, client, users_with_subs, mock_arq, db_pool):
        """Активация создаёт записи в sub_nodes_outbox с operation=add"""
        user_ids = users_with_subs["inactive_user_ids"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": user_ids,
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем запись в outbox
        async with db_pool.acquire() as conn:
            outbox = await conn.fetch(
                """
                SELECT user_sub_id, operation FROM sub_nodes_outbox
                WHERE user_sub_id = ANY(
                    SELECT id FROM user_subs WHERE user_id = ANY($1)
                )
                ORDER BY user_sub_id
                """,
                user_ids
            )
            assert len(outbox) == 2
            for record in outbox:
                assert record["operation"] == 1  # CoreProtoActions.add
    
    @pytest.mark.asyncio
    async def test_activate_calls_arq_with_correct_action(self, client, users_with_subs, mock_arq):
        """Активация вызывает ARQ с action='add'"""
        user_ids = users_with_subs["inactive_user_ids"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": user_ids,
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем вызов ARQ
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Должен вызываться admin_request_bulk_action_users с action='add'
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "add"  # action переведён в 'add'
        
        # Второй аргумент - массив пользователей
        users_for_arq = call_args[0][2]
        assert len(users_for_arq) == 2
        
        # Проверяем структуру: каждый элемент имеет user_sub_id, sub_plan_id, uuid
        for user in users_for_arq:
            assert "user_sub_id" in user
            assert "sub_plan_id" in user
            assert "uuid" in user
            assert user["sub_plan_id"] == users_with_subs["sub_plan_id"]


class TestBulkUpdateDeactivate:
    """Тесты деактивации подписок (action='deactivate')"""
    
    @pytest.mark.asyncio
    async def test_deactivate_success(self, client, users_with_subs, mock_arq, db_pool):
        """Успешная деактивация активных подписок"""
        user_ids = users_with_subs["active_user_ids"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": user_ids,
                "action": "deactivate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["affected_count"] == 2
        
        # Проверяем что подписки деактивированы в БД
        async with db_pool.acquire() as conn:
            deactivated = await conn.fetch(
                "SELECT id, is_active FROM user_subs WHERE user_id = ANY($1) ORDER BY id",
                user_ids
            )
            assert len(deactivated) == 2
            for sub in deactivated:
                assert sub["is_active"] is False
    
    @pytest.mark.asyncio
    async def test_deactivate_creates_outbox_with_delete_operation(self, client, users_with_subs, mock_arq, db_pool):
        """Деактивация создаёт записи в outbox с operation=delete"""
        user_ids = users_with_subs["active_user_ids"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": user_ids,
                "action": "deactivate"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем запись в outbox
        async with db_pool.acquire() as conn:
            outbox = await conn.fetch(
                """
                SELECT user_sub_id, operation FROM sub_nodes_outbox
                WHERE user_sub_id = ANY(
                    SELECT id FROM user_subs WHERE user_id = ANY($1)
                )
                ORDER BY user_sub_id
                """,
                user_ids
            )
            assert len(outbox) == 2
            for record in outbox:
                assert record["operation"] == 2  # CoreProtoActions.delete
    
    @pytest.mark.asyncio
    async def test_deactivate_calls_arq_with_delete_action(self, client, users_with_subs, mock_arq):
        """Деактивация вызывает ARQ с action='delete'"""
        user_ids = users_with_subs["active_user_ids"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": user_ids,
                "action": "deactivate"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем вызов ARQ
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Должен вызываться admin_request_bulk_action_users с action='delete'
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "delete"


class TestBulkUpdateResetTraffic:
    """Тесты сброса трафика (action='reset_traffic')"""
    
    @pytest.mark.asyncio
    async def test_reset_traffic_success(self, client, users_with_subs, mock_arq, db_pool):
        """Успешный сброс дневного трафика пользователя"""
        user_id = users_with_subs["traffic_user_id"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "reset_traffic"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["affected_count"] == 1
        
        # Проверяем что трафик обнулён в user_subs
        async with db_pool.acquire() as conn:
            traffic = await conn.fetchval(
                "SELECT traffic_used_day_mb FROM user_subs WHERE user_id = $1",
                user_id
            )
            assert traffic == 0
    
    @pytest.mark.asyncio
    async def test_reset_traffic_calls_correct_arq_task(self, client, users_with_subs, mock_arq):
        """Сброс трафика вызывает специальную ARQ задачу reset_day_user_traffic"""
        user_id = users_with_subs["traffic_user_id"]
        
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "reset_traffic"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем вызов ARQ
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Для reset_traffic должна вызываться другая задача
        assert call_args[0][0] == "reset_day_user_traffic"
        
        # Первый аргумент - массив пользователей
        users_for_arq = call_args[0][1]
        assert len(users_for_arq) == 1


class TestBulkUpdateValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_invalid_action(self, client, users_with_subs, mock_arq):
        """Неверный action возвращает 422"""
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [1, 2],
                "action": "invalid_action"
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
    
    @pytest.mark.asyncio
    async def test_empty_user_ids(self, client, mock_arq):
        """Пустой массив user_ids - должен вернуть 200 с affected_count=0"""
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [],
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["affected_count"] == 0
    
    @pytest.mark.asyncio
    async def test_nonexistent_user_ids(self, client, mock_arq):
        """Несуществующие user_ids - должен вернуть 200 с affected_count=0"""
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [99999, 88888],
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["affected_count"] == 0




class TestBulkUpdateEdgeCases:
    """Тесты edge cases: is_limited, множественные подписки, фильтры нод"""
    
    @pytest.mark.asyncio
    async def test_activate_skips_limited_subscriptions(self, client, db_pool, virtual_node_seed, sub_plan_seed, mock_arq):
        """Пользователь с is_limited=true НЕ попадает в outbox при activate"""
        async with db_pool.acquire() as conn:
            # Создаём пользователя с неактивной подпиской is_limited=true
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000001, "limited_user"
            )
            
            # Привязываем vnode к плану
            vnode_id = virtual_node_seed["vnode_id_1"]
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                vnode_id, plan_id
            )
            
            # Создаём pay_order
            order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 3, NOW()) RETURNING id",
                user_id
            )
            
            # Создаём неактивную подписку с is_limited=true
            user_sub_id = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited, 
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, false, true, NOW() + INTERVAL '30 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, order_id, plan_id,
                "uuid-0001-1111-2222-333333333333",
                "b64_limited_user"
            )
        
        # Пытаемся активировать
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["affected_count"] == 0  # Не затронул is_limited=true
        
        # Проверяем что в outbox ничего не попало
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 0
            
            # Проверяем что подписка осталась неактивной
            is_active = await conn.fetchval(
                "SELECT is_active FROM user_subs WHERE id = $1",
                user_sub_id
            )
            assert is_active is False
    
    @pytest.mark.asyncio
    async def test_deactivate_skips_limited_subscriptions(self, client, db_pool, virtual_node_seed, sub_plan_seed, mock_arq):
        """Пользователь с is_limited=true НЕ попадает в outbox при deactivate"""
        async with db_pool.acquire() as conn:
            # Создаём пользователя с активной подпиской is_limited=true
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000002, "limited_active_user"
            )
            
            vnode_id = virtual_node_seed["vnode_id_1"]
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                vnode_id, plan_id
            )
            
            # Создаём pay_order
            order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
                user_id
            )
            
            # Создаём активную подписку с is_limited=true
            user_sub_id = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, true, true, NOW() + INTERVAL '30 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, order_id, plan_id,
                "uuid-0002-1111-2222-333333333333",
                "b64_limited_active_user"
            )
        
        # Пытаемся деактивировать
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "deactivate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["affected_count"] == 0  # Не попал в outbox (is_limited=true фильтруется)
        
        # Проверяем что в outbox ничего не попало (is_limited=true не попадают в outbox)
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 0
            
            # Проверяем что подписка ДЕАКТИВИРОВАНА (UPDATE всё равно выполнился)
            is_active = await conn.fetchval(
                "SELECT is_active FROM user_subs WHERE id = $1",
                user_sub_id
            )
            assert is_active is False  # Деактивировалась
    
    @pytest.mark.asyncio
    async def test_reset_traffic_resets_all_but_outbox_only_limited(self, client, db_pool, virtual_node_seed, sub_plan_seed, mock_arq):
        """reset_traffic обнуляет трафик всем, но в outbox попадают только is_limited=true"""
        async with db_pool.acquire() as conn:
            # Создаём 2 пользователей: один limited, другой нет
            user_id_limited = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000003, "limited_traffic_user"
            )
            user_id_normal = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000004, "normal_traffic_user"
            )
            
            vnode_id = virtual_node_seed["vnode_id_1"]
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                vnode_id, plan_id
            )
            
            # Создаём подписки: одна limited, другая нет
            # Limited подписка
            order_id_lim = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
                user_id_limited
            )
            order_id_limited = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire, traffic_used_day_mb
                )
                VALUES ($1, $2, $3, true, true, NOW() + INTERVAL '30 days', $4, $5, false, false, 500)
                RETURNING id
                """,
                user_id_limited, order_id_lim, plan_id,
                "uuid-0003-1111-2222-333333333333",
                "b64_limited_traffic_user"
            )
            
            # Normal подписка
            order_id_norm = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
                user_id_normal
            )
            order_id_normal = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire, traffic_used_day_mb
                )
                VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false, 300)
                RETURNING id
                """,
                user_id_normal, order_id_norm, plan_id,
                "uuid-0004-1111-2222-333333333333",
                "b64_normal_traffic_user"
            )
        
        # Сбрасываем трафик обоим
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id_limited, user_id_normal],
                "action": "reset_traffic"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["affected_count"] == 1  # Только limited попал в outbox
        
        # Проверяем что трафик обнулён у ОБОИХ в user_subs
        async with db_pool.acquire() as conn:
            traffic_limited = await conn.fetchval(
                "SELECT traffic_used_day_mb FROM user_subs WHERE user_id = $1",
                user_id_limited
            )
            traffic_normal = await conn.fetchval(
                "SELECT traffic_used_day_mb FROM user_subs WHERE user_id = $1",
                user_id_normal
            )
            assert traffic_limited == 0
            assert traffic_normal == 0
            
            # Проверяем что в outbox только limited пользователь
            outbox_limited = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                order_id_limited
            )
            outbox_normal = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                order_id_normal
            )
            assert outbox_limited == 1  # limited пользователь в outbox
            assert outbox_normal == 0  # normal пользователь НЕ в outbox
    
    @pytest.mark.asyncio
    async def test_user_with_multiple_subscriptions_activate_only_inactive(self, client, db_pool, virtual_node_seed, sub_plan_seed, mock_arq):
        """У пользователя 2 подписки на РАЗНЫЕ планы: активируется только неактивная"""
        async with db_pool.acquire() as conn:
            # Создаём пользователя
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000005, "multi_sub_user"
            )
            
            vnode_id = virtual_node_seed["vnode_id_1"]
            plan_id_1 = sub_plan_seed["plan_id_1"]
            plan_id_2 = sub_plan_seed["plan_id_2"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2), ($1, $3) ON CONFLICT DO NOTHING",
                vnode_id, plan_id_1, plan_id_2
            )
            
            # Создаём 2 подписки на РАЗНЫЕ планы: одна активная, другая нет
            # Активная подписка
            order_active = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
                user_id
            )
            order_id_active = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, order_active, plan_id_1,
                "uuid-0005-1111-2222-333333333333",
                "b64_multi_sub_user_active"
            )
            
            # Неактивная подписка
            order_inactive = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 3, NOW()) RETURNING id",
                user_id
            )
            order_id_inactive = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, false, false, NOW() + INTERVAL '20 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, order_inactive, plan_id_2,
                "uuid-0006-1111-2222-333333333333",
                "b64_multi_sub_user_inactive"
            )
        
        # Активируем пользователя
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["affected_count"] == 1  # Затронута только неактивная подписка
        
        # Проверяем что активировалась только неактивная подписка
        async with db_pool.acquire() as conn:
            active_sub_status = await conn.fetchval(
                "SELECT is_active FROM user_subs WHERE id = $1",
                order_id_active
            )
            inactive_sub_status = await conn.fetchval(
                "SELECT is_active FROM user_subs WHERE id = $1",
                order_id_inactive
            )
            
            assert active_sub_status is True  # Осталась активной
            assert inactive_sub_status is True  # Стала активной
            
            # Проверяем что в outbox только вторая подписка
            outbox_active = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                order_id_active
            )
            outbox_inactive = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                order_id_inactive
            )
            assert outbox_active == 0
            assert outbox_inactive == 1
    
    @pytest.mark.asyncio
    async def test_invisible_vnode_not_in_outbox(self, client, db_pool, virtual_node_seed, sub_plan_seed, mock_arq):
        """vnode с user_visible=false не создаёт запись в outbox"""
        async with db_pool.acquire() as conn:
            # Создаём невидимую виртуальную ноду
            node_id = virtual_node_seed["node_id_1"]
            protocol_id = virtual_node_seed["proto_id"]
            
            invisible_vnode_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, user_visible)
                VALUES ($1, $2, $3, false)
                RETURNING id
                """,
                node_id, protocol_id, "Invisible VNode"
            )
            
            # Создаём пользователя
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000006, "invisible_vnode_user"
            )
            
            # Привязываем невидимую vnode к плану
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
                invisible_vnode_id, plan_id
            )
            
            # Создаём pay_order
            pay_order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 3, NOW()) RETURNING id",
                user_id
            )
            
            # Создаём подписку
            user_sub_id = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, false, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, pay_order_id, plan_id,
                "uuid-0006-1111-2222-333333333333",
                "b64_invisible_vnode_user"
            )
        
        # Активируем
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        # Подписка активируется, но в outbox не попадает
        
        # Проверяем что подписка активирована
        async with db_pool.acquire() as conn:
            is_active = await conn.fetchval(
                "SELECT is_active FROM user_subs WHERE id = $1",
                user_sub_id
            )
            assert is_active is True
            
            # Проверяем что в outbox ничего нет
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 0
    
    @pytest.mark.asyncio
    async def test_inactive_physical_node_not_in_outbox(self, client, db_pool, virtual_node_seed, sub_plan_seed, mock_arq):
        """Физ нода с is_active=false не создаёт запись в outbox"""
        async with db_pool.acquire() as conn:
            # Создаём неактивную физическую ноду
            inactive_node_id = await conn.fetchval(
                """
                INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
                VALUES ($1, $2, $3, $4, $5, false)
                RETURNING id
                """,
                "192.168.1.200", "10.0.0.200", 8200, "inactive-node", "Inactive Node"
            )
            
            protocol_id = virtual_node_seed["proto_id"]
            
            # Создаём vnode на неактивной ноде
            vnode_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, user_visible)
                VALUES ($1, $2, $3, true)
                RETURNING id
                """,
                inactive_node_id, protocol_id, "VNode on Inactive Node"
            )
            
            # Создаём пользователя
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                2000007, "inactive_node_user"
            )
            
            # Привязываем vnode к плану
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
                vnode_id, plan_id
            )
            
            # Создаём pay_order
            pay_order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 3, NOW()) RETURNING id",
                user_id
            )
            
            # Создаём подписку
            user_sub_id = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited,
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, false, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                RETURNING id
                """,
                user_id, pay_order_id, plan_id,
                "uuid-0008-1111-2222-333333333333",
                "b64_inactive_node_user"
            )
        
        # Активируем
        response = await client.put(
            "/api/v1/private/users/bulk/update",
            json={
                "user_ids": [user_id],
                "action": "activate"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        # Подписка активируется, но в outbox не попадает
        
        # Проверяем что подписка активирована
        async with db_pool.acquire() as conn:
            is_active = await conn.fetchval(
                "SELECT is_active FROM user_subs WHERE id = $1",
                user_sub_id
            )
            assert is_active is True
            
            # Проверяем что в outbox ничего нет
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 0







