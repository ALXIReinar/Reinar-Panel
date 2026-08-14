"""
Интеграционные тесты для DELETE /private/users/bulk/delete
Тестируют bulk удаление пользователей с подписками

КРИТИЧНЫЕ ПРОВЕРКИ:
1. Деактивация подписок перед удалением (is_active = false)
2. Запись в sub_nodes_outbox с operation=delete
3. Фильтрация: только is_limited=false и is_active=true (до UPDATE)
4. Фильтрация: только user_visible=true и is_active=true ноды
5. Правильное маппирование action → ARQ task (delete)
"""
import pytest
import json


@pytest.fixture
async def users_with_subs_for_delete(db_pool, virtual_node_seed, sub_plan_seed):
    """
    Создаём тестовых пользователей с подписками для bulk delete:
    - 2 пользователя с активными подписками (is_limited=false)
    - 1 пользователь с активной подпиской (is_limited=true) - не должен попасть в outbox
    - 1 пользователь с неактивной подпиской - не должен попасть в outbox
    """
    async with db_pool.acquire() as conn:
        # Создаём 4 тестовых пользователей
        user_ids = []
        for i in range(4):
            user_id = await conn.fetchval(
                """
                INSERT INTO users (tg_id, tg_username)
                VALUES ($1, $2)
                RETURNING id
                """,
                4000000 + i,
                f"delete_user_{i}"
            )
            user_ids.append(user_id)
        
        # Привязываем vnode к плану
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        plan_id_1 = sub_plan_seed["plan_id_1"]
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            vnode_id_1, plan_id_1
        )
        
        # Создаём подписки
        user_sub_ids = []
        
        # Пользователи 0,1 - активные подписки, is_limited=false (должны попасть в outbox)
        for i in range(2):
            # Создаём pay_order
            pay_order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) VALUES ($1, 2, NOW(), false, false, 0) RETURNING id",
                user_ids[i]
            )
            
            # Создаём подписку
            user_sub_id = await conn.fetchval(
                """
                INSERT INTO user_subs (
                    user_id, order_id, sub_plan_id, is_active, is_limited, 
                    expire_date, uuid, b64_id, infinite_traffic, infinite_expire
                )
                VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
                RETURNING id
                """,
                user_ids[i], pay_order_id, plan_id_1,
                f"uuid-del-{i:04d}-1111-2222-33333333",
                f"b64_delete_user_{i}"
            )
            user_sub_ids.append(user_sub_id)
        
        # Пользователь 2 - активная подписка, is_limited=true (НЕ должен попасть в outbox)
        pay_order_limited = await conn.fetchval(
            "INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) VALUES ($1, 2, NOW(), false, false, 0) RETURNING id",
            user_ids[2]
        )
        user_sub_id_limited = await conn.fetchval(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, true, true, NOW() + INTERVAL '30 days', $4, $5, false, false)
            RETURNING id
            """,
            user_ids[2], pay_order_limited, plan_id_1,
            f"uuid-del-{2:04d}-1111-2222-33333333",
            f"b64_delete_user_2"
        )
        user_sub_ids.append(user_sub_id_limited)
        
        # Пользователь 3 - неактивная подписка (НЕ должен попасть в outbox)
        pay_order_inactive = await conn.fetchval(
            "INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) VALUES ($1, 3, NOW(), false, false, 0) RETURNING id",
            user_ids[3]
        )
        user_sub_id_inactive = await conn.fetchval(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, false, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
            RETURNING id
            """,
            user_ids[3], pay_order_inactive, plan_id_1,
            f"uuid-del-{3:04d}-1111-2222-33333333",
            f"b64_delete_user_3"
        )
        user_sub_ids.append(user_sub_id_inactive)
        
        return {
            "user_ids": user_ids,
            "active_unlim_user_ids": user_ids[:2],  # is_limited=false, is_active=true
            "limited_user_id": user_ids[2],  # is_limited=true
            "inactive_user_id": user_ids[3],  # is_active=false
            "user_sub_ids": user_sub_ids,
            "sub_plan_id": plan_id_1,
            "vnode_id": vnode_id_1,
        }


