"""
Unit тесты для воркеров и батчинга ConfigWriteBuffer

Тестируем:
- _node_worker() - триггеры батчинга (max_batch, timeout)
- Флаг queue_limited - влияние на запись (теперь per-node)
- Изоляция воркеров между нодами
"""

import asyncio
import pytest
import orjson
from pathlib import Path

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.tests.utils.test_data_factory import create_test_user, create_user_injectors


# ========== Fixtures ==========

@pytest.fixture
def config_with_2_users(tmp_path):
    """Конфиг с 2 пользователями + state.json"""
    # Конфиг ядра
    config = {
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [
                    create_test_user(email="existing1@test.com", uuid="uuid-ex1", as_superuser=False),
                    create_test_user(email="existing2@test.com", uuid="uuid-ex2", as_superuser=False),
                ]
            }
        }]
    }
    config_path = tmp_path / "config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    # State файл
    state = {
        "users": [
            create_test_user(email="existing1@test.com", uuid="uuid-ex1", as_superuser=True),
            create_test_user(email="existing2@test.com", uuid="uuid-ex2", as_superuser=True),
        ]
    }
    state_path = tmp_path / "config.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    return config_path


def read_config_users(config_path: Path) -> list:
    """Читает список пользователей из конфига ядра"""
    content = orjson.loads(config_path.read_bytes())
    return content["inbounds"][0]["settings"]["clients"]


# ========== Группа 1: Воркеры и батчинг ==========

@pytest.mark.slow
async def test_worker_triggers_on_max_batch(config_with_2_users):
    """
    Тест: Воркер записывает на диск при достижении max_batch
    
    Сценарий:
    - max_batch=5, timeout=10 (большой, чтобы не сработал)
    - Добавляем 6 пользователей быстро
    - Первые 5 триггерят батч → воркер записывает
    - 6-й остаётся в очереди
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=2.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду (2 пользователя загрузятся из state.json)
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Добавляем первые 5 пользователей (достигаем max_batch)
    for i in range(5):
        user = create_test_user(email=f"batch_user_{i}@test.com", uuid=f"uuid-batch-{i}", as_superuser=True)
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj=user,
            filepath=str(config_with_2_users),
            user_injectors=user_injectors,
            reload_command=None
        )
    
    # Даём время воркеру начать обработку первого батча
    await asyncio.sleep(0.3)
    
    # Теперь добавляем 6-го пользователя
    user6 = create_test_user(email="batch_user_5@test.com", uuid="uuid-batch-5", as_superuser=True)
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj=user6,
        filepath=str(config_with_2_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # В очереди должна быть 1 операция (6-й пользователь)
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1
    
    # Даём время воркеру завершить запись первого батча и обработать 6-ю операцию
    await asyncio.sleep(2.5)
    
    # Проверяем что данные записались на диск
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 8  # 2 начальных + 6 добавленных
    
    # Проверяем что все пользователи на месте
    emails_on_disk = {u["email"] for u in users_on_disk}
    for i in range(6):
        assert f"batch_user_{i}@test.com" in emails_on_disk
    
    await buffer.stop()


@pytest.mark.slow
async def test_worker_triggers_on_timeout(config_with_2_users):
    """
    Тест: Воркер записывает на диск по истечению timeout
    
    Сценарий:
    - max_batch=10 (большой, чтобы не сработал), timeout=1.0
    - Добавляем 2 пользователя (меньше max_batch)
    - Ждём > timeout
    - Проверяем что данные записались на диск
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=1.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Добавляем только 2 пользователя (не достигаем max_batch)
    user1 = create_test_user(email="timeout_user_1@test.com", uuid="uuid-t1", as_superuser=True)
    user2 = create_test_user(email="timeout_user_2@test.com", uuid="uuid-t2", as_superuser=True)
    
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user1, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user2, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Ждём больше чем timeout для срабатывания воркера
    await asyncio.sleep(1.5)
    
    # Проверяем что данные записались на диск
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 4  # 2 начальных + 2 добавленных
    
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "timeout_user_1@test.com" in emails_on_disk
    assert "timeout_user_2@test.com" in emails_on_disk
    
    await buffer.stop()


