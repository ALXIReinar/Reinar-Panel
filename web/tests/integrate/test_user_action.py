"""
Интеграционные тесты для POST /core_protocol/user/action
Тестируют добавление/удаление пользователей на ядрах протоколов через фоновую очередь
"""
import pytest


@pytest.fixture
async def subscription_data(pg_pool, virtual_node_seed, sub_plan_seed):
    """
    Создаём разнообразные данные для тестирования фильтрации:
    - Активная/неактивная физическая нода
    - Видимая/невидимая виртуальная нода
    - Активная/неактивная подписка
    """
    async with pg_pool.acquire() as conn:
        # Создаём тестового пользователя в таблице users
        user_id = await conn.fetchval(
            """
            INSERT INTO users (tg_id, tg_username, uuid)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            123456789,  # Тестовый telegram ID
            "test_user_sub",  # Telegram username
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"  # UUID пользователя
        )
        
        # Создаём дополнительную НЕАКТИВНУЮ физическую ноду
        inactive_node_id = await conn.fetchval(
            """
            INSERT INTO nodes (node_name, ip, private_ip, api_port, is_active)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            "Inactive Node", "203.0.113.3", "10.0.0.103", 8103, False  # is_active = False, уникальный IP
        )
        
        # Создаём виртуальную ноду на НЕАКТИВНОЙ физической ноде (должна быть отфильтрована)
        vnode_on_inactive = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title, user_visible)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            inactive_node_id, virtual_node_seed["proto_id"], "VNode on Inactive", True
        )
        
        # Создаём НЕВИДИМУЮ виртуальную ноду на активной физической ноде (должна быть отфильтрована)
        invisible_vnode = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title, user_visible)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            virtual_node_seed["node_id_1"], virtual_node_seed["proto_id"], "Invisible VNode", False  # user_visible = False
        )
        
        # Связываем виртуальные ноды с планами подписки
        vnode_id_1 = virtual_node_seed["vnode_id_1"]  # Активная нода + видимая (✅ должна попасть)
        plan_id_1 = sub_plan_seed["plan_id_1"]
        
        # Добавляем в vnodes_sub_plans
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            vnode_id_1, plan_id_1
        )
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            vnode_on_inactive, plan_id_1  # ❌ не должна попасть (нода неактивна)
        )
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            invisible_vnode, plan_id_1  # ❌ не должна попасть (невидима)
        )
        
        # Создаём АКТИВНУЮ подписку для пользователя
        active_order_id = await conn.fetchval(
            """
            INSERT INTO payed_subs (sub_plan_id, user_id, is_active, expire_date, status)
            VALUES ($1, $2, $3, NOW() + INTERVAL '30 days', $4)
            RETURNING id
            """,
            plan_id_1, user_id, True, 1  # is_active = True
        )
        
        # Создаём НЕАКТИВНУЮ подписку для тестов фильтрации
        inactive_order_id = await conn.fetchval(
            """
            INSERT INTO payed_subs (sub_plan_id, user_id, is_active, expire_date, status)
            VALUES ($1, $2, $3, NOW() - INTERVAL '1 day', $4)
            RETURNING id
            """,
            plan_id_1, user_id, False, 3  # is_active = False, status = expired
        )
        
        return {
            "user_id": user_id,
            "active_order_id": active_order_id,
            "inactive_order_id": inactive_order_id,
            "vnode_id_1": vnode_id_1,  # ✅ Видимая на активной ноде
            "vnode_on_inactive": vnode_on_inactive,  # ❌ На неактивной ноде
            "invisible_vnode": invisible_vnode,  # ❌ Невидимая
        }


class TestUserActionSuccess:
    """Тесты успешного добавления/удаления пользователя"""
    
    @pytest.mark.asyncio
    async def test_user_action_add_success(self, client, subscription_data, mock_arq, pg_pool):
        """Успешное добавление пользователя - задача попала в очередь"""
        user_id = subscription_data["user_id"]
        order_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": user_id,
                "uuid": "12345678-1234-1234-1234-123456789abc",
                "tg_username": "test_user",
                "order_id": order_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Пользователь обрабатывается в фоновой очереди"
        assert data["job_id"] == "test-job-12345"
        
        # Проверяем что ARQ был вызван
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "action_on_core_proto_by_sub_plan"
        assert call_args[0][1] == "12345678-1234-1234-1234-123456789abc"  # uuid
        assert call_args[0][2] == "test_user"  # tg_username
        assert call_args[0][4] == "add"  # action
        
        # Проверяем что в outbox создалась запись
        async with pg_pool.acquire() as conn:
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE order_id = $1",
                order_id
            )
            assert outbox_count == 1  # Только 1 видимая нода на активной машине
    
    @pytest.mark.asyncio
    async def test_user_action_delete_success(self, client, subscription_data, mock_arq, pg_pool):
        """Успешное удаление пользователя"""
        user_id = subscription_data["user_id"]
        order_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": user_id,
                "uuid": "87654321-4321-4321-4321-cba987654321",
                "tg_username": "user_del",
                "order_id": order_id,
                "action": "delete"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "job_id" in data
        
        # Проверяем что action = delete
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][4] == "delete"


