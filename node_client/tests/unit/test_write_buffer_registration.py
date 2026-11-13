"""
Unit тесты для регистрации нод в ConfigWriteBuffer

Тестируем:
- register_node() - регистрация виртуальных нод (сигнатура item: dict, NodeInitError)
- _load_users_from_config() - загрузка пользователей из state.json файла
- Идемпотентность повторной регистрации
"""

import asyncio  # noqa: I001
import pytest
from pathlib import Path  # noqa: F401

import orjson

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.exceptions import NodeInitError
from node_client.tests.utils.test_data_factory import (
    create_test_user,
    create_user_injectors,
    create_vnode_service_data,
)


# ========== Fixtures ==========


@pytest.fixture
def sample_config_with_users(tmp_path):
    """
    Создаёт конфиг с 3 пользователями + state.json файл

    Returns:
        tuple: (config_path, config_dict)
    """
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
                },
            }
        ]
    }
    config_path = tmp_path / "config_with_users.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
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
                "settings": {"clients": []},
            }
        ]
    }
    config_path = tmp_path / "empty_config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state = {"users": []}
    state_path = tmp_path / "empty_config.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    return config_path


# ========== Тесты register_node() ==========


async def test_register_node_success(sample_config_with_users):
    """
    Тест: Успешная регистрация ноды с загрузкой пользователей
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=1.0)
    config_path, _ = sample_config_with_users
    node_proto_id = 1
    filepath = str(config_path)
    user_injectors = create_user_injectors()
    reload_command = "systemctl reload xray"

    item = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=filepath,
        user_injectors=user_injectors,
        reload_command=reload_command,
    )
    await buffer.register_node(item)

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

    await buffer.stop()


async def test_register_node_loads_existing_users(sample_config_with_users):
    """
    Тест: Регистрация ноды загружает существующих пользователей из state.json
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1

    item = create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_path))
    await buffer.register_node(item)

    assert len(buffer.buffer_storage[node_proto_id]) == 3
    for uuid in ["uuid-001", "uuid-002", "uuid-003"]:
        assert uuid in buffer.buffer_storage[node_proto_id]
        user = buffer.buffer_storage[node_proto_id][uuid]
        assert user["user_uuid"] == uuid
        assert "email" in user
    await buffer.stop()


async def test_register_node_empty_config(empty_config):
    """
    Тест: Регистрация ноды с пустым массивом clients
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1

    item = create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(empty_config))
    await buffer.register_node(item)

    assert node_proto_id in buffer.buffer_storage
    assert buffer.buffer_storage[node_proto_id] == {}
    assert node_proto_id in buffer.node_metadata
    assert node_proto_id in buffer.node_queues
    assert node_proto_id in buffer.worker_tasks
    await buffer.stop()


async def test_register_node_file_not_found():
    """
    Тест: Ошибка регистрации - файл не найден -> NodeInitError
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1

    item = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath="/path/to/nonexistent/file.json",
    )
    with pytest.raises(NodeInitError) as exc_info:
        await buffer.register_node(item)

    assert exc_info.value.node_proto_id == node_proto_id
    assert exc_info.value.field == "filepath"
    assert node_proto_id not in buffer.node_metadata
    assert node_proto_id not in buffer.node_queues
    await buffer.stop()


async def test_register_node_invalid_users_path(sample_config_with_users):
    """
    Тест: Ошибка регистрации - неверный путь к массиву пользователей -> NodeInitError
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1
    user_injectors = create_user_injectors(flatten_array_cursor="inbounds___99___nonexistent___clients")

    item = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
    )
    with pytest.raises(NodeInitError) as exc_info:
        await buffer.register_node(item)

    assert exc_info.value.node_proto_id == node_proto_id
    assert "flatten_array_cursor" in exc_info.value.field
    assert node_proto_id not in buffer.node_queues
    await buffer.stop()


async def test_register_node_invalid_extractor_script_syntax(sample_config_with_users):
    """
    Тест: КРИТИЧНАЯ ошибка - синтаксическая ошибка в extractor_script -> NodeInitError
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1
    user_injectors = create_user_injectors(extractor_script="def transform(u) this is invalid syntax !!!")

    item = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
    )
    with pytest.raises(NodeInitError) as exc_info:
        await buffer.register_node(item)

    assert exc_info.value.node_proto_id == node_proto_id
    assert "extractor_script" in exc_info.value.field
    assert node_proto_id not in buffer.node_queues
    await buffer.stop()