@pytest.mark.slow
async def test_worker_respects_queue_limited_flag(config_with_2_users):
    """
    Тест: Воркер НЕ записывает если queue_limited=False для конкретной ноды
    
    Сценарий:
    - Устанавливаем queue_limited=False вручную для конкретной ноды
    - Добавляем пользователей (достигаем max_batch)
    - Ждём
    - Проверяем что данные НЕ записались на диск
    - Возвращаем queue_limited=True
    - Принудительно вызываем flush
    - Проверяем что теперь данные записались
    """
    buffer = ConfigWriteBuffer(max_batch=3, timeout=1.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Отключаем лимиты очереди для конкретной ноды
    buffer.node_metadata[node_proto_id]['queue_limited'] = False
    
    # Добавляем 3 пользователя (достигаем max_batch)
    for i in range(3):
        user = create_test_user(email=f"unlimit_user_{i}@test.com", uuid=f"uuid-ul-{i}", as_superuser=True)
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj=user,
            filepath=str(config_with_2_users),
            user_injectors=user_injectors,
            reload_command=None
        )
    
    # Ждём (воркер НЕ должен записать)
    await asyncio.sleep(0.5)
    
    # Проверяем что данные НЕ записались на диск
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 2  # Только начальные, новые НЕ записались
    
    # Включаем лимиты и принудительно записываем
    buffer.node_metadata[node_proto_id]['queue_limited'] = True
    await buffer._flush_all_nodes(node_proto_id)
    
    # Теперь данные должны записаться
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 5  # 2 начальных + 3 добавленных
    
    await buffer.stop()


