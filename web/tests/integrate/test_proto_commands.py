"""
E2E тесты для эндпоинтов работы с командами протоколов (/private/protocol-commands).
Тестирует CRUD операции для команд протоколов (bulk операции).
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def protocol_with_commands_seed(client: AsyncClient, db_seed, proto_template_seed, db_pool):
    """
    Создаёт протокол и добавляет к нему несколько команд для тестов.
    Возвращает proto_id и список cmd_ids.
    """
    # Создаём протокол
    response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "TestProtocol", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = response.json()["proto_id"]
    
    # Создаём команды напрямую через БД
    async with db_pool.acquire() as conn:
        cmd_ids = []
        commands_data = [
            {"cmd_title": "add_user", "command": "xray add user --name {username}"},
            {"cmd_title": "delete_user", "command": "xray delete user --id {user_id}"},
            {"cmd_title": "restart_service", "command": "systemctl restart xray"},
        ]
        
        for cmd in commands_data:
            cmd_id = await conn.fetchval(
                """
                INSERT INTO protocols_commands (proto_id, cmd_title, command)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                proto_id,
                cmd["cmd_title"],
                cmd["command"]
            )
            cmd_ids.append(cmd_id)
    
    return {"proto_id": proto_id, "cmd_ids": cmd_ids}


# ==================== GET /protocol-commands/by_proto/{proto_id} ====================

