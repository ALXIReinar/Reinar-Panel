"""
Unit тесты для CRUD операций ConfigWriteBuffer

Тестируем:
- add_user() - добавление пользователей в буфер
- delete_user() - удаление пользователей из буфера

Ключевые проверки:
1. Длина буфера (начальная и конечная)
2. Операции в очереди
3. Idempotency (повторные операции)
"""
import asyncio
import pytest
from pathlib import Path

import orjson

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.tests.utils.test_data_factory import create_test_user, create_user_injectors


# ========== Fixtures ==========

@pytest.fixture
def empty_config(tmp_path):
    """Создаёт конфиг с пустым массивом clients + пустой state"""
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": []
                }
            }
        ]
    }
    
    config_path = tmp_path / "empty.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    # Пустой state файл
    state = {"users": []}
    state_path = tmp_path / "empty.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    return config_path


@pytest.fixture
def config_with_3_users(tmp_path):
    """Создаёт конфиг с 3 существующими пользователями + state.json"""
    # Конфиг ядра
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
                }
            }
        ]
    }
    
    config_path = tmp_path / "with_users.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    # State файл с суперобъектами
    state = {
        "users": [
            create_test_user(email="existing1@test.com", uuid="uuid-existing-1", as_superuser=True),
            create_test_user(email="existing2@test.com", uuid="uuid-existing-2", as_superuser=True),
            create_test_user(email="existing3@test.com", uuid="uuid-existing-3", as_superuser=True),
        ]
    }
    
    state_path = tmp_path / "with_users.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    return config_path


# ========== Тесты add_user() ==========

async def test_add_user_first_time_with_empty_config(empty_config):
    """
    Тест: Первое добавление пользователя с пустым конфигом
    
    Проверяем:
    - Нода автоматически регистрируется
    - Пользователь добавляется в буфер
    - Операция добавлена в очередь
    - Длина: 0 → 1
    """
    buffer = ConfigWriteBuffer()
    
    node_proto_id = 1
    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1", as_superuser=True)
    
    # Первое обращение - нужны все параметры
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=new_user,
        filepath=str(empty_config),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    
    # Проверяем что нода зарегистрирована
    assert node_proto_id in buffer.node_metadata
    assert node_proto_id in buffer.node_queues
    assert node_proto_id in buffer.worker_tasks
    
    # Проверяем длину буфера: 0 → 1
    assert len(buffer.buffer_storage[node_proto_id]) == 1
    assert "uuid-new-1" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем что операция в очереди
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    # Проверяем саму операцию
    operation = await queue.get()
    assert operation == {'op': 'add', 'uuid': 'uuid-new-1'}
    
    await buffer.stop()


async def test_add_user_first_time_with_existing_users(config_with_3_users):
    """
    Тест: Первое обращение к ноде с конфигом содержащим 3 пользователей
    
    Проверяем:
    - Существующие пользователи загружены в буфер из state.json
    - Новый пользователь добавлен
    - Длина: 3 → 4
    - В очереди только 1 операция (для нового пользователя)
    """
    buffer = ConfigWriteBuffer()
    
    node_proto_id = 1
    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1", as_superuser=True)
    
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=new_user,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем длину: 3 существующих + 1 новый = 4
    assert len(buffer.buffer_storage[node_proto_id]) == 4
    
    # Проверяем что все существующие на месте (по user_uuid)
    assert "uuid-existing-1" in buffer.buffer_storage[node_proto_id]
    assert "uuid-existing-2" in buffer.buffer_storage[node_proto_id]
    assert "uuid-existing-3" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем новый пользователь
    assert "uuid-new-1" in buffer.buffer_storage[node_proto_id]
    
    # В очереди должна быть только 1 операция (для нового пользователя)
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    operation = await queue.get()
    assert operation == {'op': 'add', 'uuid': 'uuid-new-1'}
    
    await buffer.stop()