async def test_worker_handles_empty_queue(config_with_2_users):
    """
    Тест: Воркер корректно работает с пустой очередью
    
    Сценарий:
    - Регистрируем ноду
    - НЕ добавляем новых пользователей
    - Ждём > timeout
    - Проверяем что воркер работает, но запись не происходит
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    node_proto_id = 1
    
    # Регистрируем ноду (загружаются 2 пользователя из state.json)
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        user_injectors=create_user_injectors(),
        reload_command=None
    )
    
    # Запоминаем время изменения файла
    initial_mtime = config_with_2_users.stat().st_mtime
    
    # НЕ добавляем пользователей, ждём больше timeout
    await asyncio.sleep(1.0)
    
    # Проверяем что файл НЕ изменился
    final_mtime = config_with_2_users.stat().st_mtime
    assert initial_mtime == final_mtime
    
    # Проверяем что в буфере всё ещё 2 пользователя
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    
    # Очередь пустая
    assert buffer.node_queues[node_proto_id].qsize() == 0
    
    await buffer.stop()


@pytest.mark.slow
async def test_worker_isolation_between_nodes(tmp_path):
    """
    Тест: Изоляция воркеров - ошибка в одной ноде не влияет на другие
    
    Сценарий:
    - Создаём 2 ноды с разными конфигами
    - В ноде 1 добавляем пользователей
    - В ноде 2 также добавляем пользователей
    - Искусственно портим путь к файлу ноды 1 (эмулируем ошибку записи)
    - Проверяем что нода 2 всё равно записывает успешно
    """
    # Создаём 2 конфига
    config1 = tmp_path / "config1.json"
    config2 = tmp_path / "config2.json"
    
    for config_path in [config1, config2]:
        config = {
            "inbounds": [{
                "port": 443,
                "protocol": "vless",
                "settings": {"clients": []}
            }]
        }
        config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
        
        # State файлы
        state = {"users": []}
        state_path = Path(str(config_path) + ".state.json")
        state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    buffer = ConfigWriteBuffer(max_batch=2, timeout=1.0)
    user_injectors = create_user_injectors()
    
    # Регистрируем обе ноды
    await buffer.register_node(node_proto_id=1, filepath=str(config1), user_injectors=user_injectors, reload_command=None)
    await buffer.register_node(node_proto_id=2, filepath=str(config2), user_injectors=user_injectors, reload_command=None)
    
    # Добавляем по 2 пользователя в каждую ноду
    for i in range(2):
        user1 = create_test_user(email=f"node1_user_{i}@test.com", uuid=f"uuid-n1-{i}", as_superuser=True)
        user2 = create_test_user(email=f"node2_user_{i}@test.com", uuid=f"uuid-n2-{i}", as_superuser=True)
        
        await buffer.add_user(node_proto_id=1, user_obj=user1, filepath=str(config1), user_injectors=user_injectors, reload_command=None)
        await buffer.add_user(node_proto_id=2, user_obj=user2, filepath=str(config2), user_injectors=user_injectors, reload_command=None)
    
    # Портим путь к файлу ноды 1 (эмулируем ошибку)
    buffer.node_metadata[1]['filepath'] = str(tmp_path / "nonexistent.json")
    
    # Ждём срабатывания воркеров
    await asyncio.sleep(1.5)
    
    # Проверяем что нода 2 успешно записалась
    users_node2 = read_config_users(config2)
    assert len(users_node2) == 2
    
    emails_node2 = {u["email"] for u in users_node2}
    assert "node2_user_0@test.com" in emails_node2
    assert "node2_user_1@test.com" in emails_node2
    
    # Проверяем что воркер ноды 2 всё ещё работает
    assert not buffer.worker_tasks[2].done()
    
    await buffer.stop()


# ========== Группа 2: Запись на диск ==========

async def test_write_to_disk_success(config_with_2_users):
    """
    Тест: Успешная атомарная запись на диск
    
    Сценарий:
    - Регистрируем ноду (загружаются 2 пользователя)
    - Добавляем 3 новых пользователя в буфер
    - Принудительно вызываем _write_node_to_disk()
    - Проверяем что данные записались корректно (2 + 3 = 5)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        user_injectors=user_injectors,
        reload_command=None
    )
    
    # Добавляем 3 пользователей в буфер (но не триггерим воркер)
    for i in range(3):
        user = create_test_user(email=f"write_user_{i}@test.com", uuid=f"uuid-w-{i}", as_superuser=True)
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj=user,
            filepath=str(config_with_2_users),
            user_injectors=user_injectors,
            reload_command=None
        )
    
    # Проверяем что в буфере 5 пользователей
    assert len(buffer.buffer_storage[node_proto_id]) == 5
    
    # Принудительно записываем на диск
    await buffer._write_node_to_disk(node_proto_id)
    
    # Проверяем результат на диске
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 5
    
    # Проверяем что все пользователи на месте
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "existing1@test.com" in emails_on_disk
    assert "existing2@test.com" in emails_on_disk
    for i in range(3):
        assert f"write_user_{i}@test.com" in emails_on_disk
    
    await buffer.stop()


async def test_write_preserves_file_structure(tmp_path):
    """
    Тест: Запись сохраняет структуру конфиг-файла
    
    Сценарий:
    - Создаём конфиг с дополнительными полями (log, routing, etc)
    - Регистрируем ноду
    - Добавляем пользователей
    - Записываем на диск
    - Проверяем что все поля сохранились
    """
    # Конфиг ядра с расширенной структурой
    config = {
        "log": {"loglevel": "info", "access": "/var/log/access.log"},
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "tag": "main-inbound",
            "settings": {
                "clients": [
                    create_test_user(email="original@test.com", uuid="uuid-orig", as_superuser=False)
                ],
                "decryption": "none"
            },
            "streamSettings": {"network": "tcp", "security": "tls"}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
        "routing": {"rules": [{"type": "field", "outboundTag": "direct"}]}
    }
    
    config_path = tmp_path / "complex_config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    # State файл
    state = {
        "users": [create_test_user(email="original@test.com", uuid="uuid-orig", as_superuser=True)]
    }
    state_path = tmp_path / "complex_config.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_path), user_injectors=user_injectors, reload_command=None)
    
    # Добавляем пользователя
    new_user = create_test_user(email="new@test.com", uuid="uuid-new", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=new_user, filepath=str(config_path), user_injectors=user_injectors, reload_command=None)
    
    # Записываем на диск
    await buffer._write_node_to_disk(node_proto_id)
    
    # Читаем полный конфиг
    full_config = orjson.loads(config_path.read_bytes())
    
    # Проверяем что ВСЕ поля сохранились
    assert "log" in full_config
    assert full_config["log"]["loglevel"] == "info"
    
    assert "outbounds" in full_config
    assert full_config["outbounds"][0]["protocol"] == "freedom"
    
    assert "routing" in full_config
    
    # Проверяем inbound структуру
    inbound = full_config["inbounds"][0]
    assert inbound["port"] == 443
    assert inbound["tag"] == "main-inbound"
    assert "streamSettings" in inbound
    
    # Проверяем что clients обновились
    clients = inbound["settings"]["clients"]
    assert len(clients) == 2
    emails = {c["email"] for c in clients}
    assert "original@test.com" in emails
    assert "new@test.com" in emails
    
    await buffer.stop()


