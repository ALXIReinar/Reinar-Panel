"""
Интеграционные тесты для POST /core_protocol/user/action
Тестируют добавление/удаление пользователей на ядрах протоколов через фоновую очередь
"""
import pytest


@pytest.fixture
async def subscription_data(db_pool, virtual_node_seed, sub_plan_seed):
    """
    Создаём разнообразные данные для тестирования фильтрации:
    - Активная/неактивная физическая нода
    - Видимая/невидимая виртуальная нода
    - Активная/неактивная подписка
    """
    async with db_pool.acquire() as conn:
        # Создаём тестового пользователя в таблице users
        user_id = await conn.fetchval(
            """
            INSERT INTO users (tg_id, tg_username)
            VALUES ($1, $2)
            RETURNING id
            """,
            123456789,  # Тестовый telegram ID
            "test_user_sub"  # Telegram username
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
        plan_id_2 = sub_plan_seed["plan_id_2"]  # Для неактивной подписки
        
        # Добавляем в vnodes_sub_plans
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            vnode_id_1, plan_id_1
        )
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            vnode_id_1, plan_id_2  # Привязываем и второй план
        )
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            vnode_on_inactive, plan_id_1  # ❌ не должна попасть (нода неактивна)
        )
        await conn.execute(
            "INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id) VALUES ($1, $2)",
            invisible_vnode, plan_id_1  # ❌ не должна попасть (невидима)
        )
        
        # Создаём АКТИВНУЮ подписку для пользователя (plan_id_1)
        # Сначала pay_order
        pay_order_active = await conn.fetchval(
            "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 2, NOW()) RETURNING id",
            user_id
        )
        
        active_user_sub_id = await conn.fetchval(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, true, false, NOW() + INTERVAL '30 days', $4, $5, false, false)
            RETURNING id
            """,
            user_id, pay_order_active, plan_id_1,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "b64_test_user_sub"
        )
        
        # Создаём НЕАКТИВНУЮ подписку для тестов фильтрации (plan_id_2)
        pay_order_inactive = await conn.fetchval(
            "INSERT INTO pay_orders (user_id, status, timestamp) VALUES ($1, 3, NOW()) RETURNING id",
            user_id
        )
        
        inactive_user_sub_id = await conn.fetchval(
            """
            INSERT INTO user_subs (
                user_id, order_id, sub_plan_id, is_active, is_limited,
                expire_date, uuid, b64_id, infinite_traffic, infinite_expire
            )
            VALUES ($1, $2, $3, false, false, NOW() - INTERVAL '1 day', $4, $5, false, false)
            RETURNING id
            """,
            user_id, pay_order_inactive, plan_id_2,
            "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            "b64_inactive_sub"
        )
        
        return {
            "user_id": user_id,
            "active_order_id": active_user_sub_id,  # В новой архитектуре это user_subs.id
            "inactive_order_id": inactive_user_sub_id,  # В новой архитектуре это user_subs.id
            "vnode_id_1": vnode_id_1,  # ✅ Видимая на активной ноде
            "vnode_on_inactive": vnode_on_inactive,  # ❌ На неактивной ноде
            "invisible_vnode": invisible_vnode,  # ❌ Невидимая
        }


class TestUserActionSuccess:
    """Тесты успешного добавления/удаления пользователя"""
    
    @pytest.mark.asyncio
    async def test_user_action_add_success(self, client, subscription_data, mock_arq, db_pool):
        """Успешное добавление пользователя - задача попала в очередь"""
        user_sub_id = subscription_data["active_order_id"]  # В новой архитектуре это user_subs.id
        
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",  # UUID из фикстуры
                "user_sub_id": user_sub_id,
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
        
        # Проверяем что в outbox создалась запись
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1",
                user_sub_id
            )
            assert outbox_count == 1  # Только 1 видимая нода на активной машине
    
    @pytest.mark.asyncio
    async def test_user_action_delete_success(self, client, subscription_data, mock_arq, db_pool):
        """Успешное удаление пользователя"""
        user_sub_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "user_sub_id": user_sub_id,
                "action": "delete"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "job_id" in data
        
        # Проверяем что action = delete
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][4] == "delete"  # action - 5-й аргумент (индекс 4)


class TestUserActionFiltering:
    """Тесты фильтрации нод по различным условиям"""
    
    @pytest.mark.asyncio
    async def test_user_action_filters_inactive_nodes(self, client, subscription_data, mock_arq, db_pool):
        """Неактивные физические ноды (is_active=false) не попадают в выборку"""
        user_sub_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "user_sub_id": user_sub_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что в sub_nodes передана только 1 нода (активная)
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]  # Четвёртый аргумент - список нод
        assert len(sub_nodes) == 1  # Только активная нода
        
        # Проверяем что неактивная нода НЕ попала
        vnode_ids = [node["node_proto_id"] for node in sub_nodes]
        assert subscription_data["vnode_on_inactive"] not in vnode_ids
    
    @pytest.mark.asyncio
    async def test_user_action_filters_invisible_vnodes(self, client, subscription_data, mock_arq):
        """Невидимые виртуальные ноды (user_visible=false) не попадают в выборку"""
        user_sub_id = subscription_data["active_order_id"]
        
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "user_sub_id": user_sub_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что невидимая нода НЕ попала
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]  # Четвёртый аргумент - список нод
        vnode_ids = [node["node_proto_id"] for node in sub_nodes]
        assert subscription_data["invisible_vnode"] not in vnode_ids
    
    @pytest.mark.asyncio
    async def test_user_action_filters_inactive_subscription(self, client, subscription_data, mock_arq):
        """Неактивная подписка (is_active=false) не возвращает ноды"""
        user_sub_id = subscription_data["inactive_order_id"]
        
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                "user_sub_id": user_sub_id,
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что список нод пустой
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]  # Четвёртый аргумент - список нод
        assert len(sub_nodes) == 0  # Неактивная подписка не возвращает ноды
    
    @pytest.mark.asyncio
    async def test_user_action_no_subscription_found(self, client, mock_arq):
        """Нет подписки для пользователя - пустая выборка"""
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "44444444-4444-4444-4444-444444444444",
                "user_sub_id": 99999,  # Несуществующая подписка
                "action": "add"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True  # Эндпоинт возвращает 200 даже при пустой выборке
        
        # ARQ должен быть вызван даже с пустым массивом нод
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        sub_nodes = call_args[0][3]  # Четвёртый аргумент - список нод
        assert len(sub_nodes) == 0  # Пустой массив


class TestUserActionValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_user_action_invalid_uuid_length(self, client, mock_arq):
        """UUID неправильной длины (должно быть ровно 36 символов)"""
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "short-uuid",  # Слишком короткий
                "user_sub_id": 1,
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
        """Тест удалён - tg_username больше не требуется в новой схеме API"""
        # Этот тест больше не актуален, так как tg_username удалён из схемы
        pass
    
    @pytest.mark.asyncio
    async def test_user_action_invalid_action_type(self, client, mock_arq):
        """Неверный тип действия (должно быть 'add' или 'delete')"""
        response = await client.post(
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                "uuid": "12345678-1234-1234-1234-123456789abc",
                "user_sub_id": 1,
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
            "/api/v1/private/cmd_center/core_protocol/user/action",
            json={
                # uuid отсутствует
                "user_sub_id": 1,
                "action": "add"
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

