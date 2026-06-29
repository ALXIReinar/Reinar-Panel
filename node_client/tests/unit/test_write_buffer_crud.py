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
from node_client.tests.utils.test_data_factory import create_test_user


# ========== Fixtures ==========

@pytest.fixture
def empty_config(tmp_path):
    """Создаёт конфиг с пустым массивом clients"""
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
    return config_path


@pytest.fixture
def config_with_3_users(tmp_path):
    """Создаёт конфиг с 3 существующими пользователями"""
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        create_test_user(email="existing1@test.com", uuid="uuid-existing-1"),
                        create_test_user(email="existing2@test.com", uuid="uuid-existing-2"),
                        create_test_user(email="existing3@test.com", uuid="uuid-existing-3"),
                    ]
                }
            }
        ]
    }
    
    config_path = tmp_path / "with_users.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
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
    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1")
    
    # Первое обращение - нужны все параметры
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=new_user,
        filepath=str(empty_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
    assert "new@test.com" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем что операция в очереди
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    # Проверяем саму операцию
    operation = await queue.get()
    assert operation == {'op': 'add', 'uuid': 'new@test.com'}
    
    await buffer.stop()


async def test_add_user_first_time_with_existing_users(config_with_3_users):
    """
    Тест: Первое обращение к ноде с конфигом содержащим 3 пользователей
    
    Проверяем:
    - Существующие пользователи загружены в буфер
    - Новый пользователь добавлен
    - Длина: 3 → 4
    - В очереди только 1 операция (для нового пользователя)
    """
    buffer = ConfigWriteBuffer()
    
    node_proto_id = 1
    new_user = create_test_user(email="new@test.com", uuid="uuid-new-1")
    
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=new_user,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем длину: 3 существующих + 1 новый = 4
    assert len(buffer.buffer_storage[node_proto_id]) == 4
    
    # Проверяем что все существующие на месте
    assert "existing1@test.com" in buffer.buffer_storage[node_proto_id]
    assert "existing2@test.com" in buffer.buffer_storage[node_proto_id]
    assert "existing3@test.com" in buffer.buffer_storage[node_proto_id]
    
    # Проверяем новый пользователь
    assert "new@test.com" in buffer.buffer_storage[node_proto_id]
    
    # В очереди должна быть только 1 операция (для нового пользователя)
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    operation = await queue.get()
    assert operation == {'op': 'add', 'uuid': 'new@test.com'}
    
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
    user1 = create_test_user(email="user1@test.com")
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user1,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # Проверяем начальное состояние: 3 из файла + 1 добавленный = 4
    assert len(buffer.buffer_storage[node_proto_id]) == 4
    
    # Второй пользователь - нода уже зарегистрирована, но параметры всё равно нужны
    user2 = create_test_user(email="user2@test.com")
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user2,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    assert success is True
    assert status_code == 200
    
    # Проверяем длину: 4 → 5
    assert len(buffer.buffer_storage[node_proto_id]) == 5
    assert "user2@test.com" in buffer.buffer_storage[node_proto_id]
    
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
    user = create_test_user(email="idempotent@test.com")
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # Запоминаем состояние
    initial_len = len(buffer.buffer_storage[node_proto_id])
    queue = buffer.node_queues[node_proto_id]
    
    # Очищаем очередь для чистоты эксперимента
    while not queue.empty():
        await queue.get()
    
    assert queue.qsize() == 0
    
    # Пытаемся добавить ТОГО ЖЕ пользователя снова
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
    Тест: Проверка обоих способов передачи пользователя
    
    1. Через dict (полный объект пользователя)
    2. Через str (только идентификатор)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Способ 1: Передаём полный объект (dict)
    user_dict = create_test_user(email="dict_user@test.com")
    success1, status_code1, msg1 = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user_dict,  # dict
        filepath=str(empty_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    assert success1 is True
    assert "dict_user@test.com" in buffer.buffer_storage[node_proto_id]
    
    # Способ 2: Передаём только идентификатор (str)
    # Нода уже зарегистрирована, но параметры всё равно нужны
    success2, status_code2, msg2 = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="str_user@test.com",  # str
        filepath=str(empty_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    assert success2 is True
    assert "str_user@test.com" in buffer.buffer_storage[node_proto_id]
    
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
    
    user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user,
        filepath=str(broken_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
    Тест: ОШИБКА - неверный flatten_user_identifier_key
    
    Ожидаем: (False, 500, error)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    user = create_test_user(email="test@test.com")
    
    success, status_code, msg = await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="nonexistent_field",  # ОШИБКА!
        reload_command=None
    )
    
    # Проверяем ошибку
    assert success is False
    assert status_code == 500
    assert "nonexistent_field" in msg
    
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
    
    # Регистрируем ноду (загрузятся 3 пользователя)
    test_user = create_test_user(email="test@test.com")
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    # Проверяем начальное состояние
    initial_len = len(buffer.buffer_storage[node_proto_id])
    assert initial_len == 3
    assert "existing1@test.com" in buffer.buffer_storage[node_proto_id]
    
    # Удаляем пользователя
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="existing1@test.com",
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
    assert "existing1@test.com" not in buffer.buffer_storage[node_proto_id]
    
    # Проверяем операцию в очереди
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    operation = await queue.get()
    assert operation == {'op': 'delete', 'uuid': 'existing1@test.com'}
    
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
    test_user = create_test_user(email="test@test.com")
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    initial_len = len(buffer.buffer_storage[node_proto_id])
    assert initial_len == 3
    
    # Очищаем очередь
    queue = buffer.node_queues[node_proto_id]
    while not queue.empty():
        await queue.get()
    
    # Пытаемся удалить несуществующего пользователя
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="nonexistent@test.com",
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
    - Пользователи загружаются из файла
    - Пользователь удаляется
    - Длина: 3 (из файла) → 2
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Нода НЕ зарегистрирована, пытаемся удалить
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="existing1@test.com",
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # Проверяем успех
    assert success is True
    assert status_code == 200
    
    # Проверяем что нода зарегистрирована
    assert node_proto_id in buffer.node_queues
    
    # Проверяем длину: 3 (загружены из файла) - 1 (удалён) = 2
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    assert "existing1@test.com" not in buffer.buffer_storage[node_proto_id]
    
    # Проверяем операцию
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    operation = await queue.get()
    assert operation == {'op': 'delete', 'uuid': 'existing1@test.com'}
    
    await buffer.stop()


async def test_delete_user_with_dict_vs_str(config_with_3_users):
    """
    Тест: Проверка обоих способов передачи идентификатора
    
    1. Через dict (полный объект)
    2. Через str (только email)
    """
    buffer = ConfigWriteBuffer()
    node_proto_id = 1
    
    # Регистрируем ноду
    test_user = create_test_user(email="test@test.com")
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    # Способ 1: Удаляем через dict
    user_dict = buffer.buffer_storage[node_proto_id]["existing1@test.com"]
    success1, status_code1, msg1 = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=user_dict,  # dict
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    assert success1 is True
    assert "existing1@test.com" not in buffer.buffer_storage[node_proto_id]
    
    # Способ 2: Удаляем через str
    success2, status_code2, msg2 = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="existing2@test.com",  # str
        filepath=str(config_with_3_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    assert success2 is True
    assert "existing2@test.com" not in buffer.buffer_storage[node_proto_id]
    
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
    
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="test@test.com",
        filepath=str(broken_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
    test_user = create_test_user(email="test@test.com")
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(empty_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=test_user
    )
    
    # Проверяем что буфер пустой
    assert len(buffer.buffer_storage[node_proto_id]) == 0
    
    # Пытаемся удалить
    success, status_code, msg = await buffer.delete_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier="nonexistent@test.com",
        filepath=str(empty_config),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
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
