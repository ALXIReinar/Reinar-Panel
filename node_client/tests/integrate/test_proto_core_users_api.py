"""
Интеграционные тесты для API proto_core/user/*

Тестируем:
- HTTP endpoints (/user/add, /user/delete, /user/bulk/*)
- Валидацию Pydantic схем
- Взаимодействие с ConfigWriteBuffer (мокированным)
- Hot-reload логику (мокированную)
- Обработку ошибок
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
from fastapi import FastAPI

from node_client.api import main_router
from node_client.tests.utils.test_data_factory import create_test_user


# ========== Fixtures ==========

@pytest.fixture
def mock_buffer():
    """Мокированный ConfigWriteBuffer"""
    buffer_mock = AsyncMock()
    
    # По умолчанию все операции успешны
    buffer_mock.add_user.return_value = (True, 200, "Пользователь добавлен")
    buffer_mock.delete_user.return_value = (True, 200, "Пользователь удалён")
    
    # Мокируем unlimit_queue как синхронную функцию, возвращающую async context manager
    class UnlimitQueueContext:
        async def __aenter__(self):
            return buffer_mock
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None
    
    buffer_mock.unlimit_queue = MagicMock(return_value=UnlimitQueueContext())
    
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


def create_add_user_payload(**overrides):
    """Создаёт валидный payload для /user/add"""
    payload = {
        "node_proto_id": 1,
        "user_obj": create_test_user(email="test@test.com"),
        "config_file_path": "/path/to/config.json",
        "flatten_json_users_key": "inbounds___0___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "systemctl reload xray",
        "core_port": None,
        "core_lib": None,
        "add_script": None,
        "custom_params": None
    }
    payload.update(overrides)
    return payload


def create_delete_user_payload(**overrides):
    """Создаёт валидный payload для /user/delete"""
    payload = {
        "node_proto_id": 1,
        "user_obj": create_test_user(email="test@test.com"),
        "config_file_path": "/path/to/config.json",
        "flatten_json_users_key": "inbounds___0___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "systemctl reload xray",
        "core_port": None,
        "core_lib": None,
        "delete_script": None,
        "custom_params": None
    }
    payload.update(overrides)
    return payload


# ========== Тесты /user/add ==========

async def test_add_user_success(client, mock_buffer, mock_hot_reload):
    """
    Тест: Успешное добавление пользователя
    
    Проверяем:
    - HTTP 200
    - buffer.add_user вызван с правильными параметрами
    - Ответ содержит success=True
    """
    payload = create_add_user_payload()
    
    response = await client.post("/api/v1/server/proto_core/user/add", json=payload)
    
    # Проверяем ответ
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "message" in data
    
    # Проверяем что buffer.add_user был вызван
    mock_buffer.add_user.assert_called_once()
    call_kwargs = mock_buffer.add_user.call_args.kwargs
    
    assert call_kwargs["node_proto_id"] == 1
    assert call_kwargs["user_obj_or_identifier"] == payload["user_obj"]
    assert call_kwargs["filepath"] == payload["config_file_path"]
    assert call_kwargs["users_path"] == payload["flatten_json_users_key"]
    assert call_kwargs["flatten_user_identifier_key"] == payload["flatten_user_identifier_key"]
    assert call_kwargs["reload_command"] == payload["reload_core_command"]


async def test_add_user_with_hot_reload_success(client, mock_buffer, mock_hot_reload):
    """
    Тест: Добавление с hot-reload
    
    Проверяем:
    - HotReloadExecutor.execute_action_script вызван
    - reload_command=None (т.к. hot-reload успешен)
    - Ответ содержит hot_reload=True
    """
    payload = create_add_user_payload(
        core_port=10086,
        core_lib="grpcio",
        add_script="add_user_script.py"
    )
    
    response = await client.post("/api/v1/server/proto_core/user/add", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is True
    assert data["hot_reload_message"] == "Hot-reload успешен"
    
    # Проверяем что hot-reload был вызван
    mock_hot_reload.execute_action_script.assert_called_once()
    
    # Проверяем что reload_command=None (т.к. hot-reload успешен)
    call_kwargs = mock_buffer.add_user.call_args.kwargs
    assert call_kwargs["reload_command"] is None


async def test_add_user_hot_reload_fails_continues_with_file(client, mock_buffer, mock_hot_reload):
    """
    Тест: Hot-reload провалился, но файловая запись продолжается
    
    Проверяем:
    - Hot-reload вернул False
    - buffer.add_user всё равно вызван
    - reload_command передан (т.к. hot-reload провалился)
    """
    # Hot-reload провалился (AsyncMock)
    mock_hot_reload.execute_action_script = AsyncMock(return_value=(False, "Hot-reload ошибка"))
    
    payload = create_add_user_payload(
        core_port=10086,
        core_lib="grpcio",
        add_script="add_user_script.py",
        reload_core_command="systemctl reload xray"
    )
    
    response = await client.post("/api/v1/server/proto_core/user/add", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is False
    assert data["hot_reload_message"] == "Hot-reload ошибка"
    
    # Проверяем что buffer.add_user был вызван с reload_command
    call_kwargs = mock_buffer.add_user.call_args.kwargs
    assert call_kwargs["reload_command"] == "systemctl reload xray"


async def test_add_user_buffer_error_returns_500(client, mock_buffer, mock_hot_reload):
    """
    Тест: Ошибка от буфера возвращает HTTP 500
    
    Проверяем:
    - buffer.add_user вернул (False, 500, error_message)
    - HTTP 500
    - Ответ содержит детали ошибки
    """
    # Буфер возвращает ошибку
    mock_buffer.add_user.return_value = (False, 500, "Ошибка валидации конфига")
    
    payload = create_add_user_payload()
    
    response = await client.post("/api/v1/server/proto_core/user/add", json=payload)
    
    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False
    assert "error_message" in data["detail"]
    assert "Ошибка валидации конфига" in data["detail"]["error_message"]


async def test_add_user_invalid_schema_returns_422(client, mock_buffer):
    """
    Тест: Невалидная схема возвращает HTTP 422
    
    Проверяем:
    - Отсутствует обязательное поле
    - HTTP 422
    - buffer.add_user НЕ вызван
    """
    payload = {
        "node_proto_id": 1,
        # user_obj отсутствует (обязательное поле)
        "config_file_path": "/path/to/config.json",
    }
    
    response = await client.post("/api/v1/server/proto_core/user/add", json=payload)
    
    assert response.status_code == 422
    
    # buffer.add_user не должен быть вызван
    mock_buffer.add_user.assert_not_called()


# ========== Тесты /user/delete ==========

async def test_delete_user_success(client, mock_buffer, mock_hot_reload):
    """
    Тест: Успешное удаление пользователя
    
    Проверяем:
    - HTTP 200
    - buffer.delete_user вызван с правильными параметрами
    - Ответ содержит success=True
    """
    payload = create_delete_user_payload()
    
    response = await client.post("/api/v1/server/proto_core/user/delete", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что buffer.delete_user был вызван
    mock_buffer.delete_user.assert_called_once()
    call_kwargs = mock_buffer.delete_user.call_args.kwargs
    
    assert call_kwargs["node_proto_id"] == 1
    assert call_kwargs["user_obj_or_identifier"] == payload["user_obj"]
    assert call_kwargs["filepath"] == payload["config_file_path"]


async def test_delete_user_with_hot_reload(client, mock_buffer, mock_hot_reload):
    """
    Тест: Удаление с hot-reload
    
    Проверяем:
    - HotReloadExecutor вызван для delete
    - Ответ содержит hot_reload=True
    """
    payload = create_delete_user_payload(
        core_port=10086,
        core_lib="grpcio",
        delete_script="delete_user_script.py"
    )
    
    response = await client.post("/api/v1/server/proto_core/user/delete", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is True
    
    # Проверяем что hot-reload был вызван
    mock_hot_reload.execute_action_script.assert_called_once()


async def test_delete_user_buffer_error_returns_500(client, mock_buffer, mock_hot_reload):
    """
    Тест: Ошибка от буфера при удалении
    
    Проверяем:
    - buffer.delete_user вернул (False, 500, error)
    - HTTP 500
    """
    mock_buffer.delete_user.return_value = (False, 500, "Нода не зарегистрирована")
    
    payload = create_delete_user_payload()
    
    response = await client.post("/api/v1/server/proto_core/user/delete", json=payload)
    
    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False


# ========== Тесты /user/bulk/add ==========

async def test_bulk_add_users_success(client, mock_buffer, mock_hot_reload):
    """
    Тест: Массовое добавление пользователей
    
    Проверяем:
    - HTTP 200
    - unlimit_queue использован
    - buffer.add_user вызван для каждого пользователя
    """
    users = [create_test_user(email=f"user{i}@test.com") for i in range(5)]
    
    payload = {
        "node_proto_id": 1,
        "users": users,
        "config_file_path": "/path/to/config.json",
        "flatten_json_users_key": "inbounds___0___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "systemctl reload xray",
        "core_port": None,
        "core_lib": None,
        "bulk_add_script": None,
        "custom_params": None
    }
    
    response = await client.post("/api/v1/server/proto_core/user/bulk/add", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что unlimit_queue был использован
    mock_buffer.unlimit_queue.assert_called_once_with(1)
    
    # Проверяем что add_user вызван 5 раз
    assert mock_buffer.add_user.call_count == 5


async def test_bulk_delete_users_success(client, mock_buffer, mock_hot_reload):
    """
    Тест: Массовое удаление пользователей
    
    Проверяем:
    - HTTP 200
    - unlimit_queue использован
    - buffer.delete_user вызван для каждого пользователя
    """
    payload = {
        "node_proto_id": 1,
        "users": [
            {"uuid": "user1@test.com", "tg_username": "user1_tg", "sub_node_id": 1, "order_id": 1},
            {"uuid": "user2@test.com", "tg_username": "user2_tg", "sub_node_id": 1, "order_id": 2},
            {"uuid": "user3@test.com", "tg_username": "user3_tg", "sub_node_id": 1, "order_id": 3}
        ],
        "config_file_path": "/path/to/config.json",
        "flatten_json_users_key": "inbounds___0___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "systemctl reload xray",
        "core_port": None,
        "core_lib": None,
        "bulk_delete_script": None,
        "custom_params": None
    }
    
    response = await client.request("DELETE", "/api/v1/server/proto_core/user/bulk/delete", json=payload)
    
    # DEBUG: Смотрим что именно не прошло валидацию
    if response.status_code != 200:
        print(f"Response: {response.status_code}")
        print(f"Body: {response.json()}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что unlimit_queue был использован
    mock_buffer.unlimit_queue.assert_called_once_with(1)
    
    # Проверяем что delete_user вызван 3 раза
    assert mock_buffer.delete_user.call_count == 3


async def test_bulk_add_with_hot_reload(client, mock_buffer, mock_hot_reload):
    """
    Тест: Bulk add с hot-reload
    
    Проверяем:
    - HotReloadExecutor вызван для bulk_add_users
    - Ответ содержит hot_reload=True
    """
    users = [create_test_user(email=f"user{i}@test.com") for i in range(3)]
    
    payload = {
        "node_proto_id": 1,
        "users": users,
        "config_file_path": "/path/to/config.json",
        "flatten_json_users_key": "inbounds___0___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "systemctl reload xray",
        "core_port": 10086,
        "core_lib": "grpcio",
        "bulk_add_script": "bulk_add_script.py",
        "custom_params": None
    }
    
    response = await client.post("/api/v1/server/proto_core/user/bulk/add", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["hot_reload"] is True
    
    # Проверяем что hot-reload был вызван с action='bulk_add_users'
    mock_hot_reload.execute_action_script.assert_called_once()
    call_kwargs = mock_hot_reload.execute_action_script.call_args.kwargs
    assert call_kwargs["action"] == "bulk_add_users"


async def test_bulk_operations_use_unlimit_mode(client, mock_buffer, mock_hot_reload):
    """
    Тест: Bulk операции используют unlimit режим
    
    Проверяем:
    - unlimit_queue вызван перед добавлением
    - Контекстный менеджер использован правильно
    """
    users = [create_test_user(email=f"user{i}@test.com") for i in range(10)]
    
    payload = {
        "node_proto_id": 1,
        "users": users,
        "config_file_path": "/path/to/config.json",
        "flatten_json_users_key": "inbounds___0___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "systemctl reload xray",  # Обязательное поле
        "core_port": None,
        "core_lib": None,
        "bulk_add_script": None,
        "custom_params": None
    }
    
    response = await client.post("/api/v1/server/proto_core/user/bulk/add", json=payload)
    
    assert response.status_code == 200
    
    # Проверяем что unlimit_queue был использован
    mock_buffer.unlimit_queue.assert_called_once_with(1)
