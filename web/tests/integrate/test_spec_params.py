"""
Интеграционные тесты для эндпоинтов работы со spec параметрами шаблонов (/private/specs).
Тестирует управление spec ключами и значениями для виртуальных нод.
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def vnode_with_spec_seed(client: AsyncClient, proto_template_seed, db_pool):
    """
    Создаёт виртуальную ноду со spec параметрами для тестов.
    Возвращает node_proto_id и список spec_key_ids.
    """
    tmp_id = proto_template_seed["tmp_id"]
    
    async with db_pool.acquire() as conn:
        # Создаём физическую ноду
        node_id = await conn.fetchval(
            "INSERT INTO nodes (ip, api_port, node_name, title) VALUES ($1, $2, $3, $4) RETURNING id",
            "192.168.1.100",
            8080,
            "test_node_spec",
            "Test Node for Spec"
        )
        
        # Создаём протокол
        proto_id = await conn.fetchval(
            "INSERT INTO protocols (name, tmp_id) VALUES ($1, $2) RETURNING id",
            "SpecProtocol",
            tmp_id
        )
        
        # Создаём виртуальную ноду
        node_proto_id = await conn.fetchval(
            "INSERT INTO nodes_protocols (node_id, proto_id, title) VALUES ($1, $2, $3) RETURNING id",
            node_id,
            proto_id,
            "Virtual Node for Spec"
        )
        
        # Создаём spec ключи для шаблона
        spec_key_ids = []
        keys = ["flow", "security", "encryption"]
        for key in keys:
            spec_key_id = await conn.fetchval(
                "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
                tmp_id,
                key
            )
            spec_key_ids.append(spec_key_id)
        
        # Создаём spec значения для виртуальной ноды
        values = ["xtls-rprx-vision", "tls", "none"]
        for spec_key_id, value in zip(spec_key_ids, values):
            await conn.execute(
                "INSERT INTO nodes_protocoles_spec_params_values (spec_key_id, node_proto_id, value) VALUES ($1, $2, $3)",
                spec_key_id,
                node_proto_id,
                value
            )
    
    return {
        "node_proto_id": node_proto_id,
        "spec_key_ids": spec_key_ids,
        "tmp_id": tmp_id,
        "proto_id": proto_id,
        "node_id": node_id
    }


# ==================== GET /private/specs/vnode/get_spec_values ====================

@pytest.mark.asyncio
async def test_get_spec_values_empty(client: AsyncClient, proto_template_seed, db_pool):
    """Получение пустого списка spec значений для виртуальной ноды без параметров"""
    async with db_pool.acquire() as conn:
        # Создаём виртуальную ноду без spec параметров
        node_id = await conn.fetchval(
            "INSERT INTO nodes (ip, api_port, node_name, title) VALUES ($1, $2, $3, $4) RETURNING id",
            "192.168.1.1",
            8080,
            "empty_node",
            "Empty Node"
        )
        
        proto_id = await conn.fetchval(
            "INSERT INTO protocols (name, tmp_id) VALUES ($1, $2) RETURNING id",
            "EmptyProto",
            proto_template_seed["tmp_id"]
        )
        
        node_proto_id = await conn.fetchval(
            "INSERT INTO nodes_protocols (node_id, proto_id, title) VALUES ($1, $2, $3) RETURNING id",
            node_id,
            proto_id,
            "Empty Virtual Node"
        )
    
    response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert "spec_params" in data
    assert data["spec_params"] == []


@pytest.mark.asyncio
async def test_get_spec_values_multiple(client: AsyncClient, vnode_with_spec_seed):
    """Получение нескольких spec значений для виртуальной ноды"""
    node_proto_id = vnode_with_spec_seed["node_proto_id"]
    
    response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert "spec_params" in data
    assert len(data["spec_params"]) == 3
    
    # Проверяем структуру данных
    first_param = data["spec_params"][0]
    assert "tmp_id" in first_param
    assert "spec_key_id" in first_param
    assert "key_name" in first_param
    assert "value_id" in first_param
    assert "value" in first_param
    
    # Проверяем значения
    key_names = {param["key_name"] for param in data["spec_params"]}
    assert key_names == {"flow", "security", "encryption"}
    
    values = {param["value"] for param in data["spec_params"]}
    assert values == {"xtls-rprx-vision", "tls", "none"}


@pytest.mark.asyncio
async def test_get_spec_values_nonexistent_vnode(client: AsyncClient, db_seed):
    """Несуществующий node_proto_id возвращает пустой результат"""
    response = await client.get("/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id=9999")
    
    assert response.status_code == 200
    data = response.json()
    assert data["spec_params"] == []


# ==================== PUT /private/specs/set_keys ====================

@pytest.mark.asyncio
async def test_set_keys_add_success(client: AsyncClient, proto_template_seed):
    """Успешное добавление новых spec ключей"""
    tmp_id = proto_template_seed["tmp_id"]
    
    response = await client.put(
        "/api/v1/private/templates/specs/set_keys",
        json={
            "tmp_id": tmp_id,
            "add_keys": [
                {"key_id": 0, "key_name": "headerType"},
                {"key_id": 0, "key_name": "serviceName"}
            ],
            "update_keys": [],
            "del_keys": []
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "add" in data
    assert data["add"]["success"] is True
    assert "Новые ключи успешно добавлены" in data["add"]["message"]
    assert len(data["add"]["add_ids"]) == 2


@pytest.mark.asyncio
async def test_set_keys_update_success(client: AsyncClient, vnode_with_spec_seed):
    """Успешное обновление существующих spec ключей"""
    tmp_id = vnode_with_spec_seed["tmp_id"]
    spec_key_ids = vnode_with_spec_seed["spec_key_ids"]
    
    response = await client.put(
        "/api/v1/private/templates/specs/set_keys",
        json={
            "tmp_id": tmp_id,
            "add_keys": [],
            "update_keys": [
                {"key_id": spec_key_ids[0], "key_name": "flow_updated"},
                {"key_id": spec_key_ids[1], "key_name": "security_updated"}
            ],
            "del_keys": []
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "update" in data
    assert data["update"]["success"] is True
    assert "Названия ключей обновлены" in data["update"]["message"]


@pytest.mark.asyncio
async def test_set_keys_delete_success(client: AsyncClient, proto_template_seed, db_pool):
    """Успешное удаление spec ключей (без значений)"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Создаём ключи для удаления (без связанных значений)
    async with db_pool.acquire() as conn:
        key1_id = await conn.fetchval(
            "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
            tmp_id,
            "temp_key1"
        )
        key2_id = await conn.fetchval(
            "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
            tmp_id,
            "temp_key2"
        )
    
    response = await client.put(
        "/api/v1/private/templates/specs/set_keys",
        json={
            "tmp_id": tmp_id,
            "add_keys": [],
            "update_keys": [],
            "del_keys": [key1_id, key2_id]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "delete" in data
    assert data["delete"]["success"] is True
    assert "Ключи успешно удалены" in data["delete"]["message"]


@pytest.mark.asyncio
async def test_set_keys_combined_operations(client: AsyncClient, vnode_with_spec_seed, db_pool):
    """Комбинированная операция: add + update + delete"""
    tmp_id = vnode_with_spec_seed["tmp_id"]
    spec_key_ids = vnode_with_spec_seed["spec_key_ids"]
    
    # Создаём ключ для удаления (без значений)
    async with db_pool.acquire() as conn:
        delete_key_id = await conn.fetchval(
            "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
            tmp_id,
            "to_delete"
        )
    
    response = await client.put(
        "/api/v1/private/templates/specs/set_keys",
        json={
            "tmp_id": tmp_id,
            "add_keys": [
                {"key_id": 0, "key_name": "new_key"}
            ],
            "update_keys": [
                {"key_id": spec_key_ids[0], "key_name": "flow_modified"}
            ],
            "del_keys": [delete_key_id]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["add"]["success"] is True
    assert data["update"]["success"] is True
    assert data["delete"]["success"] is True


@pytest.mark.asyncio
async def test_set_keys_duplicate_conflict(client: AsyncClient, vnode_with_spec_seed):
    """Попытка добавить дубликат ключа (ON CONFLICT DO NOTHING)"""
    tmp_id = vnode_with_spec_seed["tmp_id"]
    
    # Пытаемся добавить ключ, который уже существует
    response = await client.put(
        "/api/v1/private/templates/specs/set_keys",
        json={
            "tmp_id": tmp_id,
            "add_keys": [
                {"key_id": 0, "key_name": "flow"}  # Уже существует
            ],
            "update_keys": [],
            "del_keys": []
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "add" in data
    # ON CONFLICT DO NOTHING → не вставится, add_ids будет пустым
    assert data["add"]["success"] is False
    assert len(data["add"]["add_ids"]) == 0


# ==================== PUT /private/specs/vnode/set_key_values ====================

@pytest.mark.asyncio
async def test_set_key_values_insert(client: AsyncClient, proto_template_seed, db_pool):
    """Установка значений для новых spec параметров (INSERT) с проверкой возвращаемых ID"""
    tmp_id = proto_template_seed["tmp_id"]
    
    async with db_pool.acquire() as conn:
        # Создаём виртуальную ноду
        node_id = await conn.fetchval(
            "INSERT INTO nodes (ip, api_port, node_name, title) VALUES ($1, $2, $3, $4) RETURNING id",
            "192.168.1.50",
            8080,
            "insert_node",
            "Insert Node"
        )
        
        proto_id = await conn.fetchval(
            "INSERT INTO protocols (name, tmp_id) VALUES ($1, $2) RETURNING id",
            "InsertProto",
            tmp_id
        )
        
        node_proto_id = await conn.fetchval(
            "INSERT INTO nodes_protocols (node_id, proto_id, title) VALUES ($1, $2, $3) RETURNING id",
            node_id,
            proto_id,
            "Insert Virtual Node"
        )
        
        # Создаём spec ключи
        key1_id = await conn.fetchval(
            "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
            tmp_id,
            "alpn"
        )
        key2_id = await conn.fetchval(
            "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
            tmp_id,
            "fingerprint"
        )
    
    # Устанавливаем значения
    response = await client.put(
        "/api/v1/private/templates/specs/vnode/set_key_values",
        json={
            "node_proto_id": node_proto_id,
            "spec_param_values": [
                {"spec_key_id": key1_id, "value": "h2,http/1.1"},
                {"spec_key_id": key2_id, "value": "chrome"}
            ]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Specs успешно заданы"
    
    # Проверяем возвращаемые spec_value_ids
    assert "spec_value_ids" in data
    assert len(data["spec_value_ids"]) == 2
    
    # Проверяем структуру возвращаемых данных
    for spec_value in data["spec_value_ids"]:
        assert "value_id" in spec_value
        assert "spec_key_id" in spec_value
        assert spec_value["value_id"] is not None
        assert spec_value["spec_key_id"] in [key1_id, key2_id]
    
    # Проверяем, что значения действительно вставились
    get_response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    spec_values = get_response.json()["spec_params"]
    assert len(spec_values) == 2


@pytest.mark.asyncio
async def test_set_key_values_upsert(client: AsyncClient, vnode_with_spec_seed):
    """Обновление существующих значений (UPSERT) с проверкой возвращаемых ID"""
    node_proto_id = vnode_with_spec_seed["node_proto_id"]
    spec_key_ids = vnode_with_spec_seed["spec_key_ids"]
    
    # Обновляем существующие значения
    response = await client.put(
        "/api/v1/private/templates/specs/vnode/set_key_values",
        json={
            "node_proto_id": node_proto_id,
            "spec_param_values": [
                {"spec_key_id": spec_key_ids[0], "value": "xtls-rprx-direct"},  # Обновление
                {"spec_key_id": spec_key_ids[1], "value": "reality"},  # Обновление
                {"spec_key_id": spec_key_ids[2], "value": "aes-128-gcm"}  # Обновление
            ]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем возвращаемые spec_value_ids
    assert "spec_value_ids" in data
    assert len(data["spec_value_ids"]) == 3
    
    # Сохраняем возвращённые value_id для дальнейшей проверки
    returned_value_ids = {item["spec_key_id"]: item["value_id"] for item in data["spec_value_ids"]}
    
    # Проверяем, что все spec_key_id присутствуют
    for spec_key_id in spec_key_ids:
        assert spec_key_id in returned_value_ids
        assert returned_value_ids[spec_key_id] is not None
    
    # Проверяем, что значения действительно обновились
    get_response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    spec_values = get_response.json()["spec_params"]
    
    values_dict = {param["key_name"]: param["value"] for param in spec_values}
    assert values_dict["flow"] == "xtls-rprx-direct"
    assert values_dict["security"] == "reality"
    assert values_dict["encryption"] == "aes-128-gcm"
    
    # Проверяем соответствие value_id из ответа UPSERT с value_id из GET
    value_ids_from_get = {param["spec_key_id"]: param["value_id"] for param in spec_values}
    assert returned_value_ids == value_ids_from_get


@pytest.mark.asyncio
async def test_set_key_values_delete_all(client: AsyncClient, vnode_with_spec_seed):
    """Удаление всех значений (передача пустого списка) - возвращает пустой spec_value_ids"""
    node_proto_id = vnode_with_spec_seed["node_proto_id"]
    
    # Проверяем, что изначально есть значения
    get_response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    assert len(get_response.json()["spec_params"]) == 3
    
    # Передаём пустой список → удаляем всё
    response = await client.put(
        "/api/v1/private/templates/specs/vnode/set_key_values",
        json={
            "node_proto_id": node_proto_id,
            "spec_param_values": []
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем, что spec_value_ids пуст (т.к. не было UPSERT)
    assert "spec_value_ids" in data
    assert data["spec_value_ids"] == []
    
    # Проверяем, что все значения удалены
    get_response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    assert get_response.json()["spec_params"] == []


@pytest.mark.asyncio
async def test_set_key_values_partial_update(client: AsyncClient, vnode_with_spec_seed):
    """Частичное обновление с проверкой возвращаемых ID (удаление неуказанных ключей)"""
    node_proto_id = vnode_with_spec_seed["node_proto_id"]
    spec_key_ids = vnode_with_spec_seed["spec_key_ids"]
    
    # Проверяем, что изначально 3 значения
    get_response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    assert len(get_response.json()["spec_params"]) == 3
    
    # Обновляем только 2 параметра (третий должен удалиться)
    response = await client.put(
        "/api/v1/private/templates/specs/vnode/set_key_values",
        json={
            "node_proto_id": node_proto_id,
            "spec_param_values": [
                {"spec_key_id": spec_key_ids[0], "value": "new_flow"},
                {"spec_key_id": spec_key_ids[1], "value": "new_security"}
                # spec_key_ids[2] не указан → должен удалиться
            ]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем возвращаемые spec_value_ids (только 2 значения)
    assert "spec_value_ids" in data
    assert len(data["spec_value_ids"]) == 2
    
    # Проверяем, что возвращены правильные spec_key_id
    returned_spec_key_ids = {item["spec_key_id"] for item in data["spec_value_ids"]}
    assert returned_spec_key_ids == {spec_key_ids[0], spec_key_ids[1]}
    assert spec_key_ids[2] not in returned_spec_key_ids
    
    # Проверяем, что остались только 2 значения
    get_response = await client.get(f"/api/v1/private/templates/specs/vnode/get_spec_values?node_proto_id={node_proto_id}")
    spec_values = get_response.json()["spec_params"]
    assert len(spec_values) == 2
    
    # Проверяем, что удалился правильный ключ
    key_names = {param["key_name"] for param in spec_values}
    assert key_names == {"flow", "security"}
    assert "encryption" not in key_names