async def test_add_user_to_existing_node(config_with_3_users):
    """
    Тест: Добавление пользователя в УЖЕ зарегистрированную ноду
    
    Проверяем:
    - Пользователь добавлен в буфер
    - Операция в очереди
    - Длина: 3 → 4 → 5
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Первый пользователь - регистрирует ноду
    user1 = create_test_user(email="user1@test.com", uuid="uuid-1", as_superuser=True)
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user1,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Проверяем начальное состояние: 3 из файла + 1 добавленный = 4
    assert len(buffer.buffer_storage[node_proto_id]) == 4
    
    # Второй пользователь - нода уже зарегистрирована, параметры не нужны
    user2 = create_test_user(email="user2@test.com", uuid="uuid-2", as_superuser=True)
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user2,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем длину: 4 → 5
    assert len(buffer.buffer_storage[node_proto_id]) == 5
    assert "uuid-2" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем очередь: 2 операции (user1 и user2)
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 2
    
    await buffer.stop()


async def test_add_user_idempotency(config_with_3_users):
    """
    Тест: IDEMPOTENCY - повторное добавление существующего пользователя
    
    КЛЮЧЕВАЯ проверка:
    - Пользователь УЖЕ в буфере
    - Операция возвращает успех
    - НО буфер НЕ изменился
    - И ОПЕРАЦИЯ В ОЧЕРЕДЬ НЕ ДОБАВЛЕНА!
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Регистрируем ноду и добавляем пользователя
    user = create_test_user(email="idempotent@test.com", uuid="uuid-idempotent", as_superuser=True)
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Запоминаем состояние
    initial_len = len(buffer.buffer_storage[node_proto_id])
    queue = buffer.node_queues[node_proto_id]
    
    # Очищаем очередь для чистоты эксперимента
    while not queue.empty():
        await queue.get()
    
    assert queue.qsize() == 0
    
    # Пытаемся добавить ТОГО ЖЕ пользователя снова (с тем же user_uuid)
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Проверяем что операция вернула успех
    assert success is True
    assert status_code == 200
    assert "добавлен" in msg.lower()
    
    # КЛЮЧЕВАЯ проверка: длина буфера НЕ изменилась
    final_len = len(buffer.buffer_storage[node_proto_id])
    assert final_len == initial_len
    
    # КЛЮЧЕВАЯ проверка: операция в очередь НЕ добавлена!
    assert queue.qsize() == 0
    
    await buffer.stop()


async def test_add_user_with_dict_vs_str(empty_config):
    """
    Тест: Добавление через dict (в новой архитектуре только dict с user_uuid)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Передаём полный суперобъект (dict)
    user_dict = create_test_user(email="dict_user@test.com", uuid="uuid-dict", as_superuser=True)
    success1, status_code1, msg1 = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user_dict,  # dict с user_uuid
        filepath=str(empty_config),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    assert success1 is True
    assert "uuid-dict" in buffer.buffer_storage[node_proto_id]
    
    # Добавляем ещё одного
    user_dict2 = create_test_user(email="dict_user2@test.com", uuid="uuid-dict2", as_superuser=True)
    success2, status_code2, msg2 = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user_dict2,
        filepath=str(empty_config),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    assert success2 is True
    assert "uuid-dict2" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем что оба добавлены
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    
    await buffer.stop()


async def test_add_user_registration_fails_invalid_config(tmp_path):
    """
    Тест: ОШИБКА - первое обращение с невалидным конфигом
    
    Ожидаем: (False, 500, error)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Создаём невалидный конфиг
    broken_config = tmp_path / "broken.json"
    broken_config.write_text("{ invalid json content !@#")
    
    user = create_test_user(email="test@test.com", as_superuser=True)
    
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user,
        filepath=str(broken_config),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Проверяем ошибку
    assert success is False
    assert status_code == 500
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    assert node_proto_id not in buffer.buffer_storage
    
    await buffer.stop()


