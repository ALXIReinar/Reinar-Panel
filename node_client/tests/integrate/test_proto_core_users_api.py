"""
Интеграционные тесты для API proto_core/user/bulk/action

Тестируем:
- HTTP endpoint /user/bulk/action
- Тонкий payload (node_proto_id, users, action, core_port, custom_params)
- Обратную совместимость (extra="ignore" для старых полей)
- Валидацию Pydantic схем и конвертацию action ("add", "delete", 1, 2)
- Взаимодействие с ConfigWriteBuffer
- Hot-reload через api_bulk_add_user_script / api_bulk_delete_user_script
- Ответ 428 при незарегистрированной ноде
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from node_client.api import main_router
from node_client.exceptions import NodeNotRegisteredError
from node_client.main import node_not_registered_handler
from node_client.tests.utils.test_data_factory import create_test_user

# ========== Fixtures ==========


@pytest.fixture
def mock_buffer():
    """Мокированный ConfigWriteBuffer"""
    buffer_mock = AsyncMock()
    buffer_mock.bulk_action = AsyncMock(return_value=(True, "Действие выполнено"))
    buffer_mock.get_metadata = MagicMock(
        return_value={
            'api_bulk_add_user_script': None,
            'api_bulk_delete_user_script': None,
            'reload_command': None,
        }
    )
    return buffer_mock


@pytest.fixture
async def client(mock_buffer):
    """HTTP клиент для тестирования API"""
    app = FastAPI()
    app.include_router(main_router)
    app.add_exception_handler(NodeNotRegisteredError, node_not_registered_handler)

    def get_mock_buffer():
        return mock_buffer

    from node_client.api.proto_core.write_behind_caching_file import get_proto_cores_buffer

    app.dependency_overrides[get_proto_cores_buffer] = get_mock_buffer

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def create_bulk_action_payload(**overrides):
    """Создаёт валидный тонкий payload для /user/bulk/action"""
    payload = {
        "node_proto_id": 1,
        "users": [create_test_user(email="test@test.com")],
        "core_port": None,
        "custom_params": None,
        "action": "add",
    }
    payload.update(overrides)
    return payload


# ========== Тесты для параметра action ==========


@pytest.mark.asyncio
async def test_action_as_string_add(client, mock_buffer):
    """Тест: action='add' (строка)"""
    payload = create_bulk_action_payload(action="add")
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    mock_buffer.bulk_action.assert_called_once()
    assert mock_buffer.bulk_action.call_args.kwargs["action"] == "add"


@pytest.mark.asyncio
async def test_action_as_string_delete(client, mock_buffer):
    """Тест: action='delete' (строка)"""
    payload = create_bulk_action_payload(action="delete")
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    mock_buffer.bulk_action.assert_called_once()
    assert mock_buffer.bulk_action.call_args.kwargs["action"] == "delete"


@pytest.mark.asyncio
async def test_action_as_int_1_converts_to_add(client, mock_buffer):
    """Тест: action=1 (число) конвертируется в 'add'"""
    payload = create_bulk_action_payload(action=1)
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    assert mock_buffer.bulk_action.call_args.kwargs["action"] == "add"


@pytest.mark.asyncio
async def test_action_as_int_2_converts_to_delete(client, mock_buffer):
    """Тест: action=2 (число) конвертируется в 'delete'"""
    payload = create_bulk_action_payload(action=2)
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    assert mock_buffer.bulk_action.call_args.kwargs["action"] == "delete"


# ========== Тесты hot-reload логики ==========


@pytest.mark.asyncio
async def test_bulk_action_with_hot_reload_add(client, mock_buffer):
    """Тест: Добавление с hot-reload через скомпилированную функцию из метаданных"""
    mock_hot_reload_func = AsyncMock(return_value="Hot-reload успешен")
    mock_buffer.get_metadata.return_value = {
        'api_bulk_add_user_script': mock_hot_reload_func,
        'api_bulk_delete_user_script': None,
    }

    payload = create_bulk_action_payload(
        action="add",
        core_port=10086,
        custom_params={"tag": "vpn"},
    )
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is True
    assert data["hot_reload_message"] == "Hot-reload успешен"
    mock_hot_reload_func.assert_called_once_with(payload["users"], "127.0.0.1", 10086, {"tag": "vpn"})


@pytest.mark.asyncio
async def test_bulk_action_with_hot_reload_delete(client, mock_buffer):
    """Тест: Удаление с hot-reload"""
    mock_delete_func = AsyncMock(return_value="Hot-reload delete ok")
    mock_buffer.get_metadata.return_value = {
        'api_bulk_add_user_script': None,
        'api_bulk_delete_user_script': mock_delete_func,
    }

    payload = create_bulk_action_payload(action="delete", core_port=10086)
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["hot_reload"] is True
    mock_delete_func.assert_called_once()


@pytest.mark.asyncio
async def test_hot_reload_fails_continues_with_file(client, mock_buffer):
    """Тест: Ошибка при hot-reload не блокирует добавление в буфер"""
    mock_failing_func = AsyncMock(side_effect=RuntimeError("gRPC connection refused"))
    mock_buffer.get_metadata.return_value = {
        'api_bulk_add_user_script': mock_failing_func,
        'api_bulk_delete_user_script': None,
    }

    payload = create_bulk_action_payload(core_port=10086)
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is False
    assert "gRPC connection refused" in data["hot_reload_message"]
    mock_buffer.bulk_action.assert_called_once()


# ========== Тесты количества пользователей ==========


@pytest.mark.asyncio
async def test_single_user_add(client, mock_buffer):
    """Тест: Добавление одного пользователя"""
    user = create_test_user(email="single@test.com")
    payload = create_bulk_action_payload(users=[user])
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert len(call_kwargs["users"]) == 1
    assert call_kwargs["users"][0]["email"] == "single@test.com"


@pytest.mark.asyncio
async def test_multiple_users_bulk(client, mock_buffer):
    """Тест: Массовая операция со списком пользователей"""
    users = [create_test_user(email=f"user{i}@test.com") for i in range(5)]
    payload = create_bulk_action_payload(users=users)
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert len(call_kwargs["users"]) == 5


# ========== Тесты обработки ошибок и валидации ==========


@pytest.mark.asyncio
async def test_unregistered_node_returns_428(client, mock_buffer):
    """Тест: Незарегистрированная нода возвращает 428 Precondition Required"""
    mock_buffer.get_metadata.side_effect = NodeNotRegisteredError(999)
    payload = create_bulk_action_payload(node_proto_id=999)
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 428
    data = response.json()
    assert data["success"] is False
    assert "не зарегистрирована" in data["message"]


@pytest.mark.asyncio
async def test_buffer_error_returns_500(client, mock_buffer):
    """Тест: Ошибка буфера возвращает 500"""
    mock_buffer.bulk_action = AsyncMock(return_value=(False, "Ошибка записи"))
    payload = create_bulk_action_payload()
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False
    assert "Ошибка записи" in data["detail"]["message"]


@pytest.mark.asyncio
async def test_invalid_schema_returns_422(client, mock_buffer):
    """Тест: Отсутствие обязательных полей -> 422"""
    payload = {"node_proto_id": 1}  # users отсутствует
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_action_value_returns_422(client, mock_buffer):
    """Тест: Недопустимое значение action -> 422"""
    payload = create_bulk_action_payload(action="invalid")
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extra_fields_ignored_backward_compatibility(client, mock_buffer):
    """
    Тест: Старые служебные поля (action_script, config_file_path, user_injectors и т.д.)
    игнорируются благодаря extra='ignore'
    """
    payload = create_bulk_action_payload()
    payload.update(
        {
            "config_file_path": "/var/etc/xray.json",
            "action_script": "def foo(): pass",
            "core_lib": "grpcio",
            "reload_core_command": "systemctl restart xray",
            "user_injectors": [{"flatten_array_cursor": "foo", "extractor_script": "bar"}],
            "config2json_script": None,
            "json2config_script": None,
            "conf_converter_libs": None,
        }
    )
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True
