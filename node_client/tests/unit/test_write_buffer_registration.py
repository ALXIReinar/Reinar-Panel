"""
Unit тесты для регистрации нод в ConfigWriteBuffer

Тестируем:
- register_node() - регистрация виртуальных нод
- _load_users_from_config() - загрузка пользователей из state.json файла
"""
import asyncio
import pytest
from pathlib import Path

import orjson

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.tests.utils.test_data_factory import create_test_user, create_user_injectors


# ========== Fixtures ==========

@pytest.fixture
def sample_config_with_users(tmp_path):
    """
    Создаёт конфиг с 3 пользователями + state.json файл
    
    Returns:
        tuple: (config_path, config_dict)
    """
    # Основной конфиг ядра (то что читает xray)
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        create_test_user(email="user1@test.com", uuid="uuid-001", as_superuser=False),
                        create_test_user(email="user2@test.com", uuid="uuid-002", as_superuser=False),
                        create_test_user(email="user3@test.com", uuid="uuid-003", as_superuser=False),
                    ]
                }
            }
        ]
    }
    
    config_path = tmp_path / "config_with_users.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    # State файл с суперобъектами (наш служебный файл)
    state = {
        "users": [
            create_test_user(email="user1@test.com", uuid="uuid-001", as_superuser=True),
            create_test_user(email="user2@test.com", uuid="uuid-002", as_superuser=True),
            create_test_user(email="user3@test.com", uuid="uuid-003", as_superuser=True),
        ]
    }
    
    state_path = tmp_path / "config_with_users.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    return config_path, config


@pytest.fixture
def empty_config(tmp_path):
    """Создаёт конфиг с пустым массивом clients + пустой state"""
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
    
    # Пустой state файл
    state = {"users": []}
    state_path = tmp_path / "empty_config.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    return config_path


# ========== Тесты register_node() ==========

async def test_register_node_success(sample_config_with_users):
    """
    Тест: Успешная регистрация ноды с загрузкой пользователей
    
    Проверяем что:
    1. Метаданные сохранены
    2. Очередь создана
    3. Пользователи загружены в буфер из state.json
    4. Воркер запущен
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=1.0)
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    filepath = str(config_path)
    user_injectors = create_user_injectors()
    reload_command = "systemctl reload xray"
    
    # Регистрируем ноду
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=filepath,
        user_injectors=user_injectors,
        reload_command=reload_command
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    assert "Зарегистрирована очередь" in msg or "зарегистрирована" in msg.lower()
    
    # Проверяем метаданные
    assert node_proto_id in buffer.node_metadata
    metadata = buffer.node_metadata[node_proto_id]
    assert metadata['filepath'] == filepath
    assert metadata['reload_command'] == reload_command
    assert 'injectors' in metadata
    assert len(metadata['injectors']) == 1
    
    # Проверяем очередь
    assert node_proto_id in buffer.node_queues
    assert isinstance(buffer.node_queues[node_proto_id], asyncio.Queue)
    
    # Проверяем что пользователи загружены из state.json
    assert node_proto_id in buffer.buffer_storage
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    
    # В новой архитектуре ключи - это user_uuid
    buffer_keys = list(buffer.buffer_storage[node_proto_id].keys())
    assert "uuid-001" in buffer_keys
    assert "uuid-002" in buffer_keys
    assert "uuid-003" in buffer_keys
    
    # Проверяем O(1) структуру
    user1 = buffer.buffer_storage[node_proto_id]["uuid-001"]
    assert user1["email"] == "user1@test.com"
    assert user1["user_uuid"] == "uuid-001"
    
    # Проверяем что воркер запущен
    assert node_proto_id in buffer.worker_tasks
    assert not buffer.worker_tasks[node_proto_id].done()
    
    # Cleanup
    await buffer.stop()


async def test_register_node_loads_existing_users(sample_config_with_users):
    """
    Тест: Регистрация ноды загружает существующих пользователей из state.json
    
    Проверяем что все 3 пользователя корректно загружены в O(1) структуру
    """
    buffer = ConfigWriteBuffer()
    config_path, config_dict = sample_config_with_users
    
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем что все пользователи загружены из state.json
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    
    # Проверяем структуру {user_uuid: user_obj}
    expected_uuids = ["uuid-001", "uuid-002", "uuid-003"]
    for uuid in expected_uuids:
        assert uuid in buffer.buffer_storage[node_proto_id]
        user = buffer.buffer_storage[node_proto_id][uuid]
        assert user["user_uuid"] == uuid
        assert "email" in user
    
    await buffer.stop()


async def test_register_node_empty_config(empty_config):
    """
    Тест: Регистрация ноды с пустым массивом clients
    
    Проверяем что нода регистрируется успешно с пустым буфером
    """
    buffer = ConfigWriteBuffer()
    
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(empty_config),
        user_injectors=user_injectors,
        reload_command=None
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
    user_injectors = create_user_injectors()
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath="/path/to/nonexistent/file.json",
        user_injectors=user_injectors,
        reload_command=None
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
    # Создаём инжектор с неверным путём
    user_injectors = create_user_injectors(flatten_array_cursor="inbounds___99___nonexistent___clients")
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


async def test_register_node_invalid_extractor_script_syntax(sample_config_with_users):
    """
    Тест: КРИТИЧНАЯ ошибка - невалидный extractor_script (синтаксическая ошибка)
    
    Файл валидный, пользователи есть, но скрипт содержит синтаксическую ошибку.
    
    Ожидаем: (False, 500, error_message с указанием на ошибку скрипта)
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    # Создаём инжектор с синтаксически некорректным скриптом
    user_injectors = create_user_injectors(
        extractor_script="def transform(u) this is invalid syntax !!!"
    )
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