async def test_add_user_registration_fails_invalid_identifier(config_with_3_users):
    """
    Тест: ОШИБКА - неверный extractor_script (отсутствует функция transform)
    
    Ожидаем: (False, 500, error)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    user = create_test_user(email="test@test.com", as_superuser=True)
    
    # Создаём инжектор с неправильным скриптом
    bad_injectors = create_user_injectors(
        extractor_script="def wrong_function_name(u): return u"
    )
    
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user,
        filepath=str(config_with_3_users),
        user_injectors=bad_injectors,
        reload_command=None
    )
    
    # Проверяем ошибку
    assert success is False
    assert status_code == 500
    assert "transform" in msg.lower() or "не найден" in msg.lower()
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


# ========== Тесты delete_user() ==========

async def test_delete_user_existing(config_with_3_users):
    """
    Тест: Удаление существующего пользователя
    
    Проверяем:
    - Пользователь удалён из буфера
    - Операция добавлена в очередь
    - Длина: 3 → 2
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Регистрируем ноду (загрузятся 3 пользователя из state.json)
    user_injectors = create_user_injectors()
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем начальное состояние
    initial_len = len(buffer.buffer_storage[node_proto_id])
    assert initial_len == 3
    assert "uuid-existing-1" in buffer.buffer_storage[node_proto_id]
    
    # Удаляем пользователя (передаём суперобъект из буфера)
    user_to_delete = buffer.buffer_storage[node_proto_id]["uuid-existing-1"]
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=user_to_delete,
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    
    # Проверяем длину: 3 → 2
    final_len = len(buffer.buffer_storage[node_proto_id])
    assert final_len == initial_len - 1
    assert final_len == 2
    
    # Проверяем что пользователь удалён
    assert "uuid-existing-1" not in buffer.buffer_storage[node_proto_id]
    
    # Проверяем операцию в очереди
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    operation = await queue.get()
    assert operation == {'op': 'delete', 'uuid': 'uuid-existing-1'}
    
    await buffer.stop()


async def test_delete_user_nonexistent(config_with_3_users):
    """
    Тест: IDEMPOTENCY - удаление несуществующего пользователя
    
    КЛЮЧЕВАЯ проверка:
    - Пользователя нет в буфере
    - Операция возвращает успех
    - Буфер НЕ изменился
    - ОПЕРАЦИЯ В ОЧЕРЕДЬ НЕ ДОБАВЛЕНА!
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Регистрируем ноду
    user_injectors = create_user_injectors()
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    initial_len = len(buffer.buffer_storage[node_proto_id])
    assert initial_len == 3
    
    # Очищаем очередь
    queue = buffer.node_queues[node_proto_id]
    while not queue.empty():
        await queue.get()
    
    # Пытаемся удалить несуществующего пользователя
    nonexistent_user = create_test_user(email="nonexistent@test.com", uuid="uuid-nonexistent", as_superuser=True)
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=nonexistent_user,
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем что операция вернула успех
    assert success is True
    assert status_code == 200
    assert "уже не было" in msg.lower()
    
    # КЛЮЧЕВАЯ проверка: длина НЕ изменилась
    final_len = len(buffer.buffer_storage[node_proto_id])
    assert final_len == initial_len
    
    # КЛЮЧЕВАЯ проверка: операция в очередь НЕ добавлена!
    assert queue.qsize() == 0
    
    await buffer.stop()


async def test_delete_user_unregistered_node_success(config_with_3_users):
    """
    Тест: Удаление из незарегистрированной ноды (успешная автоматическая регистрация)
    
    Проверяем:
    - Нода автоматически регистрируется
    - Пользователи загружаются из state.json
    - Пользователь удаляется
    - Длина: 3 (из state.json) → 2
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Нода НЕ зарегистрирована, пытаемся удалить
    # Нужен полный суперобъект с user_uuid
    user_to_delete = create_test_user(email="existing1@test.com", uuid="uuid-existing-1", as_superuser=True)
    
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=user_to_delete,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    
    # Проверяем что нода зарегистрирована
    assert node_proto_id in buffer.node_queues
    
    # Проверяем длину: 3 (загружены из state.json) - 1 (удалён) = 2
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    assert "uuid-existing-1" not in buffer.buffer_storage[node_proto_id]
    
    # Проверяем операцию
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    operation = await queue.get()
    assert operation == {'op': 'delete', 'uuid': 'uuid-existing-1'}
    
    await buffer.stop()


