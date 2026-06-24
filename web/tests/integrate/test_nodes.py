"""
Интеграционные тесты для API физических нод (nodes_api.py)
Тестируют взаимодействие с микросервисом node_client через Fake классы
"""
import pytest
from web.tests.conftest import FakeAiohttpSession



class TestCreatePhysicalNode:
    """Тесты для POST /api/v1/private/nodes/create"""
    
    @pytest.mark.asyncio
    async def test_create_node_success(self, client, seed_info):
        """Успешное создание физической ноды с валидным ответом от микросервиса"""
        # Мокируем успешный ответ от healthcheck
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "success": True,
                "message": "pong",
                "service": "test-node-service",
                "version": "0.1"
            }
        )
        
        response = await client.post(
            "/api/v1/private/nodes/create",
            json={
                "ip": "192.168.1.50",
                "private_ip": "10.0.0.50",
                "api_port": 8100,
                "title": "New Test Node",
                "is_active": True
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "node_id" in data
        assert data["node_name"] == "test-node-service"
        assert data["message"] == "Нода создана"
    
    @pytest.mark.asyncio
    async def test_create_node_connection_error(self, client, seed_info):
        """Ошибка подключения к микросервису (502 Bad Gateway)"""
        # Мокируем ClientError (нода не отвечает)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(raise_error=True)
        
        response = await client.post(
            "/api/v1/private/nodes/create",
            json={
                "ip": "192.168.1.51",
                "private_ip": "10.0.0.51",
                "api_port": 8101,
                "title": "Unreachable Node",
                "is_active": True
            }
        )
        
        assert response.status_code == 502
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Не удалось связаться с нодой" in data["detail"]["message"]
        assert "err_message" in data["detail"]

    @pytest.mark.asyncio
    async def test_create_node_invalid_response(self, client, seed_info):
        """Невалидный ответ от микросервиса (400 Bad Request)"""
        # Мокаем ответ aiohttp
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"message": "pong"}
        )

        # Запрос на тестируемый эндпоинт
        response = await client.post(
            "/api/v1/private/nodes/create",
            json={
                "ip": "192.168.1.52",
                "private_ip": "10.0.0.52",
                "api_port": 8102,
                "title": "Invalid Response Node",
                "is_active": True
            }
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Неизвестный ответ от ноды" in data["detail"]["message"]
        assert "node_resp" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_create_node_duplicate(self, client, seed_info):
        """Попытка создать дубликат ноды (409 Conflict)"""
        # Создаём первую ноду успешно
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "success": True,
                "message": "pong",
                "service": "duplicate-node",
                "version": "0.1"
            }
        )
        
        # Первая попытка - успех
        response1 = await client.post(
            "/api/v1/private/nodes/create",
            json={
                "ip": "192.168.1.60",
                "private_ip": "10.0.0.60",
                "api_port": 8110,
                "title": "Duplicate Node",
                "is_active": True
            }
        )
        assert response1.status_code == 200
        
        # Вторая попытка с теми же IP - конфликт
        response2 = await client.post(
            "/api/v1/private/nodes/create",
            json={
                "ip": "192.168.1.60",
                "private_ip": "10.0.0.60",
                "api_port": 8110,
                "title": "Duplicate Node 2",
                "is_active": True
            }
        )
        
        assert response2.status_code == 409
        data = response2.json()
        assert data["detail"]["success"] is False
        assert "уже создан" in data["detail"]["message"]


class TestGetAllPhysicalNodes:
    """Тесты для GET /api/v1/private/nodes/all"""
    
    @pytest.mark.asyncio
    async def test_get_all_nodes_empty(self, client, seed_info):
        """Получение пустого списка нод (нет нод в БД)"""
        response = await client.get("/api/v1/private/nodes/all?limit=10&offset=0")
        
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert len(data["nodes"]) == 0
    
    @pytest.mark.asyncio
    async def test_get_all_nodes_with_data(self, client, physical_node_seed):
        """Получение списка с несколькими нодами"""
        response = await client.get("/api/v1/private/nodes/all?limit=10&offset=0")
        
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert len(data["nodes"]) == 3  # Три ноды из фикстуры
        
        # Проверяем структуру данных
        node = data["nodes"][0]
        assert "id" in node
        assert "ip" in node
        assert "private_ip" in node
        assert "api_port" in node
        assert "title" in node
        assert "is_active" in node
        assert "binded_vnodes_count" in node
    
    @pytest.mark.asyncio
    async def test_get_all_nodes_filter_active(self, client, physical_node_seed):
        """Фильтрация нод по is_active"""
        # Только активные ноды
        response_active = await client.get("/api/v1/private/nodes/all?is_active=true&limit=10&offset=0")
        assert response_active.status_code == 200
        data_active = response_active.json()
        assert len(data_active["nodes"]) == 2  # node_id_1 и node_id_3 (обе активные)
        assert all(node["is_active"] is True for node in data_active["nodes"])
        
        # Только неактивные ноды
        response_inactive = await client.get("/api/v1/private/nodes/all?is_active=false&limit=10&offset=0")
        assert response_inactive.status_code == 200
        data_inactive = response_inactive.json()
        assert len(data_inactive["nodes"]) == 1  # node_id_2 (неактивная)
        assert data_inactive["nodes"][0]["is_active"] is False