async def test_register_node_missing_transform_function(sample_config_with_users):
    """
    Тест: КРИТИЧНАЯ ошибка - в extractor_script отсутствует функция transform
    
    Скрипт валидный синтаксически, но не содержит требуемую функцию transform().
    
    Ожидаем: (False, 500, error_message)
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    # Создаём инжектор со скриптом без функции transform
    user_injectors = create_user_injectors(
        extractor_script="def wrong_name(u): return u"
    )
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем что регистрация провалилась
    assert success is False
    assert status_code == 500
    assert isinstance(msg, str)
    assert "transform" in msg.lower() or "не найден" in msg.lower()
    
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
    user_injectors = create_user_injectors()
    
    success, status_code, msg = await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(broken_file),
        user_injectors=user_injectors,
        reload_command=None
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
    Тест: Создание корректного маппинга {user_uuid: user_obj}
    
    Проверяем что _load_users_from_config загружает из state.json и создаёт O(1) структуру
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    
    # Подготавливаем метаданные вручную
    buffer.node_metadata[node_proto_id] = {
        'filepath': str(config_path),
        'injectors': [],  # Для _load_users_from_config не используется
        'reload_command': None
    }
    
    # Загружаем пользователей из state.json
    await buffer._load_users_from_config(node_proto_id)
    
    # Проверяем структуру
    assert node_proto_id in buffer.buffer_storage
    users_map = buffer.buffer_storage[node_proto_id]
    
    # Должно быть 3 пользователя из state.json
    assert len(users_map) == 3
    
    # Проверяем O(1) доступ по user_uuid
    assert "uuid-001" in users_map
    assert "uuid-002" in users_map
    assert "uuid-003" in users_map
    
    # Проверяем что значения - это полные суперобъекты
    user1 = users_map["uuid-001"]
    assert user1["email"] == "user1@test.com"
    assert user1["user_uuid"] == "uuid-001"
    assert "flow" in user1


async def test_load_users_with_uuid_identifier(sample_config_with_users):
    """
    Тест: Загрузка пользователей из state.json всегда использует user_uuid
    
    Проверяем что ключи - это всегда user_uuid
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    
    node_proto_id = 1
    
    buffer.node_metadata[node_proto_id] = {
        'filepath': str(config_path),
        'injectors': [],
        'reload_command': None
    }
    
    await buffer._load_users_from_config(node_proto_id)
    
    users_map = buffer.buffer_storage[node_proto_id]
    
    # Проверяем что ключи - это user_uuid
    assert "uuid-001" in users_map
    assert "uuid-002" in users_map
    assert "uuid-003" in users_map
    
    # Проверяем значения
    user1 = users_map["uuid-001"]
    assert user1["user_uuid"] == "uuid-001"
    assert user1["email"] == "user1@test.com"