class TestUserActionFiltering:
    """Тесты фильтрации нод по различным условиям"""
    
    @pytest.mark.asyncio
    async def test_user_action_filters_inactive_nodes(self, client, subscription_data, mock_arq, pg_pool):
        """Неактивные физические ноды (is_active=false) не попадают в выборку"""
        user_id = subscription_data["user_id"]
        order_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": user_id,
                "uuid": "11111111-1111-1111-1111-111111111111",
                "tg_username": "test_filter",
                "order_id": order_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что в sub_nodes передана только 1 нода (активная)
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]  # Третий аргумент - список нод
        assert len(sub_nodes) == 1  # Только активная нода
        
        # Проверяем что неактивная нода НЕ попала
        vnode_ids = [node["node_proto_id"] for node in sub_nodes]
        assert subscription_data["vnode_on_inactive"] not in vnode_ids
    
    @pytest.mark.asyncio
    async def test_user_action_filters_invisible_vnodes(self, client, subscription_data, mock_arq):
        """Невидимые виртуальные ноды (user_visible=false) не попадают в выборку"""
        user_id = subscription_data["user_id"]
        order_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": user_id,
                "uuid": "22222222-2222-2222-2222-222222222222",
                "tg_username": "test_invis",
                "order_id": order_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что невидимая нода НЕ попала
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]
        vnode_ids = [node["node_proto_id"] for node in sub_nodes]
        assert subscription_data["invisible_vnode"] not in vnode_ids
    
    @pytest.mark.asyncio
    async def test_user_action_filters_inactive_subscription(self, client, subscription_data, mock_arq):
        """Неактивная подписка (is_active=false) не возвращает ноды"""
        user_id = subscription_data["user_id"]
        inactive_order_id = subscription_data["inactive_order_id"]
        
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": user_id,
                "uuid": "33333333-3333-3333-3333-333333333333",
                "tg_username": "test_inactive",
                "order_id": inactive_order_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что список нод пустой
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]
        assert len(sub_nodes) == 0  # Неактивная подписка не возвращает ноды
    
    @pytest.mark.asyncio
    async def test_user_action_no_subscription_found(self, client, mock_arq):
        """Нет подписки для пользователя - пустая выборка"""
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": 99999,  # Несуществующий пользователь
                "uuid": "44444444-4444-4444-4444-444444444444",
                "tg_username": "no_sub",
                "order_id": 99999,  # Несуществующая подписка
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True  # Эндпоинт возвращает 200 даже при пустой выборке
        
        # Проверяем что список нод пустой
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]
        assert len(sub_nodes) == 0


class TestUserActionValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_user_action_invalid_uuid_length(self, client, mock_arq):
        """UUID неправильной длины (должно быть ровно 36 символов)"""
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": 1,
                "uuid": "short-uuid",  # Слишком короткий
                "tg_username": "test_user",
                "order_id": 1,
                "action": "add"
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # Проверяем что ошибка связана с uuid
        assert any("uuid" in str(err).lower() for err in data["detail"])
    
    @pytest.mark.asyncio
    async def test_user_action_invalid_username_length(self, client, mock_arq):
        """Telegram username слишком короткий (минимум 5 символов)"""
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": 1,
                "uuid": "12345678-1234-1234-1234-123456789abc",
                "tg_username": "usr",  # Слишком короткий (< 5)
                "order_id": 1,
                "action": "add"
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        assert any("tg_username" in str(err).lower() for err in data["detail"])
    
    @pytest.mark.asyncio
    async def test_user_action_invalid_action_type(self, client, mock_arq):
        """Неверный тип действия (должно быть 'add' или 'delete')"""
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": 1,
                "uuid": "12345678-1234-1234-1234-123456789abc",
                "tg_username": "test_user",
                "order_id": 1,
                "action": "update"  # Неверное значение
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        assert any("action" in str(err).lower() for err in data["detail"])
    
    @pytest.mark.asyncio
    async def test_user_action_missing_required_fields(self, client, mock_arq):
        """Отсутствуют обязательные поля"""
        response = await client.post(
            "/api/v1/cmd_center/core_protocol/user/action",
            json={
                "user_id": 1,
                # uuid отсутствует
                "tg_username": "test_user",
                "order_id": 1,
                "action": "add"
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