class TestGetPhysicalNodeById:
    """Тесты для GET /api/v1/private/nodes/{node_id}"""
    
    @pytest.mark.asyncio
    async def test_get_node_success(self, client, physical_node_seed):
        """Успешное получение ноды по ID"""
        node_id = physical_node_seed["node_id_1"]
        response = await client.get(f"/api/v1/private/nodes/{node_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "node" in data
        assert data["node"]["node_id"] == node_id
        assert data["node"]["ip"] == "192.168.1.100"
        assert data["node"]["private_ip"] == "10.0.0.100"
        assert data["node"]["api_port"] == 8100
        assert data["node"]["title"] == "Test Physical Node 1"
    
    @pytest.mark.asyncio
    async def test_get_node_not_found(self, client, seed_info):
        """Нода не найдена (404)"""
        response = await client.get("/api/v1/private/nodes/9999")
        
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert "не найдена" in data["message"]


class TestUpdatePhysicalNode:
    """Тесты для PUT /api/v1/private/nodes/update/{node_id}"""
    
    @pytest.mark.asyncio
    async def test_update_node_success(self, client, physical_node_seed):
        """Успешное обновление всех полей ноды"""
        node_id = physical_node_seed["node_id_1"]
        
        response = await client.put(
            f"/api/v1/private/nodes/update/{node_id}",
            json={
                "node_id": node_id,
                "ip": "192.168.1.200",
                "private_ip": "10.0.0.200",
                "api_port": 8200,
                "title": "Updated Node Title",
                "is_active": False
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Нода обновлена"
        
        # Проверяем что данные обновились в БД
        get_response = await client.get(f"/api/v1/private/nodes/{node_id}")
        updated_node = get_response.json()["node"]
        assert updated_node["ip"] == "192.168.1.200"
        assert updated_node["private_ip"] == "10.0.0.200"
        assert updated_node["api_port"] == 8200
        assert updated_node["title"] == "Updated Node Title"
        assert updated_node["is_active"] is False
    
    @pytest.mark.asyncio
    async def test_update_node_partial(self, client, physical_node_seed):
        """Частичное обновление (только некоторые поля)"""
        node_id = physical_node_seed["node_id_2"]
        
        response = await client.put(
            f"/api/v1/private/nodes/update/{node_id}",
            json={
                "node_id": node_id,
                "title": "Partially Updated",
                "is_active": True
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что только указанные поля изменились
        get_response = await client.get(f"/api/v1/private/nodes/{node_id}")
        updated_node = get_response.json()["node"]
        assert updated_node["title"] == "Partially Updated"
        assert updated_node["is_active"] is True
        # Старые значения сохранились
        assert updated_node["ip"] == "192.168.1.101"
        assert updated_node["private_ip"] == "10.0.0.101"
    
    @pytest.mark.asyncio
    async def test_update_node_conflict(self, client, physical_node_seed):
        """Конфликт при обновлении (409) - дубликат ip/port пары"""
        node_id_1 = physical_node_seed["node_id_1"]
        
        # Пытаемся обновить node_id_1 на ip/port от node_id_2
        response = await client.put(
            f"/api/v1/private/nodes/update/{node_id_1}",
            json={
                "node_id": node_id_1,
                "ip": "192.168.1.101",
                "private_ip": "10.0.0.101",
                "api_port": 8101
            }
        )
        
        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Конфликт" in data["detail"]["message"]


class TestDeletePhysicalNode:
    """Тесты для DELETE /api/v1/private/nodes/{node_id}"""
    
    @pytest.mark.asyncio
    async def test_delete_node_success(self, client, physical_node_seed):
        """Успешное удаление физической ноды"""
        node_id = physical_node_seed["node_id_2"]
        
        response = await client.delete(f"/api/v1/private/nodes/{node_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Нода удалена"
        
        # Проверяем что нода действительно удалена
        get_response = await client.get(f"/api/v1/private/nodes/{node_id}")
        assert get_response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_delete_node_cascade(self, client, physical_node_seed, pg_pool, proto_template_seed):
        """Каскадное удаление виртуальных нод при удалении физической ноды"""
        node_id = physical_node_seed["node_id_1"]
        
        # Сначала создаём протокол для FK constraint
        async with pg_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                """
                INSERT INTO protocols (tmp_id, name)
                VALUES ($1, $2)
                RETURNING id
                """,
                proto_template_seed["tmp_id"],
                "Test Protocol"
            )
            
            # Создаём виртуальную ноду для node_id_1
            vnode_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, config_path, user_visible, title, proto_port, sub_node_address)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                node_id,
                proto_id,
                "/etc/test-proto/config.json",
                True,
                "Test VNode",
                443,
                "192.168.1.100"
            )
        
        # Проверяем что виртуальная нода существует
        async with pg_pool.acquire() as conn:
            vnode_exists_before = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM nodes_protocols WHERE id = $1)",
                vnode_id
            )
            assert vnode_exists_before is True
        
        # Удаляем физическую ноду
        response = await client.delete(f"/api/v1/private/nodes/{node_id}")
        assert response.status_code == 200
        
        # Проверяем что виртуальная нода тоже удалилась (CASCADE)
        async with pg_pool.acquire() as conn:
            vnode_exists_after = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM nodes_protocols WHERE id = $1)",
                vnode_id
            )
            assert vnode_exists_after is False
