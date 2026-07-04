"""
Unit тесты для регистрации нод в ConfigWriteBuffer

Тестируем:
- register_node() - регистрация виртуальных нод
- _load_users_from_config() - загрузка пользователей из конфиг-файла
"""
import asyncio
import pytest
from pathlib import Path

import orjson

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.tests.utils.test_data_factory import create_test_user


# ========== Fixtures ==========

@pytest.fixture
def sample_config_with_users(tmp_path):
    """Создаёт конфиг с 3 пользователями"""
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        create_test_user(email="user1@test.com", uuid="uuid-001"),
                        create_test_user(email="user2@test.com", uuid="uuid-002"),
                        create_test_user(email="user3@test.com", uuid="uuid-003"),
                    ]
                }
            }
        ]
    }
    
    config_path = tmp_path / "config_with_users.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    return config_path, config


@pytest.fixture
def empty_config(tmp_path):
    """Создаёт конфиг с пустым массивом clients"""
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": []  # Пустой массив
                }
            }
        ]
    }
    
    config_path = tmp_path / "empty_config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    return config_path


# ========== Тесты register_node() ==========

async def test_register_node_success(sample_config_with_users):
    """
    Тест: Успешная регистрация ноды с загрузкой пользователей
    
    Проверяем что:
    1. Метаданные сохранены
    2. Очередь создана
    3. Пользователи загружены в буфер
    4. Воркер запущен
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=1.0)
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    filepath = str(config_path)
    users_path = "inbounds___0___settings___clients"
    flatten_user_identifier_key = "email"
    reload_command = "systemctl reload xray"
    
    # Создаём тестового пользователя для валидации
    test_user = create_test_user(email="test@test.com")
    
    # Регистрируем ноду
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=filepath,
        users_path=users_path,
        flatten_user_identifier_key=flatten_user_identifier_key,
        reload_command=reload_command,
        user_obj=test_user
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    assert "Зарегистрирована очередь" in msg or "зарегистрирована" in msg.lower()
    
    # Проверяем метаданные
    assert node_proto_id in buffer.node_metadata
    metadata = buffer.node_metadata[node_proto_id]
    assert metadata['filepath'] == filepath
    assert metadata['users_path'] == users_path
    assert metadata['flatten_user_identifier_key'] == flatten_user_identifier_key
    assert metadata['reload_command'] == reload_command
    
    # Проверяем очередь
    assert node_proto_id in buffer.node_queues
    assert isinstance(buffer.node_queues[node_proto_id], asyncio.Queue)
    
    # Проверяем что пользователи загружены
    assert node_proto_id in buffer.buffer_storage
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    assert "user1@test.com" in buffer.buffer_storage[node_proto_id]
    assert "user2@test.com" in buffer.buffer_storage[node_proto_id]
    assert "user3@test.com" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем O(1) структуру
    user1 = buffer.buffer_storage[node_proto_id]["user1@test.com"]
    assert user1["email"] == "user1@test.com"
    assert user1["id"] == "uuid-001"
    
    # Проверяем что воркер запущен
    assert node_proto_id in buffer.worker_tasks
    assert not buffer.worker_tasks[node_proto_id].done()
    
    # Cleanup
    await buffer.stop()


async def test_register_node_loads_existing_users(sample_config_with_users):
    """
    Тест: Регистрация ноды загружает существующих пользователей из конфига
    
    Проверяем что все 3 пользователя корректно загружены в O(1) структуру
    """
    buffer = ConfigWriteBuffer()
    config_path, config_dict = sample_config_with_users
    
    node_proto_id = 1
    test_user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем что все пользователи загружены
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    
    # Проверяем структуру {email: user_obj}
    expected_emails = ["user1@test.com", "user2@test.com", "user3@test.com"]
    for email in expected_emails:
        assert email in buffer.buffer_storage[node_proto_id]
        user = buffer.buffer_storage[node_proto_id][email]
        assert user["email"] == email
        assert "id" in user  # UUID должен быть
    
    await buffer.stop()


async def test_register_node_empty_config(empty_config):
    """
    Тест: Регистрация ноды с пустым массивом clients
    
    Проверяем что нода регистрируется успешно с пустым буфером
    """
    buffer = ConfigWriteBuffer()
    
    node_proto_id = 1
    test_user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(empty_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем что буфер пустой
    assert node_proto_id in buffer.buffer_storage
    assert buffer.buffer_storage[node_proto_id] == {}
    assert len(buffer.buffer_storage[node_proto_id]) == 0
    
    # Но метаданные и очередь должны быть
    assert node_proto_id in buffer.node_metadata
    assert node_proto_id in buffer.node_queues
    assert node_proto_id in buffer.worker_tasks
    
    await buffer.stop()


async def test_register_node_file_not_found():
    """
    Тест: Ошибка регистрации - файл не найден
    
    Ожидаем: (False, 500, error_message)
    Нода НЕ должна быть зарегистрирована
    """
    buffer = ConfigWriteBuffer()
    
    node_proto_id = 1
    test_user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath="/path/to/nonexistent/file.json",
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    
    # Проверяем что нода НЕ зарегистрирована
    assert node_proto_id not in buffer.node_metadata
    assert node_proto_id not in buffer.node_queues
    assert node_proto_id not in buffer.worker_tasks
    assert node_proto_id not in buffer.buffer_storage
    
    await buffer.stop()


async def test_register_node_invalid_users_path(sample_config_with_users):
    """
    Тест: Ошибка регистрации - неверный путь к массиву пользователей
    
    Ожидаем: (False, 500, error_message)
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    test_user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        users_path="inbounds___99___nonexistent___clients",  # Неверный путь
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