@pytest.mark.asyncio
async def test_get_protocol_commands_empty(client: AsyncClient, db_seed, proto_template_seed):
    """Получение пустого списка команд для протокола"""
    # Создаём протокол без команд
    response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "EmptyProtocol", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = response.json()["proto_id"]
    
    # Получаем команды
    response = await client.get(f"/api/v1/private/protocol-commands/by_proto/{proto_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert data["commands"] == []


@pytest.mark.asyncio
async def test_get_protocol_commands_multiple(client: AsyncClient, protocol_with_commands_seed):
    """Получение списка с несколькими командами"""
    proto_id = protocol_with_commands_seed["proto_id"]
    
    response = await client.get(f"/api/v1/private/protocol-commands/by_proto/{proto_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert len(data["commands"]) == 3
    
    # Проверяем структуру данных
    first_cmd = data["commands"][0]
    assert "cmd_id" in first_cmd
    assert "title" in first_cmd
    assert "command" in first_cmd
    assert "created_at" in first_cmd


# ==================== POST /protocol-commands/bulk/insert ====================

@pytest.mark.asyncio
async def test_bulk_insert_commands_success(client: AsyncClient, db_seed, proto_template_seed):
    """Успешная массовая вставка нескольких команд"""
    # Создаём протокол
    response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "BulkInsertProto", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = response.json()["proto_id"]
    
    # Вставляем команды
    commands = [
        {"cmd_title": "start", "command": "systemctl start service"},
        {"cmd_title": "stop", "command": "systemctl stop service"},
        {"cmd_title": "status", "command": "systemctl status service"},
    ]
    
    response = await client.post(
        "/api/v1/private/protocol-commands/bulk/insert",
        json={"proto_id": proto_id, "commands": commands}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "cmd_ids" in data
    assert len(data["cmd_ids"]) == 3
    assert "Вставлено команд: 3" in data["message"]


@pytest.mark.asyncio
async def test_bulk_insert_single_command(client: AsyncClient, db_seed, proto_template_seed):
    """Вставка одной команды через bulk insert"""
    # Создаём протокол
    response = await client.post(
        "/api/v1/private/protocols/create",
        json={"name": "SingleCmdProto", "tmp_id": proto_template_seed["tmp_id"]}
    )
    proto_id = response.json()["proto_id"]
    
    # Вставляем одну команду
    commands = [
        {"cmd_title": "reload", "command": "systemctl reload service"},
    ]
    
    response = await client.post(
        "/api/v1/private/protocol-commands/bulk/insert",
        json={"proto_id": proto_id, "commands": commands}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["cmd_ids"]) == 1


@pytest.mark.asyncio
async def test_bulk_insert_invalid_proto_id(client: AsyncClient, db_seed):
    """Вставка команд с несуществующим proto_id возвращает 404"""
    commands = [
        {"cmd_title": "test", "command": "test command"},
    ]
    
    # Используем несуществующий proto_id (в пределах smallint)
    response = await client.post(
        "/api/v1/private/protocol-commands/bulk/insert",
        json={"proto_id": 9999, "commands": commands}
    )
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["message"] == "Протокол не найден"


# ==================== PUT /protocol-commands/bulk/update ====================

@pytest.mark.asyncio
async def test_bulk_update_commands_success(client: AsyncClient, protocol_with_commands_seed):
    """Успешное массовое обновление команд"""
    proto_id = protocol_with_commands_seed["proto_id"]
    cmd_ids = protocol_with_commands_seed["cmd_ids"]
    
    # Обновляем все команды
    commands = [
        {"id": cmd_ids[0], "cmd_title": "add_user_updated", "command": "NEW: xray add user"},
        {"id": cmd_ids[1], "cmd_title": "delete_user_updated", "command": "NEW: xray delete user"},
        {"id": cmd_ids[2], "cmd_title": "restart_updated", "command": "NEW: systemctl restart"},
    ]
    
    response = await client.put(
        "/api/v1/private/protocol-commands/bulk/update",
        json={"proto_id": proto_id, "commands": commands}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # API возвращает список ID обновлённых команд
    assert isinstance(data["updated_count"], list)
    assert len(data["updated_count"]) == 3
    assert "Обновлено команд: 3" in data["message"]
    
    # Проверяем, что команды действительно обновились
    get_response = await client.get(f"/api/v1/private/protocol-commands/by_proto/{proto_id}")
    commands_list = get_response.json()["commands"]
    
    # Проверяем первую обновлённую команду
    updated_cmd = next(cmd for cmd in commands_list if cmd["cmd_id"] == cmd_ids[0])
    assert updated_cmd["title"] == "add_user_updated"
    assert "NEW: xray add user" in updated_cmd["command"]


@pytest.mark.asyncio
async def test_bulk_update_partial(client: AsyncClient, protocol_with_commands_seed):
    """Обновление части команд (некоторые ID не существуют или принадлежат другому протоколу)"""
    proto_id = protocol_with_commands_seed["proto_id"]
    cmd_ids = protocol_with_commands_seed["cmd_ids"]
    
    # Пытаемся обновить существующие и несуществующие команды
    commands = [
        {"id": cmd_ids[0], "cmd_title": "valid_update", "command": "valid command"},
        {"id": 999999, "cmd_title": "invalid_update", "command": "should not update"},
    ]
    
    response = await client.put(
        "/api/v1/private/protocol-commands/bulk/update",
        json={"proto_id": proto_id, "commands": commands}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Должна обновиться только одна команда (существующая)
    assert isinstance(data["updated_count"], list)
    assert len(data["updated_count"]) == 1


# ==================== DELETE /protocol-commands/bulk/delete ====================

@pytest.mark.asyncio
async def test_bulk_delete_commands_success(client: AsyncClient, protocol_with_commands_seed):
    """Успешное массовое удаление команд"""
    proto_id = protocol_with_commands_seed["proto_id"]
    cmd_ids = protocol_with_commands_seed["cmd_ids"]
    
    # Удаляем две команды (httpx.delete() не поддерживает json, используем request())
    response = await client.request(
        "DELETE",
        "/api/v1/private/protocol-commands/bulk/delete",
        json={"proto_id": proto_id, "cmd_ids": [cmd_ids[0], cmd_ids[1]]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted_count"] == 2
    assert "Удалено команд: 2" in data["message"]
    
    # Проверяем, что команды удалены
    get_response = await client.get(f"/api/v1/private/protocol-commands/by_proto/{proto_id}")
    remaining_commands = get_response.json()["commands"]
    assert len(remaining_commands) == 1
    assert remaining_commands[0]["cmd_id"] == cmd_ids[2]


@pytest.mark.asyncio
async def test_bulk_delete_partial(client: AsyncClient, protocol_with_commands_seed):
    """Удаление с несуществующими ID (частичное удаление)"""
    proto_id = protocol_with_commands_seed["proto_id"]
    cmd_ids = protocol_with_commands_seed["cmd_ids"]
    
    # Пытаемся удалить существующую и несуществующую команду
    response = await client.request(
        "DELETE",
        "/api/v1/private/protocol-commands/bulk/delete",
        json={"proto_id": proto_id, "cmd_ids": [cmd_ids[0], 999999]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Должна удалиться только одна команда (существующая)
    assert data["deleted_count"] == 1
    
    # Проверяем, что удалилась только одна команда
    get_response = await client.get(f"/api/v1/private/protocol-commands/by_proto/{proto_id}")
    remaining_commands = get_response.json()["commands"]
    assert len(remaining_commands) == 2