async def test_register_node_missing_transform_function(sample_config_with_users):
    """
    Тест: В extractor_script отсутствует функция transform -> NodeInitError
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1
    user_injectors = create_user_injectors(extractor_script="def wrong_name(u): return u")

    item = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=user_injectors,
    )
    with pytest.raises(NodeInitError) as exc_info:
        await buffer.register_node(item)

    assert exc_info.value.node_proto_id == node_proto_id
    assert "extractor_script" in exc_info.value.field
    assert node_proto_id not in buffer.node_queues
    await buffer.stop()


async def test_register_node_corrupted_json(tmp_path):
    """
    Тест: Невалидный JSON конфига -> NodeInitError
    """
    buffer = ConfigWriteBuffer()
    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{ this is not valid json !@#$%")
    node_proto_id = 1

    item = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(broken_file),
    )
    with pytest.raises(NodeInitError) as exc_info:
        await buffer.register_node(item)

    assert exc_info.value.node_proto_id == node_proto_id
    assert exc_info.value.field == "filepath"
    assert node_proto_id not in buffer.node_queues
    await buffer.stop()


async def test_register_node_idempotence(sample_config_with_users):
    """
    Тест (Property 1): Повторный вызов register_node для известной ноды
    заменяет метаданные, но НЕ очищает buffer_storage и local_state
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1

    item1 = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        reload_command="cmd1",
    )
    await buffer.register_node(item1)

    assert buffer.node_metadata[node_proto_id]['reload_command'] == "cmd1"
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    buffer.local_state[node_proto_id]['test_key'] = 42

    # Повторная регистрация с обновлённой командой
    item2 = create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        reload_command="cmd2",
    )
    await buffer.register_node(item2)

    # Метаданные обновились
    assert buffer.node_metadata[node_proto_id]['reload_command'] == "cmd2"
    # buffer_storage и local_state сохранились
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    assert buffer.local_state[node_proto_id]['test_key'] == 42

    await buffer.stop()


# ========== Тесты _load_users_from_config() ==========


async def test_load_users_creates_correct_mapping(sample_config_with_users):
    """
    Тест: Создание корректного маппинга {user_uuid: user_obj}
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1
    buffer.node_metadata[node_proto_id] = {
        'filepath': str(config_path),
        'injectors': [],
        'reload_command': None,
    }
    await buffer._load_users_from_config(node_proto_id)
    assert node_proto_id in buffer.buffer_storage
    users_map = buffer.buffer_storage[node_proto_id]
    assert len(users_map) == 3
    assert "uuid-001" in users_map
    assert "uuid-002" in users_map
    assert "uuid-003" in users_map
    user1 = users_map["uuid-001"]
    assert user1["email"] == "user1@test.com"
    assert user1["user_uuid"] == "uuid-001"
    assert "flow" in user1


async def test_load_users_with_uuid_identifier(sample_config_with_users):
    """
    Тест: Загрузка пользователей из state.json всегда использует user_uuid
    """
    buffer = ConfigWriteBuffer()
    config_path, _ = sample_config_with_users
    node_proto_id = 1
    buffer.node_metadata[node_proto_id] = {'filepath': str(config_path), 'injectors': [], 'reload_command': None}
    await buffer._load_users_from_config(node_proto_id)
    users_map = buffer.buffer_storage[node_proto_id]
    assert "uuid-001" in users_map
    assert "uuid-002" in users_map
    assert "uuid-003" in users_map
    user1 = users_map["uuid-001"]
    assert user1["user_uuid"] == "uuid-001"
    assert user1["email"] == "user1@test.com"