class TestBulkDeleteSuccess:
    """Тесты успешного удаления пользователей"""
    
    @pytest.mark.asyncio
    async def test_bulk_delete_removes_users(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Успешное удаление пользователей из БД"""
        user_ids = users_with_subs_for_delete["active_unlim_user_ids"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": user_ids}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_count"] == 2
        
        # Проверяем что пользователи помечены как удалённые (soft delete)
        async with db_pool.acquire() as conn:
            users = await conn.fetch(
                "SELECT id, is_deleted FROM users WHERE id = ANY($1)",
                user_ids
            )
            assert len(users) == 2  # Пользователи остались в БД
            for user in users:
                assert user["is_deleted"] is True  # Помечены как удалённые
    
    @pytest.mark.asyncio
    async def test_bulk_delete_deactivates_subscriptions(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Удаление деактивирует подписки перед удалением пользователей"""
        user_ids = users_with_subs_for_delete["active_unlim_user_ids"]
        
        # Проверяем что подписки активны ДО удаления
        async with db_pool.acquire() as conn:
            active_before = await conn.fetch(
                "SELECT id, is_active FROM user_subs WHERE user_id = ANY($1)",
                user_ids
            )
            assert len(active_before) == 2
            for sub in active_before:
                assert sub["is_active"] is True
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": user_ids}
        )
        
        assert response.status_code == 200
        
        # Проверяем что подписки деактивированы (is_active=false)
        # Подписки НЕ удаляются каскадно, а остаются в БД с is_active=false
        async with db_pool.acquire() as conn:
            subs_after = await conn.fetch(
                "SELECT id, is_active FROM user_subs WHERE user_id = ANY($1)",
                user_ids
            )
            assert len(subs_after) == 2
            for sub in subs_after:
                assert sub["is_active"] is False  # Деактивированы
    
    @pytest.mark.asyncio
    async def test_bulk_delete_returns_correct_count(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Проверка правильного deleted_count в ответе"""
        user_ids = users_with_subs_for_delete["user_ids"][:3]  # Удаляем 3 пользователей
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": user_ids}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2  # Только 2 попали в outbox (is_limited=false, is_active=true)
        assert "message" in data


class TestBulkDeleteOutboxAndArq:
    """Тесты записи в outbox и вызова ARQ"""
    
    @pytest.mark.asyncio
    async def test_bulk_delete_creates_outbox_for_active_subs(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Удаление создаёт записи в sub_nodes_outbox с operation=delete"""
        user_ids = users_with_subs_for_delete["active_unlim_user_ids"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": user_ids}
        )
        
        assert response.status_code == 200
        
        # Проверяем запись в outbox
        async with db_pool.acquire() as conn:
            outbox = await conn.fetch(
                """
                SELECT o.user_sub_id, o.operation
                FROM sub_nodes_outbox o
                WHERE o.user_sub_id = ANY($1)
                ORDER BY o.user_sub_id
                """,
                users_with_subs_for_delete["user_sub_ids"][:2]
            )
            assert len(outbox) == 2
            for record in outbox:
                assert record["operation"] == 2  # CoreProtoActions.delete
    
    @pytest.mark.asyncio
    async def test_bulk_delete_only_is_limited_false_in_outbox(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Только пользователи с is_limited=false попадают в outbox"""
        # Удаляем всех пользователей
        all_user_ids = users_with_subs_for_delete["user_ids"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": all_user_ids}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # В outbox должны попасть только 2 пользователя (is_limited=false, is_active=true)
        assert data["deleted_count"] == 2
        
        # Проверяем outbox
        async with db_pool.acquire() as conn:
            # Проверяем что is_limited=false в outbox
            outbox_unlim = await conn.fetch(
                """
                SELECT COUNT(*) as cnt FROM sub_nodes_outbox
                WHERE user_sub_id = ANY($1)
                """,
                users_with_subs_for_delete["user_sub_ids"][:2]
            )
            assert outbox_unlim[0]["cnt"] == 2
            
            # Проверяем что is_limited=true НЕ в outbox
            outbox_lim = await conn.fetch(
                """
                SELECT COUNT(*) as cnt FROM sub_nodes_outbox
                WHERE user_sub_id = $1
                """,
                users_with_subs_for_delete["user_sub_ids"][2]
            )
            assert outbox_lim[0]["cnt"] == 0
            
            # Проверяем что is_active=false НЕ в outbox
            outbox_inactive = await conn.fetch(
                """
                SELECT COUNT(*) as cnt FROM sub_nodes_outbox
                WHERE user_sub_id = $1
                """,
                users_with_subs_for_delete["user_sub_ids"][3]
            )
            assert outbox_inactive[0]["cnt"] == 0
    
    @pytest.mark.asyncio
    async def test_bulk_delete_calls_arq_with_delete_action(self, client, users_with_subs_for_delete, mock_arq):
        """Удаление вызывает ARQ с action='delete' и передаёт event_ids"""
        user_ids = users_with_subs_for_delete["active_unlim_user_ids"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": user_ids}
        )
        
        assert response.status_code == 200
        
        # Проверяем вызов ARQ
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Должен вызываться admin_request_bulk_action_users с action='delete'
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "delete"
        
        # Второй аргумент - массив event_ids (list[int])
        event_ids = call_args[0][2]
        assert isinstance(event_ids, list)
        assert len(event_ids) == 2
        assert all(isinstance(eid, int) for eid in event_ids)
    
    @pytest.mark.asyncio
    async def test_bulk_delete_empty_list_no_arq_call(self, client, mock_arq):
        """Пустой список user_ids не вызывает ARQ"""
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": []}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 0
        
        # ARQ не должен вызываться
        mock_arq.enqueue_job.assert_not_called()


class TestBulkDeleteEdgeCases:
    """Тесты edge cases: несуществующие users, фильтры"""
    
    @pytest.mark.asyncio
    async def test_bulk_delete_nonexistent_users(self, client, mock_arq):
        """Несуществующие user_ids не вызывают ошибку"""
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": [99999, 88888]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 0
        
        # ARQ не вызывается
        mock_arq.enqueue_job.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_bulk_delete_inactive_subscription_not_in_outbox(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Пользователь с неактивной подпиской НЕ попадает в outbox"""
        inactive_user_id = users_with_subs_for_delete["inactive_user_id"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": [inactive_user_id]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 0  # Не попал в outbox
        
        # Проверяем что пользователь помечен как удалённый (soft delete)
        async with db_pool.acquire() as conn:
            is_deleted = await conn.fetchval(
                "SELECT is_deleted FROM users WHERE id = $1",
                inactive_user_id
            )
            assert is_deleted is True
            
            # Проверяем что в outbox ничего нет
            outbox_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE user_sub_id = $1
                """,
                users_with_subs_for_delete["user_sub_ids"][3]
            )
            assert outbox_count == 0
    
    @pytest.mark.asyncio
    async def test_bulk_delete_is_limited_user_not_in_outbox(self, client, users_with_subs_for_delete, mock_arq, db_pool):
        """Пользователь с is_limited=true НЕ попадает в outbox"""
        limited_user_id = users_with_subs_for_delete["limited_user_id"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": [limited_user_id]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 0  # Не попал в outbox
        
        # Проверяем что пользователь помечен как удалённый (soft delete)
        async with db_pool.acquire() as conn:
            is_deleted = await conn.fetchval(
                "SELECT is_deleted FROM users WHERE id = $1",
                limited_user_id
            )
            assert is_deleted is True
            
            # Проверяем что в outbox ничего нет
            outbox_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE user_sub_id = $1
                """,
                users_with_subs_for_delete["user_sub_ids"][2]
            )
            assert outbox_count == 0
    
    @pytest.mark.asyncio
    async def test_bulk_delete_invisible_vnode_no_outbox(self, client, virtual_node_seed, sub_plan_seed, mock_arq, db_pool):
        """vnode с user_visible=false не создаёт запись в outbox"""
        async with db_pool.acquire() as conn:
            # Создаём невидимую vnode
            node_id = virtual_node_seed["node_id_1"]
            protocol_id = virtual_node_seed["proto_id"]
            
            invisible_vnode_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, user_visible)
                VALUES ($1, $2, $3, false)
                RETURNING id
                """,
                node_id, protocol_id, "Invisible VNode Delete"
            )
            
            # Создаём пользователя
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                4001000, "invisible_delete_user"
            )
            
            # Привязываем невидимую vnode к плану
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
                invisible_vnode_id, plan_id
            )
            
            # Создаём pay_order
            pay_order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) VALUES ($1, 2, NOW(), false, false, 0) RETURNING id",
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
                user_id, pay_order_id, plan_id,
                "uuid-invis-del-0001-0002-00000003",
                "b64_invisible_delete_user"
            )
        
        # Удаляем пользователя
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": [user_id]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 0  # Не попал в outbox (invisible vnode)
        
        # Проверяем что пользователь помечен как удалённый (soft delete)
        async with db_pool.acquire() as conn:
            is_deleted = await conn.fetchval(
                "SELECT is_deleted FROM users WHERE id = $1",
                user_id
            )
            assert is_deleted is True
            
            # Проверяем что в outbox ничего нет
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 0
    
    @pytest.mark.asyncio
    async def test_bulk_delete_inactive_node_no_outbox(self, client, virtual_node_seed, sub_plan_seed, mock_arq, db_pool):
        """Физ нода с is_active=false не создаёт запись в outbox"""
        async with db_pool.acquire() as conn:
            # Создаём неактивную ноду
            inactive_node_id = await conn.fetchval(
                """
                INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
                VALUES ($1, $2, $3, $4, $5, false)
                RETURNING id
                """,
                "192.168.3.100", "10.20.30.100", 8300, "inactive-node-delete", "Inactive Node Delete"
            )
            
            protocol_id = virtual_node_seed["proto_id"]
            
            # Создаём vnode на неактивной ноде
            vnode_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, user_visible)
                VALUES ($1, $2, $3, true)
                RETURNING id
                """,
                inactive_node_id, protocol_id, "VNode on Inactive Node Delete"
            )
            
            # Создаём пользователя
            user_id = await conn.fetchval(
                "INSERT INTO users (tg_id, tg_username) VALUES ($1, $2) RETURNING id",
                4002000, "inactive_node_delete_user"
            )
            
            # Привязываем vnode к плану
            plan_id = sub_plan_seed["plan_id_1"]
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
                vnode_id, plan_id
            )
            
            # Создаём pay_order
            pay_order_id = await conn.fetchval(
                "INSERT INTO pay_orders (user_id, status, timestamp, infinite_expire, infinite_traffic, cost) VALUES ($1, 2, NOW(), false, false, 0) RETURNING id",
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
                user_id, pay_order_id, plan_id,
                "uuid-inact-del-0001-0002-00000003",
                "b64_inactive_node_delete_user"
            )
        
        # Удаляем пользователя
        response = await client.request(
            "DELETE",
            "/api/v1/private/users/bulk/delete",
            json={"user_ids": [user_id]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 0  # Не попал в outbox (inactive node)
        
        # Проверяем что пользователь помечен как удалённый (soft delete)
        async with db_pool.acquire() as conn:
            is_deleted = await conn.fetchval(
                "SELECT is_deleted FROM users WHERE id = $1",
                user_id
            )
            assert is_deleted is True
            
            # Проверяем что в outbox ничего нет
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 0