async def test_write_with_reload_command(config_with_2_users, tmp_path):
    """
    Тест: Запись с выполнением команды перезагрузки
    """
    marker_file = tmp_path / "reload_marker.txt"
    reload_command = f'echo Reloaded > "{marker_file}"'
    
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду с командой перезагрузки
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        user_injectors=user_injectors,
        reload_command=reload_command
    )
    
    # Добавляем пользователя
    user = create_test_user(email="reload_test@test.com", uuid="uuid-reload", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=reload_command)
    
    # Проверяем что маркера ещё нет
    assert not marker_file.exists()
    
    # Записываем на диск (должна выполниться команда перезагрузки)
    await buffer._write_node_to_disk(node_proto_id)
    
    # Даём время команде выполниться
    await asyncio.sleep(0.5)
    
    # Проверяем что команда выполнилась
    assert marker_file.exists()
    content = marker_file.read_text().strip()
    assert "Reloaded" in content
    
    await buffer.stop()


async def test_write_without_reload_command(config_with_2_users):
    """
    Тест: Запись без команды перезагрузки
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду БЕЗ команды перезагрузки
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Добавляем пользователя
    user = create_test_user(email="no_reload@test.com", uuid="uuid-noreload", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Записываем на диск
    await buffer._write_node_to_disk(node_proto_id)
    
    # Проверяем что данные записались
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 3  # 2 начальных + 1 добавленный
    
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "no_reload@test.com" in emails_on_disk
    
    await buffer.stop()


# ========== Группа 3: Unlimit режим (bulk операции) ==========

async def test_unlimit_queue_disables_limits(config_with_2_users):
    """
    Тест: unlimit_queue() устанавливает queue_limited=False для конкретной ноды
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Изначально True
    assert buffer.node_metadata[node_proto_id]['queue_limited'] is True
    
    # Входим в контекст
    async with buffer.unlimit_queue(node_proto_id):
        # Внутри контекста должно быть False
        assert buffer.node_metadata[node_proto_id]['queue_limited'] is False
    
    # После выхода восстановлено в True
    assert buffer.node_metadata[node_proto_id]['queue_limited'] is True
    
    await buffer.stop()


@pytest.mark.slow
async def test_unlimit_queue_flushes_on_exit(config_with_2_users):
    """
    Тест: unlimit_queue() принудительно записывает при выходе из контекста
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Используем unlimit режим
    async with buffer.unlimit_queue(node_proto_id):
        # Добавляем 3 пользователя (не достигаем max_batch=10)
        for i in range(3):
            user = create_test_user(email=f"unlimit_{i}@test.com", uuid=f"uuid-ul-{i}", as_superuser=True)
            await buffer.add_user(node_proto_id=node_proto_id, user_obj=user, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # После выхода из контекста данные ДОЛЖНЫ записаться
    await asyncio.sleep(0.3)
    
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 5  # 2 начальных + 3 добавленных
    
    emails_on_disk = {u["email"] for u in users_on_disk}
    for i in range(3):
        assert f"unlimit_{i}@test.com" in emails_on_disk
    
    await buffer.stop()


async def test_unlimit_queue_restores_flag(config_with_2_users):
    """
    Тест: unlimit_queue() восстанавливает флаг queue_limited после выхода
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Изначально True
    assert buffer.node_metadata[node_proto_id]['queue_limited'] is True
    
    # Сценарий 1: Нормальный выход
    async with buffer.unlimit_queue(node_proto_id):
        assert buffer.node_metadata[node_proto_id]['queue_limited'] is False
    
    assert buffer.node_metadata[node_proto_id]['queue_limited'] is True
    
    # Сценарий 2: Выход через исключение
    try:
        async with buffer.unlimit_queue(node_proto_id):
            assert buffer.node_metadata[node_proto_id]['queue_limited'] is False
            raise ValueError("Тестовое исключение")
    except ValueError:
        pass
    
    # Флаг всё равно должен восстановиться
    assert buffer.node_metadata[node_proto_id]['queue_limited'] is True
    
    await buffer.stop()


