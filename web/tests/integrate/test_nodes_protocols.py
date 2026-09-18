"""
Интеграционные тесты для API виртуальных нод (nodes_protocols.py)
Тестируют CRUD операции с виртуальными нодами (протоколы на физических серверах)
"""

import pytest


class TestGetNodeProtocols:
    """Тесты для GET /api/v1/private/nodes/{node_id}/protocols"""

    @pytest.mark.asyncio
    async def test_get_node_protocols_empty(self, client, physical_node_seed):
        """Получение пустого списка (нет виртуальных нод на физической ноде)"""
        # У node_id_3 нет виртуальных нод
        node_id = physical_node_seed['node_id_3']
        response = await client.get(f"/api/v1/private/protocols/info/{node_id}", params={"limit": 10, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert "protocols" in data
        assert len(data["protocols"]) == 0

    @pytest.mark.asyncio
    async def test_get_node_protocols_with_data(self, client, virtual_node_seed):
        """Получение списка виртуальных нод на физической ноде"""
        node_id = virtual_node_seed['node_id_1']
        response = await client.get(f"/api/v1/private/protocols/info/{node_id}", params={"limit": 10, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert "protocols" in data
        assert len(data["protocols"]) == 2  # vnode1 и vnode2 на node_id_1

        # Проверяем структуру данных
        protocol = data["protocols"][0]
        assert "node_proto_id" in protocol
        assert "proto_id" in protocol
        assert "proto_name" in protocol
        assert "title" in protocol
        assert "sub_node_address" in protocol

    @pytest.mark.asyncio
    async def test_get_node_protocols_pagination(self, client, virtual_node_seed):
        """Пагинация списка виртуальных нод"""
        node_id = virtual_node_seed['node_id_1']
        # Получаем первую виртуальную ноду
        response1 = await client.get(f"/api/v1/private/protocols/info/{node_id}", params={"limit": 1, "offset": 0})
        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["protocols"]) == 1

        # Получаем вторую виртуальную ноду
        response2 = await client.get(f"/api/v1/private/protocols/info/{node_id}", params={"limit": 1, "offset": 1})
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
            f"/api/v1/private/nodes/protocols/{vnode_id}",
            json={
                "config_path": "/etc/updated-proto/new-config.json",
                "title": "Fully Updated Virtual Node",
                "metrics_port": 9091,
                "proto_port": 8444,
                "sub_node_address": "updated-vnode.example.com",
            },
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
            f"/api/v1/private/nodes/protocols/{vnode_id}",
            json={"title": "Partially Updated Title", "sub_node_address": "new-address.example.com"},
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
            f"/api/v1/private/nodes/protocols/{vnode_id}", json={"config_path": "/etc/new-path/config.json"}
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

        response = await client.put(f"/api/v1/private/nodes/protocols/{vnode_id}", json={"metrics_port": 9092})

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

        response = await client.put(f"/api/v1/private/nodes/protocols/{vnode_id}", json={"proto_port": 8445})

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
            f"/api/v1/private/nodes/protocols/{vnode_id}",
            json={
                "metrics_port": 9090  # Уже занят vnode1
            },
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
            f"/api/v1/private/nodes/protocols/{vnode_id}",
            json={
                "proto_port": 8443  # Уже занят vnode1
            },
        )

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Конфликт портов" in data["detail"]["message"]

    @pytest.mark.asyncio
    async def test_update_vnode_not_found(self, client, db_seed):
        """Обновление несуществующей виртуальной ноды (404)"""
        response = await client.put("/api/v1/private/nodes/protocols/9919", json={"title": "Non-Existent Node"})

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдена" in data["detail"]["message"]

    @pytest.mark.asyncio
    async def test_update_vnode_no_fields(self, client, virtual_node_seed):
        """Обновление без полей (пустой body)"""
        vnode_id = virtual_node_seed["vnode_id_1"]

        response = await client.put(f"/api/v1/private/nodes/protocols/{vnode_id}", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Нет полей для обновления" in data["message"]


class TestDeleteVirtualNode:
    """Тесты для DELETE /api/v1/private/nodes/protocols/{np_id}"""

    @pytest.mark.asyncio
    async def test_delete_vnode_success(self, client, virtual_node_seed, db_pool):
        """Успешное удаление виртуальной ноды"""
        vnode_id = virtual_node_seed["vnode_id_3"]

        response = await client.delete(f"/api/v1/private/nodes/protocols/{vnode_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Виртуальная нода удалена"

        # Проверяем что нода действительно удалена из БД
        async with db_pool.acquire() as conn:
            vnode_exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM nodes_protocols WHERE id = $1)", vnode_id)
            assert vnode_exists is False


class TestRegisterVirtualNode:
    """Тесты для POST /api/v1/server/nodes/protocols/register"""

    @pytest.mark.asyncio
    async def test_register_vnode_success_full_params(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Успешная регистрация виртуальной ноды со всеми параметрами"""
        # Создаём протокол для тестирования
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Test Proto for Register",
            )

        node_id = physical_node_seed["node_id_1"]

        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": node_id,
                "title": "Full Params Virtual Node Test",
                "metrics_port": 9095,
                "proto_port": 8450,
                "config_path": "/etc/vpn/config-test.json",
                "constant_node_data_obj": {"key": "value", "nested": {"data": 123}},
                "sub_node_address": "test-vnode.example.com",
                "metrics_command": "custom-metrics-cmd",
                "reload_core_command": "custom-reload-cmd",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Виртуальная нода поставлена на регистрацию"
        assert "node_proto_id" in data
        assert "title" in data
        assert data["title"] == "Full Params Virtual Node Test"

        # Проверяем что запись создалась в БД с правильными данными
        node_proto_id = data["node_proto_id"]
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode is not None
            assert vnode["node_id"] == node_id
            assert vnode["proto_id"] == proto_id
            assert vnode["metrics_port"] == 9095
            assert vnode["proto_port"] == 8450
            assert vnode["config_path"] == "/etc/vpn/config-test.json"
            assert vnode["constant_node_data_obj"] == {"key": "value", "nested": {"data": 123}}
            assert vnode["sub_node_address"] == "test-vnode.example.com"
            assert vnode["metrics_command"] == "custom-metrics-cmd"
            assert vnode["reload_core_command"] == "custom-reload-cmd"
            assert vnode["reg_status"] == 1  # pending по умолчанию

    @pytest.mark.asyncio
    async def test_register_vnode_success_minimal_params(
        self, client, physical_node_seed, proto_template_seed, db_pool
    ):
        """Успешная регистрация с минимальными обязательными параметрами"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Minimal Proto",
            )

        node_id = physical_node_seed["node_id_1"]

        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": node_id,
                "title": "Minimal Node",
                "proto_port": 8451,
                "config_path": "/etc/vpn/minimal.json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "node_proto_id" in data

        # Проверяем дефолтные значения в БД
        node_proto_id = data["node_proto_id"]
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["metrics_port"] is None
            assert vnode["constant_node_data_obj"] == {}  # Дефолт пустой объект
            assert vnode["sub_node_address"] is None
            assert vnode["metrics_command"] is None
            assert vnode["reload_core_command"] is None
            assert vnode["reg_status"] == 1

    @pytest.mark.asyncio
    async def test_register_vnode_with_optional_commands(
        self, client, physical_node_seed, proto_template_seed, db_pool
    ):
        """Регистрация с кастомными командами метрик и перезагрузки"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto with Commands",
            )

        node_id = physical_node_seed["node_id_2"]

        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": node_id,
                "title": "Node with Commands",
                "proto_port": 8452,
                "config_path": "/etc/vpn/commands.json",
                "metrics_command": "docker exec xray-metrics curl localhost:9999/stats",
                "reload_core_command": "systemctl reload xray-custom",
            },
        )

        assert response.status_code == 200
        data = response.json()
        node_proto_id = data["node_proto_id"]

        # Проверяем команды сохранились
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["metrics_command"] == "docker exec xray-metrics curl localhost:9999/stats"
            assert vnode["reload_core_command"] == "systemctl reload xray-custom"

    @pytest.mark.asyncio
    async def test_register_vnode_constant_node_data_default(
        self, client, physical_node_seed, proto_template_seed, db_pool
    ):
        """Проверка что constant_node_data_obj по умолчанию устанавливается как {}"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Default Data",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": physical_node_seed["node_id_1"],
                "title": "Default Data Node",
                "proto_port": 8453,
                "config_path": "/etc/vpn/default.json",
                "constant_node_data_obj": None,  # Явно передаём None
            },
        )

        assert response.status_code == 200
        node_proto_id = response.json()["node_proto_id"]

        # Проверяем что в БД сохранился пустой объект
        async with db_pool.acquire() as conn:
            constant_data = await conn.fetchval(
                "SELECT constant_node_data_obj FROM nodes_protocols WHERE id = $1", node_proto_id
            )
            assert constant_data == {}

    @pytest.mark.asyncio
    async def test_register_vnode_invalid_proto_id(self, client, physical_node_seed):
        """Регистрация с несуществующим proto_id (404)"""
        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": 32000,  # Несуществующий протокол (в диапазоне smallint)
                "node_id": physical_node_seed["node_id_1"],
                "title": "Invalid Proto",
                "proto_port": 8454,
                "config_path": "/etc/vpn/invalid.json",
            },
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдены" in data["detail"]["message"]

    @pytest.mark.asyncio
    async def test_register_vnode_invalid_node_id(self, client, proto_template_seed, db_pool):
        """Регистрация с несуществующим node_id (404)"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Invalid Node",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": 32000,  # Несуществующая физическая нода (в диапазоне smallint)
                "title": "Invalid Node",
                "proto_port": 8455,
                "config_path": "/etc/vpn/invalid-node.json",
            },
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдены" in data["detail"]["message"]

    @pytest.mark.asyncio
    async def test_register_vnode_check_db_status_pending(
        self, client, physical_node_seed, proto_template_seed, db_pool
    ):
        """Проверка что reg_status устанавливается в 1 (pending) по умолчанию"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Status Check",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": physical_node_seed["node_id_1"],
                "title": "Status Pending Node",
                "proto_port": 8456,
                "config_path": "/etc/vpn/status.json",
            },
        )

        assert response.status_code == 200
        node_proto_id = response.json()["node_proto_id"]

        # Проверяем статус в БД
        async with db_pool.acquire() as conn:
            reg_status = await conn.fetchval("SELECT reg_status FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert reg_status == 1  # pending


class TestConfirmVirtualNode:
    """Тесты для POST /api/v1/server/nodes/protocols/confirm"""

    @pytest.mark.asyncio
    async def test_confirm_vnode_success_status(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Успешное подтверждение со статусом success (2)"""
        # Создаём виртуальную ноду в статусе pending
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Confirm Success",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status)
                VALUES ($1, $2, $3, $4, $5, 1)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "Pending Node",
                8460,
                "/tmp/pending.json",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,  # success
                "title": "Confirmed Success Node",
                "config_path": "/etc/vpn/confirmed.json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Виртуальная нода поставлена на регистрацию"

        # Проверяем обновление в БД
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["reg_status"] == 2  # success
            assert vnode["title"] == "Confirmed Success Node"
            assert vnode["config_path"] == "/etc/vpn/confirmed.json"

    @pytest.mark.asyncio
    async def test_confirm_vnode_failed_status(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Подтверждение со статусом failed (3)"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Confirm Failed",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status)
                VALUES ($1, $2, $3, $4, $5, 1)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "Pending Failed Node",
                8461,
                "/tmp/pending-fail.json",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 3,  # failed
                "title": "Failed Registration Node",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем статус failed в БД
        async with db_pool.acquire() as conn:
            reg_status = await conn.fetchval("SELECT reg_status FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert reg_status == 3  # failed

    @pytest.mark.asyncio
    async def test_confirm_vnode_string_status(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Поддержка строковых статусов: "success" → 2, "failed" → 3"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto String Status",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status)
                VALUES ($1, $2, $3, $4, $5, 1)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "String Status Node",
                8462,
                "/tmp/string-status.json",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": "success",  # Строковый статус
            },
        )

        assert response.status_code == 200

        # Проверяем что строка преобразовалась в int
        async with db_pool.acquire() as conn:
            reg_status = await conn.fetchval("SELECT reg_status FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert reg_status == 2

    @pytest.mark.asyncio
    async def test_confirm_vnode_update_params(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Обновление параметров при подтверждении (config_path, commands)"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Update Params",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status)
                VALUES ($1, $2, $3, $4, $5, 1)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "Update Params Node",
                8463,
                "/tmp/old-config.json",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,
                "config_path": "/etc/vpn/new-config.json",
                "reload_core_command": "systemctl reload vpn-core",
                "metrics_command": "curl localhost:9999/metrics",
                "constant_node_data_obj": {"updated": True, "version": 2},
            },
        )

        assert response.status_code == 200

        # Проверяем обновлённые параметры
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["config_path"] == "/etc/vpn/new-config.json"
            assert vnode["reload_core_command"] == "systemctl reload vpn-core"
            assert vnode["metrics_command"] == "curl localhost:9999/metrics"
            assert vnode["constant_node_data_obj"] == {"updated": True, "version": 2}

    @pytest.mark.asyncio
    async def test_confirm_vnode_partial_update(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Частичное обновление - только status и title"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Partial Update",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status, metrics_command)
                VALUES ($1, $2, $3, $4, $5, 1, $6)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "Old Title",
                8464,
                "/etc/vpn/partial.json",
                "old-metrics-cmd",
            )

        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,
                "title": "Updated Title Only",
                # Не передаём config_path, metrics_command и другие поля
            },
        )

        assert response.status_code == 200

        # Проверяем что обновились только указанные поля
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["reg_status"] == 2
            assert vnode["title"] == "Updated Title Only"
            # Старые значения сохранились
            assert vnode["config_path"] == "/etc/vpn/partial.json"
            assert vnode["metrics_command"] == "old-metrics-cmd"

    @pytest.mark.asyncio
    async def test_confirm_vnode_not_found(self, client, db_seed):
        """Подтверждение несуществующей виртуальной ноды (404)"""
        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": 32000,  # Несуществующая нода (в диапазоне int)
                "status": 2,
            },
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдены" in data["detail"]["message"]

    @pytest.mark.asyncio
    async def test_confirm_vnode_updates_reg_status(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Проверка что reg_status корректно обновляется в БД"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Status Update",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status)
                VALUES ($1, $2, $3, $4, $5, 1)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "Status Update Node",
                8465,
                "/tmp/status-update.json",
            )

            # Проверяем начальный статус
            initial_status = await conn.fetchval("SELECT reg_status FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert initial_status == 1  # pending

        # Подтверждаем со статусом success
        response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,
            },
        )

        assert response.status_code == 200

        # Проверяем что статус обновился
        async with db_pool.acquire() as conn:
            updated_status = await conn.fetchval("SELECT reg_status FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert updated_status == 2  # success


class TestRegisterConfirmFlow:
    """Интеграционные тесты полного цикла register → confirm"""

    @pytest.mark.asyncio
    async def test_full_registration_flow_success(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Полный цикл: register → confirm success → проверка БД"""
        # Создаём протокол
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Full Flow",
            )

        # Шаг 1: Регистрация
        register_response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": physical_node_seed["node_id_1"],
                "title": "Full Flow Node",
                "proto_port": 8470,
                "config_path": "/tmp/flow.json",
                "constant_node_data_obj": {"flow": "test"},
            },
        )

        assert register_response.status_code == 200
        register_data = register_response.json()
        node_proto_id = register_data["node_proto_id"]

        # Проверяем статус pending после регистрации
        async with db_pool.acquire() as conn:
            reg_status = await conn.fetchval("SELECT reg_status FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert reg_status == 1  # pending

        # Шаг 2: Подтверждение
        confirm_response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,  # success
                "title": "Full Flow Confirmed",
                "config_path": "/etc/vpn/flow-confirmed.json",
                "constant_node_data_obj": {"flow": "confirmed", "ready": True},
            },
        )

        assert confirm_response.status_code == 200

        # Шаг 3: Финальная проверка БД
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["reg_status"] == 2  # success
            assert vnode["title"] == "Full Flow Confirmed"
            assert vnode["config_path"] == "/etc/vpn/flow-confirmed.json"
            assert vnode["constant_node_data_obj"] == {"flow": "confirmed", "ready": True}

    @pytest.mark.asyncio
    async def test_full_registration_flow_failed(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Полный цикл с неудачной регистрацией: register → confirm failed → проверка БД"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Failed Flow",
            )

        # Регистрация
        register_response = await client.post(
            "/api/v1/server/nodes/protocols/register",
            json={
                "proto_id": proto_id,
                "node_id": physical_node_seed["node_id_1"],
                "title": "Failed Flow Node",
                "proto_port": 8471,
                "config_path": "/tmp/failed-flow.json",
            },
        )

        assert register_response.status_code == 200
        node_proto_id = register_response.json()["node_proto_id"]

        # Подтверждение с failed статусом
        confirm_response = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": "failed",  # Строковый статус
                "title": "Failed Registration",
            },
        )

        assert confirm_response.status_code == 200

        # Проверяем failed статус в БД
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["reg_status"] == 3  # failed
            assert vnode["title"] == "Failed Registration"

    @pytest.mark.asyncio
    async def test_confirm_idempotency(self, client, physical_node_seed, proto_template_seed, db_pool):
        """Повторное подтверждение одной и той же ноды (идемпотентность)"""
        async with db_pool.acquire() as conn:
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                proto_template_seed["tmp_id"],
                "Proto Idempotency",
            )
            node_proto_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, proto_id, title, proto_port, config_path, reg_status)
                VALUES ($1, $2, $3, $4, $5, 1)
                RETURNING id
                """,
                physical_node_seed["node_id_1"],
                proto_id,
                "Idempotent Node",
                8472,
                "/tmp/idempotent.json",
            )

        # Первое подтверждение
        first_confirm = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,
                "title": "Confirmed Once",
            },
        )
        assert first_confirm.status_code == 200

        # Второе подтверждение той же ноды
        second_confirm = await client.post(
            "/api/v1/server/nodes/protocols/confirm",
            json={
                "node_proto_id": node_proto_id,
                "status": 2,
                "title": "Confirmed Twice",
            },
        )
        assert second_confirm.status_code == 200

        # Проверяем что обновление прошло успешно
        async with db_pool.acquire() as conn:
            vnode = await conn.fetchrow("SELECT * FROM nodes_protocols WHERE id = $1", node_proto_id)
            assert vnode["reg_status"] == 2
            assert vnode["title"] == "Confirmed Twice"  # Обновилось при повторном вызове
