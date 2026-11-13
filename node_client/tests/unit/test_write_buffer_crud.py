"""
Unit тесты для CRUD операций в ConfigWriteBuffer

Тестируем:
- add_user() - добавление пользователей в буфер (тонкий вызов, NodeNotRegisteredError при незарегистрированной ноде)
- delete_user() - удаление пользователей из буфера
- bulk_action() - пакетные операции добавления и удаления
- read_config_json() и dump_config() - вспомогательные методы конвертации
"""

from pathlib import Path  # noqa: F401

import orjson
import pytest

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.exceptions import NodeNotRegisteredError
from node_client.tests.utils.test_data_factory import (
    create_test_user,
    create_vnode_service_data,
)

# ========== Fixtures ==========


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


@pytest.fixture
def config_with_3_users(tmp_path):
    """Создаёт конфиг с 3 пользователями + state файл"""
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        create_test_user(email="existing1@test.com", uuid="uuid-existing-1", as_superuser=False),
                        create_test_user(email="existing2@test.com", uuid="uuid-existing-2", as_superuser=False),
                        create_test_user(email="existing3@test.com", uuid="uuid-existing-3", as_superuser=False),
                    ]
                },
            }
        ]
    }
    config_path = tmp_path / "config_with_3_users.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state = {
        "users": [
            create_test_user(email="existing1@test.com", uuid="uuid-existing-1", as_superuser=True),
            create_test_user(email="existing2@test.com", uuid="uuid-existing-2", as_superuser=True),
            create_test_user(email="existing3@test.com", uuid="uuid-existing-3", as_superuser=True),
        ]
    }
    state_path = tmp_path / "config_with_3_users.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    return config_path


# ========== Тесты add_user() ==========


async def test_add_user_unregistered_node():
    """
    Тест: Попытка добавления в незарегистрированную ноду -> NodeNotRegisteredError
    """
    buffer = ConfigWriteBuffer()
    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1", as_superuser=True)
    with pytest.raises(NodeNotRegisteredError) as exc_info:
        await buffer.add_user(node_proto_id=999, user_obj=new_user)
    assert exc_info.value.node_proto_id == 999
    await buffer.stop()


async def test_add_user_first_time_with_empty_config(empty_config):
    """
    Тест: Добавление пользователя в зарегистрированную ноду с пустым конфигом
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(empty_config)))

    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1", as_superuser=True)
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=new_user,
    )
    assert success is True
    assert status_code == 200
    assert len(buffer.buffer_storage[node_proto_id]) == 1
    assert "uuid-new-1" in buffer.buffer_storage[node_proto_id]

    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    operation = await queue.get()
    assert operation == {'op': 'add', 'uuid': 'uuid-new-1'}
    await buffer.stop()


async def test_add_user_first_time_with_existing_users(config_with_3_users):
    """
    Тест: Добавление пользователя в ноду с 3 существующими пользователями
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1", as_superuser=True)
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=new_user,
    )
    assert success is True
    assert status_code == 200
    assert len(buffer.buffer_storage[node_proto_id]) == 4
    assert "uuid-existing-1" in buffer.buffer_storage[node_proto_id]
    assert "uuid-new-1" in buffer.buffer_storage[node_proto_id]

    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    operation = await queue.get()
    assert operation == {'op': 'add', 'uuid': 'uuid-new-1'}
    await buffer.stop()