@pytest.mark.slow
async def test_bulk_operations_without_intermediate_writes(config_with_2_users):
    """
    Тест: Массовое добавление в unlimit режиме без промежуточных записей
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=2.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Запоминаем время изменения файла
    initial_mtime = config_with_2_users.stat().st_mtime
    
    # Используем unlimit режим
    async with buffer.unlimit_queue(node_proto_id):
        # Добавляем 20 пользователей
        for i in range(20):
            user = create_test_user(email=f"bulk_{i}@test.com", uuid=f"uuid-bulk-{i}", as_superuser=True)
            await buffer.add_user(node_proto_id=node_proto_id, user_obj=user, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
        
        # Ждём больше чем timeout
        await asyncio.sleep(2.5)
        
        # Файл НЕ должен измениться (промежуточных записей не было)
        mid_mtime = config_with_2_users.stat().st_mtime
        assert initial_mtime == mid_mtime
    
    # После выхода данные должны записаться
    await asyncio.sleep(0.3)
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 22  # 2 начальных + 20 добавленных
    
    await buffer.stop()


# ========== Группа 4: Остановка и cleanup ==========

async def test_stop_cancels_all_workers(tmp_path):
    """
    Тест: stop() корректно останавливает все воркеры
    """
    # Создаём 3 конфига
    configs = []
    for i in range(3):
        config_path = tmp_path / f"config_{i}.json"
        config = {"inbounds": [{"port": 443 + i, "protocol": "vless", "settings": {"clients": []}}]}
        config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
        
        state_path = tmp_path / f"config_{i}.json.state.json"
        state = {"users": []}
        state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
        
        configs.append(config_path)
    
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    user_injectors = create_user_injectors()
    
    # Регистрируем 3 ноды
    for i, config_path in enumerate(configs):
        await buffer.register_node(node_proto_id=i + 1, filepath=str(config_path), user_injectors=user_injectors, reload_command=None)
    
    # Проверяем что все воркеры запущены
    for i in range(1, 4):
        assert i in buffer.worker_tasks
        assert not buffer.worker_tasks[i].done()
    
    # Останавливаем
    await buffer.stop()
    
    # Проверяем что все воркеры остановлены (done)
    for i in range(1, 4):
        assert buffer.worker_tasks[i].done()


@pytest.mark.slow
async def test_stop_flushes_pending_operations(config_with_2_users):
    """
    Тест: stop() записывает несохранённые операции на диск
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=100.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Добавляем пользователей (не достигая max_batch и не дожидаясь timeout)
    for i in range(3):
        user = create_test_user(email=f"pending_{i}@test.com", uuid=f"uuid-pend-{i}", as_superuser=True)
        await buffer.add_user(node_proto_id=node_proto_id, user_obj=user, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Вызываем stop (должен сбросить остатки)
    await buffer.stop()
    
    # Проверяем что данные записались
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 5  # 2 начальных + 3 добавленных


async def test_stop_idempotent(config_with_2_users):
    """
    Тест: Повторный вызов stop() безопасен
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    user_injectors = create_user_injectors()
    
    # Регистрируем ноду
    await buffer.register_node(node_proto_id=node_proto_id, filepath=str(config_with_2_users), user_injectors=user_injectors, reload_command=None)
    
    # Вызываем stop() три раза
    await buffer.stop()
    await buffer.stop()
    await buffer.stop()
    
    # Проверяем что не возникло исключений
    assert True
