"""
Интеграционные тесты для API виртуальных нод (nodes_protocols.py)
Тестируют CRUD операции с виртуальными нодами (протоколы на физических серверах)
"""
import pytest


class TestCreateVirtualNode:
    """Тесты для POST /api/v1/private/nodes/protocols/create"""
    
    @pytest.mark.asyncio
    async def test_create_vnode_success(self, client, physical_node_seed, proto_template_seed, pg_pool):
        """Успешное создание виртуальной ноды"""
        # Создаём протокол для теста
        async with pg_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Test Protocol for Create"
            )
        
        response = await client.post(
            "/api/v1/private/nodes/protocols/create",
            json={
                "node_id": physical_node_seed["node_id_1"],
                "proto_id": proto_id,
                "title": "New Virtual Node",
                "sub_node_address": "new-vnode.example.com"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "node_protocol_id" in data
        assert data["message"] == "Успешно добавили виртуальную ноду"
        
        # Проверяем что нода создалась в БД
        async with pg_pool.acquire() as conn:
            vnode = await conn.fetchrow(
                "SELECT * FROM nodes_protocols WHERE id = $1",
                data["node_protocol_id"]
            )
            assert vnode is not None
            assert vnode["title"] == "New Virtual Node"
            assert vnode["sub_node_address"] == "new-vnode.example.com"
    
    @pytest.mark.asyncio
    async def test_create_vnode_node_not_found(self, client, proto_template_seed, pg_pool):
        """Физическая нода не найдена (404)"""
        # Создаём протокол для теста
        async with pg_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Test Protocol"
            )
        
        response = await client.post(
            "/api/v1/private/nodes/protocols/create",
            json={
                "node_id": 9999,  # Несуществующий node_id
                "proto_id": proto_id,
                "title": "VNode on Non-Existent Node",
                "sub_node_address": None
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "не существует" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_create_vnode_protocol_not_found(self, client, physical_node_seed):
        """Протокол не найден (404)"""
        response = await client.post(
            "/api/v1/private/nodes/protocols/create",
            json={
                "node_id": physical_node_seed["node_id_1"],
                "proto_id": 9999,  # Несуществующий proto_id
                "title": "VNode Non-Exist Proto",  # Укорочено до 30 символов
                "sub_node_address": None
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "не существует" in data["detail"]["message"]


class TestGetNodeProtocols:
    """Тесты для GET /api/v1/private/nodes/{node_id}/protocols"""
    
    @pytest.mark.asyncio
    async def test_get_node_protocols_empty(self, client, physical_node_seed):
        """Получение пустого списка (нет виртуальных нод на физической ноде)"""
        # У node_id_1 пока нет виртуальных нод (virtual_node_seed не использована)
        node_id = physical_node_seed['node_id_1']
        response = await client.get(
            f"/api/v1/private/nodes/protocols/by_node",
            params={"node_id": node_id, "limit": 10, "offset": 0}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "protocols" in data
        assert len(data["protocols"]) == 0
    
    @pytest.mark.asyncio
    async def test_get_node_protocols_with_data(self, client, virtual_node_seed):
        """Получение списка виртуальных нод на физической ноде"""
        node_id = virtual_node_seed['node_id_1']
        response = await client.get(
            f"/api/v1/private/nodes/protocols/by_node",
            params={"node_id": node_id, "limit": 10, "offset": 0}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "protocols" in data
        assert len(data["protocols"]) == 2  # vnode1 и vnode2 на node_id_1
        
        # Проверяем структуру данных
        protocol = data["protocols"][0]
        assert "node_id" in protocol
        assert "proto_id" in protocol
        assert "proto_name" in protocol
        assert "title" in protocol
        assert "sub_node_address" in protocol
    
    @pytest.mark.asyncio
    async def test_get_node_protocols_pagination(self, client, virtual_node_seed):
        """Пагинация списка виртуальных нод"""
        node_id = virtual_node_seed['node_id_1']
        # Получаем первую виртуальную ноду
        response1 = await client.get(
            f"/api/v1/private/nodes/protocols/by_node",
            params={"node_id": node_id, "limit": 1, "offset": 0}
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["protocols"]) == 1
        
        # Получаем вторую виртуальную ноду
        response2 = await client.get(
            f"/api/v1/private/nodes/protocols/by_node",
            params={"node_id": node_id, "limit": 1, "offset": 1}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert len(data2["protocols"]) == 1
        
        # Проверяем что это разные ноды
        assert data1["protocols"][0]["title"] != data2["protocols"][0]["title"]


class TestGetVirtualNodeById:
    """Тесты для GET /api/v1/private/nodes/protocols/{np_id}"""
    
    @pytest.mark.asyncio
    async def test_get_vnode_success(self, client, virtual_node_seed):
        """Успешное получение виртуальной ноды по ID"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        response = await client.get(f"/api/v1/private/nodes/protocols/{vnode_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "node_protocol" in data
        vnode = data["node_protocol"]
        assert vnode["title"] == "VNode1 With Ports"
        assert vnode["sub_node_address"] == "vnode1.example.com"
        assert vnode["metrics_port"] == 9090
        assert vnode["proto_port"] == 8443
        assert vnode["config_path"] == "/etc/test-proto/config1.json"
    
    @pytest.mark.asyncio
    async def test_get_vnode_not_found(self, client, db_seed):
        """Виртуальная нода не найдена (404)"""
        response = await client.get("/api/v1/private/nodes/protocols/9999")
        
        assert response.status_code == 404
        data = response.json()
        assert "не найдена" in data["detail"]["message"]


class TestUpdateVirtualNode:
    """Тесты для PUT /api/v1/private/nodes/protocols/update"""
    
    @pytest.mark.asyncio
    async def test_update_vnode_full(self, client, virtual_node_seed):
        """Полное обновление всех полей виртуальной ноды"""
        vnode_id = virtual_node_seed["vnode_id_2"]
        
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "config_path": "/etc/updated-proto/new-config.json",
                "title": "Fully Updated Virtual Node",
                "metrics_port": 9091,
                "proto_port": 8444,
                "sub_node_address": "updated-vnode.example.com"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Виртуальная нода обновлена"
        
        # Проверяем что данные обновились в БД
        get_response = await client.get(f"/api/v1/private/nodes/protocols/{vnode_id}")
        updated_vnode = get_response.json()["node_protocol"]
        assert updated_vnode["config_path"] == "/etc/updated-proto/new-config.json"
        assert updated_vnode["title"] == "Fully Updated Virtual Node"
        assert updated_vnode["metrics_port"] == 9091
        assert updated_vnode["proto_port"] == 8444
        assert updated_vnode["sub_node_address"] == "updated-vnode.example.com"
    
    @pytest.mark.asyncio
    async def test_update_vnode_partial(self, client, virtual_node_seed):
        """Частичное обновление (только title и sub_node_address)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "title": "Partially Updated Title",
                "sub_node_address": "new-address.example.com"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что только указанные поля изменились
        get_response = await client.get(f"/api/v1/private/nodes/protocols/{vnode_id}")
        updated_vnode = get_response.json()["node_protocol"]
        assert updated_vnode["title"] == "Partially Updated Title"
        assert updated_vnode["sub_node_address"] == "new-address.example.com"
        # Старые значения сохранились
        assert updated_vnode["metrics_port"] == 9090
        assert updated_vnode["proto_port"] == 8443
        assert updated_vnode["config_path"] == "/etc/test-proto/config1.json"
    
    @pytest.mark.asyncio
    async def test_update_vnode_config_path(self, client, virtual_node_seed):
        """Обновление config_path (бизнес-кейс: изменение конфигурации)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "config_path": "/etc/new-path/config.json"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что путь обновился
        get_response = await client.get(f"/api/v1/private/nodes/protocols/{vnode_id}")
        updated_vnode = get_response.json()["node_protocol"]
        assert updated_vnode["config_path"] == "/etc/new-path/config.json"
    
    @pytest.mark.asyncio
    async def test_update_vnode_set_metrics_port(self, client, virtual_node_seed):
        """Установка metrics_port (бизнес-кейс: контроль уникальности портов)"""
        vnode_id = virtual_node_seed["vnode_id_2"]  # У этой ноды нет портов
        
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "metrics_port": 9092
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что порт установлен
        get_response = await client.get(f"/api/v1/private/nodes/protocols/{vnode_id}")
        updated_vnode = get_response.json()["node_protocol"]
        assert updated_vnode["metrics_port"] == 9092
    
    @pytest.mark.asyncio
    async def test_update_vnode_set_proto_port(self, client, virtual_node_seed):
        """Установка proto_port (бизнес-кейс: контроль уникальности портов)"""
        vnode_id = virtual_node_seed["vnode_id_2"]  # У этой ноды нет портов
        
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "proto_port": 8445
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что порт установлен
        get_response = await client.get(f"/api/v1/private/nodes/protocols/{vnode_id}")
        updated_vnode = get_response.json()["node_protocol"]
        assert updated_vnode["proto_port"] == 8445
    
    @pytest.mark.asyncio
    async def test_update_vnode_metrics_port_conflict(self, client, virtual_node_seed):
        """Конфликт metrics_port с другой виртуальной нодой на той же физ. ноде (409)"""
        vnode_id = virtual_node_seed["vnode_id_2"]
        
        # Пытаемся установить metrics_port, который уже занят vnode_id_1
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "metrics_port": 9090  # Уже занят vnode1
            }
        )
        
        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Конфликт портов" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_update_vnode_proto_port_conflict(self, client, virtual_node_seed):
        """Конфликт proto_port с другой виртуальной нодой на той же физ. ноде (409)"""
        vnode_id = virtual_node_seed["vnode_id_2"]
        
        # Пытаемся установить proto_port, который уже занят vnode_id_1
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id,
                "proto_port": 8443  # Уже занят vnode1
            }
        )
        
        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Конфликт портов" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_update_vnode_not_found(self, client, db_seed):
        """Обновление несуществующей виртуальной ноды (404)"""
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": 9999,
                "title": "Non-Existent Node"
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдена" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_update_vnode_no_fields(self, client, virtual_node_seed):
        """Обновление без полей (пустой body)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        response = await client.put(
            "/api/v1/private/nodes/protocols/update",
            json={
                "node_proto_id": vnode_id
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Нет полей для обновления" in data["message"]


class TestDeleteVirtualNode:
    """Тесты для DELETE /api/v1/private/nodes/protocols/{np_id}"""
    
    @pytest.mark.asyncio
    async def test_delete_vnode_success(self, client, virtual_node_seed, pg_pool):
        """Успешное удаление виртуальной ноды"""
        vnode_id = virtual_node_seed["vnode_id_3"]
        
        response = await client.delete(f"/api/v1/private/nodes/protocols/{vnode_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Виртуальная нода удалена"
        
        # Проверяем что нода действительно удалена из БД
        async with pg_pool.acquire() as conn:
            vnode_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM nodes_protocols WHERE id = $1)",
                vnode_id
            )
            assert vnode_exists is False
