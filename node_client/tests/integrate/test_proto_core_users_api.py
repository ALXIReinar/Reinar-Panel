"""
Интеграционные тесты для API proto_core/user/bulk/action

Тестируем:
- HTTP endpoint /user/bulk/action
- Валидацию Pydantic схем
- Параметр action ("add", "delete", 1, 2)
- Взаимодействие с ConfigWriteBuffer (мокированным)
- Hot-reload логику (мокированную)
- Обработку ошибок
- Логику с количеством пользователей
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
from fastapi import FastAPI

from node_client.api import main_router
from node_client.tests.utils.test_data_factory import create_test_user, create_user_injectors


# ========== Fixtures ==========

@pytest.fixture
def mock_buffer():
    """Мокированный ConfigWriteBuffer"""
    buffer_mock = AsyncMock()
    
    # По умолчанию все операции успешны
    buffer_mock.bulk_action = AsyncMock(return_value=(True, "Действие выполнено"))
    
    return buffer_mock


@pytest.fixture
def mock_hot_reload():
    """Мокированный HotReloadExecutor"""
    with patch('node_client.api.proto_core.proto_core_users_api.HotReloadExecutor') as mock:
        # По умолчанию hot-reload успешен (AsyncMock для awaitable)
        mock.execute_action_script = AsyncMock(return_value=(True, "Hot-reload успешен"))
        yield mock


@pytest.fixture
async def client(mock_buffer):
    """HTTP клиент для тестирования API"""
    app = FastAPI()
    app.include_router(main_router)
    
    # Подменяем dependency на мокированный buffer
    def get_mock_buffer():
        return mock_buffer
    
    from node_client.api.proto_core.write_behind_caching_file import get_proto_cores_buffer
    app.dependency_overrides[get_proto_cores_buffer] = get_mock_buffer
    
    from httpx import ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def create_bulk_action_payload(**overrides):
    """Создаёт валидный payload для /user/bulk/action"""
    payload = {
        "node_proto_id": 1,
        "users": [create_test_user(email="test@test.com")],
        "config_file_path": "/path/to/config.json",
        "user_injectors": [
            {
                "flatten_array_cursor": "inbounds___0___settings___clients",
                "extractor_script": "def transform(u): return {'id': u['user_uuid'], 'email': u.get('user_sub_id', 'test@test.com')}",
                "libs": None
            }
        ],
        "reload_core_command": "systemctl reload xray",
        "core_port": None,
        "core_lib": None,
        "action_script": None,
        "custom_params": None,
        "action": "add"  # По умолчанию add
    }
    payload.update(overrides)
    return payload


# ========== Тесты для параметра action ==========

@pytest.mark.asyncio
async def test_action_as_string_add(client, mock_buffer, mock_hot_reload):
    """
    Тест: action="add" (строка)
    
    Проверяем:
    - HTTP 200
    - buffer.bulk_action вызван с action="add"
    """
    payload = create_bulk_action_payload(action="add")
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что buffer.bulk_action был вызван с action="add"
    mock_buffer.bulk_action.assert_called_once()
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert call_kwargs["action"] == "add"


@pytest.mark.asyncio
async def test_action_as_string_delete(client, mock_buffer, mock_hot_reload):
    """
    Тест: action="delete" (строка)
    
    Проверяем:
    - HTTP 200
    - buffer.bulk_action вызван с action="delete"
    """
    payload = create_bulk_action_payload(action="delete")
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что buffer.bulk_action был вызван с action="delete"
    mock_buffer.bulk_action.assert_called_once()
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert call_kwargs["action"] == "delete"


@pytest.mark.asyncio
async def test_action_as_int_1_converts_to_add(client, mock_buffer, mock_hot_reload):
    """
    Тест: action=1 (число) конвертируется в "add"
    
    Проверяем:
    - HTTP 200
    - action=1 конвертируется в "add" через validator
    - buffer.bulk_action вызван с action="add"
    """
    payload = create_bulk_action_payload(action=1)
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем конвертацию 1 -> "add"
    mock_buffer.bulk_action.assert_called_once()
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert call_kwargs["action"] == "add"


@pytest.mark.asyncio
async def test_action_as_int_2_converts_to_delete(client, mock_buffer, mock_hot_reload):
    """
    Тест: action=2 (число) конвертируется в "delete"
    
    Проверяем:
    - HTTP 200
    - action=2 конвертируется в "delete" через validator
    - buffer.bulk_action вызван с action="delete"
    """
    payload = create_bulk_action_payload(action=2)
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем конвертацию 2 -> "delete"
    mock_buffer.bulk_action.assert_called_once()
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert call_kwargs["action"] == "delete"


# ========== Тесты hot-reload логики ==========

@pytest.mark.asyncio
async def test_bulk_action_with_hot_reload_add(client, mock_buffer, mock_hot_reload):
    """
    Тест: Добавление с hot-reload (action="add")
    
    Проверяем:
    - HotReloadExecutor вызван с action="bulk_add_users"
    - Ответ содержит hot_reload=True
    """
    payload = create_bulk_action_payload(
        action="add",
        core_port=10086,
        core_lib="grpcio",
        action_script="def bulk_add_users(users, ip, port, params): return True"
    )
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is True
    assert data["hot_reload_message"] == "Hot-reload успешен"
    
    # Проверяем что hot-reload был вызван с action="bulk_add_users"
    mock_hot_reload.execute_action_script.assert_called_once()
    call_kwargs = mock_hot_reload.execute_action_script.call_args.kwargs
    assert call_kwargs["action"] == "user_core_operation"


@pytest.mark.asyncio
async def test_bulk_action_with_hot_reload_delete(client, mock_buffer, mock_hot_reload):
    """
    Тест: Удаление с hot-reload (action="delete")
    
    Проверяем:
    - HotReloadExecutor вызван с action="bulk_delete_users"
    - Ответ содержит hot_reload=True
    """
    payload = create_bulk_action_payload(
        action="delete",
        core_port=10086,
        core_lib="grpcio",
        action_script="def bulk_delete_users(users, ip, port, params): return True"
    )
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is True
    
    # Проверяем что hot-reload был вызван с action="bulk_delete_users"
    mock_hot_reload.execute_action_script.assert_called_once()
    call_kwargs = mock_hot_reload.execute_action_script.call_args.kwargs
    assert call_kwargs["action"] == "user_core_operation"


@pytest.mark.asyncio
async def test_hot_reload_fails_continues_with_file(client, mock_buffer, mock_hot_reload):
    """
    Тест: Hot-reload провалился, но файловая запись продолжается
    
    Проверяем:
    - Hot-reload вернул False
    - buffer.bulk_action всё равно вызван
    - Ответ содержит hot_reload=False
    """
    # Hot-reload провалился
    mock_hot_reload.execute_action_script = AsyncMock(return_value=(False, "Hot-reload ошибка"))
    
    payload = create_bulk_action_payload(
        core_port=10086,
        core_lib="grpcio",
        action_script="def bulk_add_users(users, ip, port, params): return False",
        reload_core_command="systemctl reload xray"
    )
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is False
    assert data["hot_reload_message"] == "Hot-reload ошибка"
    
    # Проверяем что buffer.bulk_action был вызван несмотря на провал hot-reload
    mock_buffer.bulk_action.assert_called_once()


# ========== Тесты логики с количеством пользователей ==========

@pytest.mark.asyncio
async def test_single_user_add(client, mock_buffer, mock_hot_reload):
    """
    Тест: Добавление одного пользователя
    
    Проверяем:
    - Работает с 1 пользователем
    - buffer.bulk_action вызван с правильным списком
    """
    user = create_test_user(email="single@test.com")
    payload = create_bulk_action_payload(users=[user])
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что передан список из 1 пользователя
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert len(call_kwargs["users"]) == 1
    assert call_kwargs["users"][0]["email"] == "single@test.com"


@pytest.mark.asyncio
async def test_multiple_users_bulk(client, mock_buffer, mock_hot_reload):
    """
    Тест: Массовая операция с несколькими пользователями
    
    Проверяем:
    - Работает со списком пользователей
    - buffer.bulk_action получает весь список
    """
    users = [create_test_user(email=f"user{i}@test.com") for i in range(5)]
    payload = create_bulk_action_payload(users=users)
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что передан список из 5 пользователей
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert len(call_kwargs["users"]) == 5


# ========== Тесты обработки ошибок ==========

@pytest.mark.asyncio
async def test_buffer_error_returns_500(client, mock_buffer, mock_hot_reload):
    """
    Тест: Ошибка от буфера возвращает HTTP 500
    
    Проверяем:
    - buffer.bulk_action вернул (False, error_message)
    - HTTP 500
    - Ответ содержит детали ошибки
    """
    # Буфер возвращает ошибку
    mock_buffer.bulk_action = AsyncMock(return_value=(False, "Ошибка валидации конфига"))
    
    payload = create_bulk_action_payload()
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False
    assert "message" in data["detail"]
    assert "Ошибка валидации конфига" in data["detail"]["message"]


@pytest.mark.asyncio
async def test_invalid_schema_returns_422(client, mock_buffer):
    """
    Тест: Невалидная схема возвращает HTTP 422
    
    Проверяем:
    - Отсутствует обязательное поле
    - HTTP 422
    - buffer.bulk_action НЕ вызван
    """
    payload = {
        "node_proto_id": 1,
        # users отсутствует (обязательное поле)
        "config_file_path": "/path/to/config.json",
    }
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 422
    
    # buffer.bulk_action не должен быть вызван
    mock_buffer.bulk_action.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_action_value_returns_422(client, mock_buffer):
    """
    Тест: Невалидное значение action возвращает HTTP 422
    
    Проверяем:
    - action="invalid" не проходит валидацию
    - HTTP 422
    """
    payload = create_bulk_action_payload(action="invalid")
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 422
    
    # buffer.bulk_action не должен быть вызван
    mock_buffer.bulk_action.assert_not_called()


# ========== Тесты user_injectors ==========

@pytest.mark.asyncio
async def test_user_injectors_passed_correctly(client, mock_buffer, mock_hot_reload):
    """
    Тест: user_injectors правильно передаются в буфер
    
    Проверяем:
    - user_injectors конвертируются в list[dict]
    - Каждый инжектор содержит flatten_array_cursor, extractor_script, libs
    """
    injectors_data = [
        {
            "flatten_array_cursor": "inbounds___0___settings___clients",
            "extractor_script": "def transform(u): return {'id': u['user_uuid']}",
            "libs": None
        },
        {
            "flatten_array_cursor": "inbounds___1___settings___users",
            "extractor_script": "def transform(u): return {'name': u['email']}",
            "libs": "json,base64"
        }
    ]
    
    payload = create_bulk_action_payload(user_injectors=injectors_data)
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    
    # Проверяем что user_injectors переданы правильно
    call_kwargs = mock_buffer.bulk_action.call_args.kwargs
    assert len(call_kwargs["user_injectors"]) == 2
    assert call_kwargs["user_injectors"][0]["flatten_array_cursor"] == "inbounds___0___settings___clients"
    assert call_kwargs["user_injectors"][1]["flatten_array_cursor"] == "inbounds___1___settings___users"


# ========== Тесты custom_params ==========

@pytest.mark.asyncio
async def test_custom_params_passed_to_hot_reload(client, mock_buffer, mock_hot_reload):
    """
    Тест: custom_params передаются в HotReloadExecutor
    
    Проверяем:
    - custom_params корректно переданы
    """
    custom_params = {"inbound_tag": "main", "flow": "xtls-rprx-vision"}
    
    payload = create_bulk_action_payload(
        custom_params=custom_params,
        core_port=10086,
        core_lib="grpcio",
        action_script="def bulk_add_users(users, ip, port, params): return True"
    )
    
    response = await client.put("/api/v1/server/proto_core/user/bulk/action", json=payload)
    
    assert response.status_code == 200
    
    # Проверяем что custom_params переданы в hot-reload
    call_kwargs = mock_hot_reload.execute_action_script.call_args.kwargs
    assert call_kwargs["custom_params"] == custom_params
