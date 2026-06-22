"""
E2E тесты для эндпоинтов работы с протоколами (/private/protocols).
Тестирует CRUD операции для популярных VPN протоколов.
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def proto_template_seed(pg_pool, db_seed):
    """
    Создаёт тестовый шаблон протокола в БД.
    Возвращает tmp_id для использования в тестах.
    Зависит от db_seed для очистки БД перед каждым тестом.
    """
    async with pg_pool.acquire() as conn:
        # Создаём первый тестовый шаблон протокола
        tmp_id = await conn.fetchval(
            """
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted, 
                reload_core_command, sub_prepare_script
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "TestProtocol Template",
            "https://example.com/proto_template",
            1,
            True,
            "systemctl reload test-proto",
            "#!/bin/bash\necho 'test'"
        )
        
        # Создаём второй шаблон для разнообразия
        tmp_id_2 = await conn.fetchval(
            """
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted,
                reload_core_command, sub_prepare_script
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "AnotherTemplate",
            "https://example.com/another_template",
            1,
            True,
            "systemctl reload another",
            "#!/bin/bash\necho 'another'"
        )
        
        return {"tmp_id": tmp_id, "tmp_id_2": tmp_id_2}


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
async def test_delete_protocol_with_nodes(client: AsyncClient, db_seed, proto_template_seed, pg_pool):
    """Удаление протокола, используемого нодами (409 Conflict)"""
    # Создаём протокол
    create_response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "UsedProto", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = create_response.json()["proto_id"]
    
    # Создаём ноду, использующую этот протокол
    async with pg_pool.acquire() as conn:
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