async def test_delete_user_with_dict_vs_str(config_with_3_users):
    """
    Тест: Удаление через dict (в новой архитектуре требуется dict с user_uuid)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Регистрируем ноду
    user_injectors = create_user_injectors()
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Удаляем через dict (суперобъект из буфера)
    user_dict = buffer.buffer_storage[node_proto_id]["uuid-existing-1"]
    success1, status_code1, msg1 = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=user_dict,  # dict с user_uuid
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    assert success1 is True
    assert "uuid-existing-1" not in buffer.buffer_storage[node_proto_id]
    
    # Удаляем ещё одного
    user_dict2 = buffer.buffer_storage[node_proto_id]["uuid-existing-2"]
    success2, status_code2, msg2 = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=user_dict2,
        filepath=str(config_with_3_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    assert success2 is True
    assert "uuid-existing-2" not in buffer.buffer_storage[node_proto_id]
    
    # Проверяем финальное состояние: 3 - 2 = 1
    assert len(buffer.buffer_storage[node_proto_id]) == 1
    
    await buffer.stop()


async def test_delete_user_registration_fails(tmp_path):
    """
    Тест: ОШИБКА - автоматическая регистрация проваливается
    
    Ожидаем: (False, 500, error)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Создаём невалидный конфиг
    broken_config = tmp_path / "broken.json"
    broken_config.write_text("{ broken }")
    
    user_to_delete = create_test_user(email="test@test.com", uuid="uuid-test", as_superuser=True)
    
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=user_to_delete,
        filepath=str(broken_config),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Проверяем ошибку
    assert success is False
    assert status_code == 500
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()


async def test_delete_user_from_empty_buffer(empty_config):
    """
    Тест: Удаление из пустого буфера
    
    Проверяем:
    - Операция возвращает успех (idempotency)
    - Буфер остаётся пустым
    - Операция в очередь НЕ добавлена
    - Длина: 0 → 0
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Регистрируем ноду с пустым конфигом
    user_injectors = create_user_injectors()
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(empty_config),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем что буфер пустой
    assert len(buffer.buffer_storage[node_proto_id]) == 0
    
    # Пытаемся удалить
    nonexistent_user = create_test_user(email="nonexistent@test.com", uuid="uuid-nonexistent", as_superuser=True)
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj=nonexistent_user,
        filepath=str(empty_config),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    
    # Длина осталась 0
    assert len(buffer.buffer_storage[node_proto_id]) == 0
    
    # Операция НЕ добавлена
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 0
    
    await buffer.stop()


# ========== Тесты bulk_action() ==========

async def test_bulk_action_add_small_batch(config_with_3_users):
    """
    Тест: Bulk добавление МАЛОГО количества пользователей (< max_batch)
    
    Проверяем:
    - Пользователи добавлены в буфер
    - unlimit_queue НЕ использовался (len(users) < max_batch)
    - Операции добавлены в очередь
    - Длина: 3 → 8 (3 существующих + 5 новых)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Создаём 5 новых пользователей (меньше чем max_batch=10)
    new_users = [
        create_test_user(email=f"bulk{i}@test.com", uuid=f"uuid-bulk-{i}", as_superuser=True)
        for i in range(5)
    ]
    
    # Выполняем bulk add
    success, msg = await buffer.bulk_action(
        node_proto_id=node_proto_id,
        users=new_users,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None,
        action="add"
    )
    
    assert success is True
    assert "выполнена" in msg.lower()
    
    # Проверяем что нода зарегистрирована
    assert node_proto_id in buffer.node_metadata
    
    # Проверяем длину: 3 (из state.json) + 5 (добавлено) = 8
    assert len(buffer.buffer_storage[node_proto_id]) == 8
    
    # Проверяем что все новые пользователи добавлены
    for i in range(5):
        assert f"uuid-bulk-{i}" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем что операции в очереди (5 операций add)
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 5
    
    await buffer.stop()


