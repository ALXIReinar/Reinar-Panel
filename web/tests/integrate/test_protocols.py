"""
E2E тесты для эндпоинтов работы с протоколами (/private/protocols).
Тестирует CRUD операции для популярных VPN протоколов.
"""
import pytest
from httpx import AsyncClient


# ==================== POST /private/protocols/create ====================

@pytest.mark.asyncio
async def test_create_protocol_success(client: AsyncClient, db_seed, proto_template_seed):
    """Успешное создание протокола"""
    response = await client.post(
        "/api/v1/private/protocols/create",
        json={
            "name": "WireGuard",
            "tmp_id": proto_template_seed["tmp_id"]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "proto_id" in data
    assert data["proto_id"] is not None
    assert data["message"] == "Протокол создан"


@pytest.mark.asyncio
async def test_create_protocol_duplicate(client: AsyncClient, db_seed, proto_template_seed):
    """Попытка создать дубликат протокола (409 Conflict)"""
    # Создаём протокол первый раз
    await client.post(
        "/api/v1/private/protocols/create",
        json={
            "name": "OpenVPN",
            "tmp_id": proto_template_seed["tmp_id"]
        }
    )
    
    # Пытаемся создать дубликат
    response = await client.post(
        "/api/v1/private/protocols/create",
        json={
            "name": "OpenVPN",
            "tmp_id": proto_template_seed["tmp_id"]
        }
    )
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["success"] is False
    assert "уже существует" in data["detail"]["message"]


# ==================== GET /private/protocols/all ====================

@pytest.mark.asyncio
async def test_get_all_protocols_empty(client: AsyncClient, db_seed, proto_template_seed):
    """Получение пустого списка протоколов"""
    response = await client.get("/api/v1/private/protocols/all")
    
    assert response.status_code == 200
    data = response.json()
    assert "protocols" in data
    assert data["protocols"] == []


@pytest.mark.asyncio
async def test_get_all_protocols_multiple(client: AsyncClient, db_seed, proto_template_seed):
    """Получение списка с несколькими протоколами"""
    # Создаём несколько протоколов
    protocols_data = [
        {"name": "WireGuard", "tmp_id": proto_template_seed["tmp_id"]},
        {"name": "OpenVPN", "tmp_id": proto_template_seed["tmp_id"]},
        {"name": "Shadowsocks", "tmp_id": proto_template_seed["tmp_id_2"]},
    ]
    
    for proto in protocols_data:
        await client.post("/api/v1/private/protocols/create", json=proto)
    
    # Получаем все протоколы
    response = await client.get("/api/v1/private/protocols/all")
    
    assert response.status_code == 200
    data = response.json()
    assert "protocols" in data
    assert len(data["protocols"]) == 3
    
    # Проверяем структуру данных
    first_proto = data["protocols"][0]
    assert "proto_id" in first_proto
    assert "name" in first_proto
    assert "created_at" in first_proto
    assert "tmp_id" in first_proto
    assert "tmp_name" in first_proto  # JOIN с proto_templates


@pytest.mark.asyncio
async def test_get_all_protocols_pagination(client: AsyncClient, db_seed, proto_template_seed):
    """Проверка пагинации (offset/limit)"""
    # Создаём 5 протоколов
    for i in range(5):
        await client.post(
            "/api/v1/private/protocols/create",
            json={"name": f"Protocol_{i}", "tmp_id": proto_template_seed["tmp_id"]}
        )
    
    # Запрос с limit=2, offset=0
    response = await client.get("/api/v1/private/protocols/all?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["protocols"]) == 2
    
    # Запрос с limit=2, offset=2
    response = await client.get("/api/v1/private/protocols/all?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["protocols"]) == 2
    
    # Запрос с limit=2, offset=4 (последний протокол)
    response = await client.get("/api/v1/private/protocols/all?limit=2&offset=4")
    assert response.status_code == 200
    data = response.json()
    assert len(data["protocols"]) == 1


@pytest.mark.asyncio
async def test_get_all_protocols_limit_boundary(client: AsyncClient, db_seed, proto_template_seed):
    """Граничный случай: limit=15 (максимум)"""
    # Создаём 20 протоколов
    for i in range(20):
        await client.post(
            "/api/v1/private/protocols/create",
            json={"name": f"Proto_{i:02d}", "tmp_id": proto_template_seed["tmp_id"]}
        )
    
    # Запрос с максимальным limit
    response = await client.get("/api/v1/private/protocols/all?limit=15&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["protocols"]) == 15


@pytest.mark.asyncio
async def test_get_all_protocols_limit_exceeded(client: AsyncClient, db_seed, proto_template_seed):
    """limit > 15 вызывает ошибку валидации (422)"""
    response = await client.get("/api/v1/private/protocols/all?limit=16&offset=0")
    
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_get_all_protocols_filter_by_tmp_id(client: AsyncClient, db_seed, proto_template_seed):
    """Фильтрация протоколов по tmp_id (шаблону) - несколько протоколов с одним шаблоном"""
    tmp_id_1 = proto_template_seed["tmp_id"]
    tmp_id_2 = proto_template_seed["tmp_id_2"]
    
    # Создаём 3 протокола: 2 с шаблоном1, 1 с шаблоном2
    proto1_resp = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "Protocol_A", "tmp_id": tmp_id_1}
    )
    proto1_id = proto1_resp.json()["proto_id"]
    
    proto2_resp = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "Protocol_B", "tmp_id": tmp_id_1}
    )
    proto2_id = proto2_resp.json()["proto_id"]
    
    proto3_resp = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "Protocol_C", "tmp_id": tmp_id_2}
    )
    proto3_id = proto3_resp.json()["proto_id"]
    
    # Фильтруем по tmp_id_1 (должны вернуться 2 протокола)
    response = await client.get(f"/api/v1/private/protocols/all?tmp_id={tmp_id_1}")
    assert response.status_code == 200
    data = response.json()
    assert "protocols" in data
    assert len(data["protocols"]) == 2
    
    # Проверяем, что вернулись правильные протоколы
    returned_proto_ids = {proto["proto_id"] for proto in data["protocols"]}
    assert returned_proto_ids == {proto1_id, proto2_id}
    
    # Проверяем, что все протоколы используют tmp_id_1
    for proto in data["protocols"]:
        assert proto["tmp_id"] == tmp_id_1
    
    # Фильтруем по tmp_id_2 (должен вернуться 1 протокол)
    response = await client.get(f"/api/v1/private/protocols/all?tmp_id={tmp_id_2}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["protocols"]) == 1
    assert data["protocols"][0]["proto_id"] == proto3_id
    assert data["protocols"][0]["tmp_id"] == tmp_id_2


# ==================== GET /private/protocols/{proto_id} ====================

@pytest.mark.asyncio
async def test_get_protocol_success(client: AsyncClient, db_seed, proto_template_seed):
    """Успешное получение конкретного протокола"""
    # Создаём протокол
    create_response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "WireGuard", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = create_response.json()["proto_id"]
    
    # Получаем протокол по ID
    response = await client.get(f"/api/v1/private/protocols/{proto_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert "proto_info" in data
    proto_info = data["proto_info"]
    assert proto_info["proto_id"] == proto_id
    assert proto_info["name"] == "WireGuard"


@pytest.mark.asyncio
async def test_get_protocol_with_template_info(client: AsyncClient, db_seed, proto_template_seed):
    """Проверка JOIN с proto_templates (url_tmp, sub_prepare_script)"""
    # Создаём протокол
    create_response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "TestProto", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = create_response.json()["proto_id"]
    
    # Получаем протокол с информацией о шаблоне
    response = await client.get(f"/api/v1/private/protocols/{proto_id}")
    
    assert response.status_code == 200
    proto_info = response.json()["proto_info"]
    
    # Проверяем данные из proto_templates
    assert "url_tmp" in proto_info
    assert proto_info["url_tmp"] == "https://example.com/proto_template"
    assert "sub_prepare_script" in proto_info
    assert "echo 'test'" in proto_info["sub_prepare_script"]


@pytest.mark.asyncio
async def test_get_protocol_not_found(client: AsyncClient, db_seed, proto_template_seed):
    """Несуществующий proto_id возвращает 404"""
    # Используем ID в пределах smallint (< 32767)
    response = await client.get("/api/v1/private/protocols/9999")
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["message"] == "Протокол не найден"


# ==================== DELETE /private/protocols/delete/{proto_id} ====================

@pytest.mark.asyncio
async def test_delete_protocol_success(client: AsyncClient, db_seed, proto_template_seed):
    """Успешное удаление протокола"""
    # Создаём протокол
    create_response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "ToDelete", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = create_response.json()["proto_id"]
    
    # Удаляем протокол
    response = await client.delete(f"/api/v1/private/protocols/delete/{proto_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Протокол удалён"
    
    # Проверяем, что протокол действительно удалён
    get_response = await client.get(f"/api/v1/private/protocols/{proto_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_protocol_with_nodes(client: AsyncClient, db_seed, proto_template_seed, db_pool):
    """Удаление протокола, используемого нодами (409 Conflict)"""
    # Создаём протокол
    create_response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "UsedProto", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = create_response.json()["proto_id"]
    
    # Создаём ноду, использующую этот протокол
    async with db_pool.acquire() as conn:
        # Сначала создаём физическую ноду
        node_id = await conn.fetchval(
            """
            INSERT INTO nodes (ip, api_port, node_name, title)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "192.168.1.1",
            8080,
            "test_node_1",
            "Test Node"
        )
        
        # Затем создаём виртуальную ноду (связь с протоколом)
        await conn.execute(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title)
            VALUES ($1, $2, $3)
            """,
            node_id,
            proto_id,
            "Test Virtual Node"
        )
    
    # Пытаемся удалить протокол, который используется
    response = await client.delete(f"/api/v1/private/protocols/delete/{proto_id}")
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["success"] is False
    assert "не может быть удалён" in data["detail"]["message"]
    assert "ноды используют" in data["detail"]["message"]