async def test_register_node_invalid_identifier_key(sample_config_with_users):
    """
    Тест: КРИТИЧНАЯ ошибка - неверный flatten_user_identifier_key
    
    Файл валидный, пользователи есть, но ключ идентификатора указывает
    на несуществующее поле.
    
    Ожидаем: (False, 500, error_message с указанием на ошибку identifier)
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    test_user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="nonexistent_field",  # ОШИБКА!
        reload_command=None,
        user_obj=test_user
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    # Сообщение должно указывать на проблему с identifier
    assert "nonexistent_field" in msg or "не найден" in msg.lower()
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


async def test_register_node_corrupted_json(tmp_path):
    """
    Тест: Ошибка регистрации - невалидный JSON
    
    Ожидаем: (False, 500, error_message)
    """
    buffer = ConfigWriteBuffer()
    
    # Создаём файл с невалидным JSON
    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{ this is not valid json !@#$%")
    
    node_proto_id = 1
    test_user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(broken_file),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


# ========== Тесты _load_users_from_config() ==========

async def test_load_users_creates_correct_mapping(sample_config_with_users):
    """
    Тест: Создание корректного маппинга {identifier: user_obj}
    
    Проверяем что _load_users_from_config создаёт O(1) структуру
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    
    # Подготавливаем метаданные вручную
    buffer.node_metadata[node_proto_id] = {
        'filepath': str(config_path),
        'users_path': "inbounds___0___settings___clients",
        'flatten_user_identifier_key': "email",
        'reload_command': None
    }
    
    # Загружаем пользователей
    await buffer._load_users_from_config(node_proto_id)
    
    # Проверяем структуру
    assert node_proto_id in buffer.buffer_storage
    users_map = buffer.buffer_storage[node_proto_id]
    
    # Должно быть 3 пользователя
    assert len(users_map) == 3
    
    # Проверяем O(1) доступ
    assert "user1@test.com" in users_map
    assert "user2@test.com" in users_map
    assert "user3@test.com" in users_map
    
    # Проверяем что значения - это полные объекты пользователей
    user1 = users_map["user1@test.com"]
    assert user1["email"] == "user1@test.com"
    assert user1["id"] == "uuid-001"
    assert "flow" in user1


async def test_load_users_with_uuid_identifier(sample_config_with_users):
    """
    Тест: Использование UUID в качестве идентификатора
    
    Проверяем что можно использовать "id" вместо "email"
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    
    buffer.node_metadata[node_proto_id] = {
        'filepath': str(config_path),
        'users_path': "inbounds___0___settings___clients",
        'flatten_user_identifier_key': "id",  # Используем UUID
        'reload_command': None
    }
    
    await buffer._load_users_from_config(node_proto_id)
    
    users_map = buffer.buffer_storage[node_proto_id]
    
    # Проверяем что ключи - это UUID
    assert "uuid-001" in users_map
    assert "uuid-002" in users_map
    assert "uuid-003" in users_map
    
    # Проверяем значения
    user1 = users_map["uuid-001"]
    assert user1["id"] == "uuid-001"
    assert user1["email"] == "user1@test.com"