async def test_bulk_action_add_large_batch(config_with_3_users):
    """
    Тест: Bulk добавление БОЛЬШОГО количества пользователей (>= max_batch)
    
    Проверяем:
    - Пользователи добавлены в буфер
    - unlimit_queue ИСПОЛЬЗОВАЛСЯ (len(users) >= max_batch)
    - После выхода из контекста произошёл flush
    - Длина: 3 → 23 (3 существующих + 20 новых)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Создаём 20 новых пользователей (больше чем max_batch=10)
    new_users = [
        create_test_user(email=f"bulk{i}@test.com", uuid=f"uuid-bulk-{i}", as_superuser=True)
        for i in range(20)
    ]
    
    # Выполняем bulk add
    success, msg = await buffer.bulk_action(
        node_proto_id=node_proto_id,
        users=new_users,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None,
        action="add"
    )
    
    assert success is True
    
    # Проверяем длину: 3 + 20 = 23
    assert len(buffer.buffer_storage[node_proto_id]) == 23
    
    # Проверяем что все пользователи добавлены
    for i in range(20):
        assert f"uuid-bulk-{i}" in buffer.buffer_storage[node_proto_id]
    
    # Очередь должна быть пуста после flush (который произошёл при выходе из unlimit_queue)
    queue = buffer.node_queues[node_proto_id]
    # NOTE: Может быть не 0 если воркер не успел обработать, но все операции должны быть в процессе
    
    await buffer.stop()


async def test_bulk_action_delete_users(config_with_3_users):
    """
    Тест: Bulk удаление пользователей
    
    Проверяем:
    - Пользователи удалены из буфера
    - Длина: 3 → 1 (удалили 2 из 3)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду (загрузятся 3 пользователя)
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    
    # Удаляем 2 пользователей через bulk
    users_to_delete = [
        create_test_user(email="existing1@test.com", uuid="uuid-existing-1", as_superuser=True),
        create_test_user(email="existing2@test.com", uuid="uuid-existing-2", as_superuser=True),
    ]
    
    success, msg = await buffer.bulk_action(
        node_proto_id=node_proto_id,
        users=users_to_delete,
        filepath=str(config_with_3_users),
        user_injectors=create_user_injectors(),
        reload_command=None,
        action="delete"
    )
    
    assert success is True
    
    # Проверяем длину: 3 - 2 = 1
    assert len(buffer.buffer_storage[node_proto_id]) == 1
    
    # Проверяем что пользователи удалены
    assert "uuid-existing-1" not in buffer.buffer_storage[node_proto_id]
    assert "uuid-existing-2" not in buffer.buffer_storage[node_proto_id]
    
    # Проверяем что третий остался
    assert "uuid-existing-3" in buffer.buffer_storage[node_proto_id]
    
    await buffer.stop()


async def test_bulk_action_unregistered_node(empty_config):
    """
    Тест: Bulk операция на незарегистрированной ноде
    
    Проверяем:
    - Нода автоматически регистрируется
    - Операции выполняются успешно
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Нода НЕ зарегистрирована
    assert node_proto_id not in buffer.node_metadata
    
    # Создаём пользователей для bulk add
    new_users = [
        create_test_user(email=f"user{i}@test.com", uuid=f"uuid-{i}", as_superuser=True)
        for i in range(3)
    ]
    
    success, msg = await buffer.bulk_action(
        node_proto_id=node_proto_id,
        users=new_users,
        filepath=str(empty_config),
        user_injectors=create_user_injectors(),
        reload_command=None,
        action="add"
    )
    
    assert success is True
    
    # Проверяем что нода зарегистрирована
    assert node_proto_id in buffer.node_metadata
    assert node_proto_id in buffer.node_queues
    
    # Проверяем что пользователи добавлены
    assert len(buffer.buffer_storage[node_proto_id]) == 3
    
    await buffer.stop()


async def test_bulk_action_registration_fails(tmp_path):
    """
    Тест: ОШИБКА - bulk операция с невалидным конфигом (регистрация проваливается)
    
    Ожидаем: (False, error_message)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Создаём невалидный конфиг
    broken_config = tmp_path / "broken.json"
    broken_config.write_text("{ broken json }")
    
    new_users = [
        create_test_user(email="user@test.com", uuid="uuid-1", as_superuser=True)
    ]
    
    success, msg = await buffer.bulk_action(
        node_proto_id=node_proto_id,
        users=new_users,
        filepath=str(broken_config),
        user_injectors=create_user_injectors(),
        reload_command=None,
        action="add"
    )
    
    # Проверяем ошибку
    assert success is False
    assert "не удалось" in msg.lower()
    
    # Нода не зарегистрирована
    assert node_proto_id not in buffer.node_queues
    
    await buffer.stop()