async def test_add_user_to_existing_node(config_with_3_users):
    """
    Тест: Последовательное добавление нескольких пользователей
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    user1 = create_test_user(email="user1@test.com", uuid="uuid-1", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user1)
    assert len(buffer.buffer_storage[node_proto_id]) == 4

    user2 = create_test_user(email="user2@test.com", uuid="uuid-2", as_superuser=True)
    success, status_code, msg = await buffer.add_user(node_proto_id=node_proto_id, user_obj=user2)
    assert success is True
    assert status_code == 200
    assert len(buffer.buffer_storage[node_proto_id]) == 5
    assert "uuid-2" in buffer.buffer_storage[node_proto_id]

    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 2
    await buffer.stop()


async def test_add_user_idempotency(config_with_3_users):
    """
    Тест: IDEMPOTENCY - повторное добавление существующего пользователя
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    user = create_test_user(email="idempotent@test.com", uuid="uuid-idempotent", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)

    initial_len = len(buffer.buffer_storage[node_proto_id])
    queue = buffer.node_queues[node_proto_id]
    while not queue.empty():
        await queue.get()
    assert queue.qsize() == 0

    # Повторное добавление того же uuid
    success, status_code, msg = await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)
    assert success is True
    assert status_code == 200
    assert "добавлен" in msg.lower()

    # Длина и очередь не изменились
    assert len(buffer.buffer_storage[node_proto_id]) == initial_len
    assert queue.qsize() == 0
    await buffer.stop()


async def test_add_user_with_dict_vs_str(empty_config):
    """
    Тест: Добавление через dict (суперобъект с user_uuid)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(empty_config)))

    user_dict = create_test_user(email="dict_user@test.com", uuid="uuid-dict", as_superuser=True)
    success1, status_code1, _ = await buffer.add_user(node_proto_id=node_proto_id, user_obj=user_dict)
    assert success1 is True
    assert "uuid-dict" in buffer.buffer_storage[node_proto_id]

    user_dict2 = create_test_user(email="dict_user2@test.com", uuid="uuid-dict2", as_superuser=True)
    success2, status_code2, _ = await buffer.add_user(node_proto_id=node_proto_id, user_obj=user_dict2)
    assert success2 is True
    assert "uuid-dict2" in buffer.buffer_storage[node_proto_id]
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    await buffer.stop()


# ========== Тесты delete_user() ==========


async def test_delete_user_unregistered_node():
    """
    Тест: Удаление из незарегистрированной ноды -> NodeNotRegisteredError
    """
    buffer = ConfigWriteBuffer()
    user = create_test_user(email="test@test.com", uuid="uuid-1", as_superuser=True)
    with pytest.raises(NodeNotRegisteredError) as exc_info:
        await buffer.delete_user(node_proto_id=999, user_obj=user)
    assert exc_info.value.node_proto_id == 999
    await buffer.stop()


async def test_delete_user_existing(config_with_3_users):
    """
    Тест: Удаление существующего пользователя
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    initial_len = len(buffer.buffer_storage[node_proto_id])
    assert initial_len == 3
    assert "uuid-existing-1" in buffer.buffer_storage[node_proto_id]

    user_to_delete = buffer.buffer_storage[node_proto_id]["uuid-existing-1"]
    success, status_code, msg = await buffer.delete_user(node_proto_id=node_proto_id, user_obj=user_to_delete)
    assert success is True
    assert status_code == 200
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    assert "uuid-existing-1" not in buffer.buffer_storage[node_proto_id]

    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    operation = await queue.get()
    assert operation == {'op': 'delete', 'uuid': 'uuid-existing-1'}
    await buffer.stop()


async def test_delete_user_nonexistent(config_with_3_users):
    """
    Тест: IDEMPOTENCY - удаление несуществующего пользователя
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    initial_len = len(buffer.buffer_storage[node_proto_id])
    queue = buffer.node_queues[node_proto_id]
    while not queue.empty():
        await queue.get()

    nonexistent_user = create_test_user(email="nonexistent@test.com", uuid="uuid-nonexistent", as_superuser=True)
    success, status_code, msg = await buffer.delete_user(node_proto_id=node_proto_id, user_obj=nonexistent_user)
    assert success is True
    assert status_code == 200
    assert "уже не было" in msg.lower()
    assert len(buffer.buffer_storage[node_proto_id]) == initial_len
    assert queue.qsize() == 0
    await buffer.stop()


async def test_delete_user_from_empty_buffer(empty_config):
    """
    Тест: Удаление из пустого буфера
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(empty_config)))
    assert len(buffer.buffer_storage[node_proto_id]) == 0

    nonexistent_user = create_test_user(email="nonexistent@test.com", uuid="uuid-nonexistent", as_superuser=True)
    success, status_code, _ = await buffer.delete_user(node_proto_id=node_proto_id, user_obj=nonexistent_user)
    assert success is True
    assert status_code == 200
    assert len(buffer.buffer_storage[node_proto_id]) == 0
    assert buffer.node_queues[node_proto_id].qsize() == 0
    await buffer.stop()


# ========== Тесты bulk_action() ==========


async def test_bulk_action_unregistered_node():
    """
    Тест: Bulk операция на незарегистрированной ноде -> NodeNotRegisteredError
    """
    buffer = ConfigWriteBuffer()
    users = [create_test_user(email="user@test.com", uuid="u1", as_superuser=True)]
    with pytest.raises(NodeNotRegisteredError) as exc_info:
        await buffer.bulk_action(node_proto_id=999, users=users, action="add")
    assert exc_info.value.node_proto_id == 999
    await buffer.stop()


async def test_bulk_action_add_small_batch(config_with_3_users):
    """
    Тест: Bulk добавление малого количества (< max_batch)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    new_users = [
        create_test_user(email=f"bulk{i}@test.com", uuid=f"uuid-bulk-{i}", as_superuser=True) for i in range(5)
    ]
    success, msg = await buffer.bulk_action(node_proto_id=node_proto_id, users=new_users, action="add")
    assert success is True
    assert "выполнена" in msg.lower()
    assert len(buffer.buffer_storage[node_proto_id]) == 8
    for i in range(5):
        assert f"uuid-bulk-{i}" in buffer.buffer_storage[node_proto_id]
    assert buffer.node_queues[node_proto_id].qsize() == 5
    await buffer.stop()


async def test_bulk_action_add_large_batch(config_with_3_users):
    """
    Тест: Bulk добавление большого количества (>= max_batch)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    new_users = [
        create_test_user(email=f"bulk{i}@test.com", uuid=f"uuid-bulk-{i}", as_superuser=True) for i in range(20)
    ]
    success, _ = await buffer.bulk_action(node_proto_id=node_proto_id, users=new_users, action="add")
    assert success is True
    assert len(buffer.buffer_storage[node_proto_id]) == 23
    for i in range(20):
        assert f"uuid-bulk-{i}" in buffer.buffer_storage[node_proto_id]
    await buffer.stop()


async def test_bulk_action_delete_users(config_with_3_users):
    """
    Тест: Bulk удаление пользователей
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_3_users))
    )

    users_to_delete = [
        create_test_user(email="existing1@test.com", uuid="uuid-existing-1", as_superuser=True),
        create_test_user(email="existing2@test.com", uuid="uuid-existing-2", as_superuser=True),
    ]
    success, _ = await buffer.bulk_action(node_proto_id=node_proto_id, users=users_to_delete, action="delete")
    assert success is True
    assert len(buffer.buffer_storage[node_proto_id]) == 1
    assert "uuid-existing-1" not in buffer.buffer_storage[node_proto_id]
    assert "uuid-existing-2" not in buffer.buffer_storage[node_proto_id]
    assert "uuid-existing-3" in buffer.buffer_storage[node_proto_id]
    await buffer.stop()


# ========== Тесты read_config_json() и dump_config() ==========


async def test_read_config_json_and_dump_config(empty_config):
    """
    Тест: Вспомогательные методы чтения и сериализации конфига через буфер
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    await buffer.register_node(create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(empty_config)))

    raw_json = '{"inbounds": [{"port": 443}]}'
    parsed = buffer.read_config_json(node_proto_id, raw_json)
    assert isinstance(parsed, dict)
    assert parsed["inbounds"][0]["port"] == 443

    dumped_bytes = buffer.dump_config(node_proto_id, parsed)
    assert isinstance(dumped_bytes, bytes)
    assert b"443" in dumped_bytes

    await buffer.stop()
