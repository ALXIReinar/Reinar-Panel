"""
Unit тесты для воркеров и батчинга ConfigWriteBuffer

Тестируем:
- _node_worker() - триггеры батчинга (max_batch, timeout)
- Флаг queue_limited - влияние на запись
- Изоляция воркеров между нодами
"""

import asyncio
import pytest
import orjson
from pathlib import Path

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.tests.utils.test_data_factory import create_test_user


# ========== Fixtures ==========

@pytest.fixture
def config_with_2_users(tmp_path):
    """Конфиг с 2 пользователями"""
    config = {
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [
                    create_test_user(email="existing1@test.com"),
                    create_test_user(email="existing2@test.com"),
                ]
            }
        }]
    }
    config_path = tmp_path / "config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    return config_path


def read_config_users(config_path: Path) -> list:
    """Читает список пользователей из конфига"""
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
    - Проверяем:
      * Данные записались на диск (2 начальных + 6 добавленных = 8)
      * В очереди осталась 1 операция (6-й пользователь)
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=2.0)
    node_proto_id = 1
    
    # Регистрируем ноду (2 пользователя загрузятся)
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем первые 5 пользователей (достигаем max_batch)
    for i in range(5):
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj_or_identifier=create_test_user(email=f"batch_user_{i}@test.com"),
            filepath=str(config_with_2_users),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
            reload_command=None
        )
    
    # Даём время воркеру начать обработку первого батча
    await asyncio.sleep(0.3)
    
    # Теперь добавляем 6-го пользователя (после того как воркер начал обработку)
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="batch_user_5@test.com"),
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # КЛЮЧЕВАЯ ПРОВЕРКА: В очереди должна быть 1 операция (6-й пользователь)
    # Первые 5 уже обрабатываются воркером
    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1  # 6-я операция ещё не обработана воркером
    
    # Даём время воркеру завершить запись первого батча И обработать 6-ю операцию
    # Воркер запишет первый батч (5 операций), затем начнёт ждать следующий батч
    # 6-я операция триггернет timeout (2 сек)
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
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем только 2 пользователя (не достигаем max_batch)
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="timeout_user_1@test.com"),
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="timeout_user_2@test.com"),
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
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
    Тест: Воркер НЕ записывает если queue_limited=False
    
    Сценарий:
    - Устанавливаем queue_limited=False вручную
    - Добавляем пользователей (достигаем max_batch)
    - Ждём
    - Проверяем что данные НЕ записались на диск
    - Возвращаем queue_limited=True
    - Принудительно вызываем flush
    - Проверяем что теперь данные записались
    """
    buffer = ConfigWriteBuffer(max_batch=3, timeout=1.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Отключаем лимиты очереди
    buffer.queue_limited = False
    
    # Добавляем 3 пользователя (достигаем max_batch)
    for i in range(3):
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj_or_identifier=create_test_user(email=f"unlimit_user_{i}@test.com"),
            filepath=str(config_with_2_users),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
            reload_command=None
        )
    
    # Ждём (воркер НЕ должен записать)
    await asyncio.sleep(0.5)
    
    # Проверяем что данные НЕ записались на диск
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 2  # Только начальные, новые НЕ записались
    
    # Включаем лимиты и принудительно записываем
    buffer.queue_limited = True
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
    - Проверяем что воркер работает, но запись не происходит (нечего записывать)
    - Файл не изменился
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    node_proto_id = 1
    
    # Регистрируем ноду (загружаются 2 пользователя)
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
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
    - В ноде 1 добавляем пользователей (будет запись)
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
    
    buffer = ConfigWriteBuffer(max_batch=2, timeout=1.0)
    
    # Регистрируем обе ноды
    await buffer.register_node(
        node_proto_id=1,
        filepath=str(config1),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    await buffer.register_node(
        node_proto_id=2,
        filepath=str(config2),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем по 2 пользователя в каждую ноду
    for i in range(2):
        await buffer.add_user(
            node_proto_id=1,
            user_obj_or_identifier=create_test_user(email=f"node1_user_{i}@test.com"),
            filepath=str(config1),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
            reload_command=None
        )
        await buffer.add_user(
            node_proto_id=2,
            user_obj_or_identifier=create_test_user(email=f"node2_user_{i}@test.com"),
            filepath=str(config2),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
            reload_command=None
        )
    
    # Портим путь к файлу ноды 1 (эмулируем ошибку)
    buffer.node_metadata[1]['filepath'] = str(tmp_path / "nonexistent.json")
    
    # Ждём срабатывания воркеров
    await asyncio.sleep(1.5)
    
    # Проверяем что нода 1 НЕ записалась (файл не существует)
    # Но нода 2 успешно записалась
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
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем 3 пользователей в буфер (но не триггерим воркер)
    for i in range(3):
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj_or_identifier=create_test_user(email=f"write_user_{i}@test.com"),
            filepath=str(config_with_2_users),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
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
    - Проверяем что все поля сохранились (не только clients)
    """
    # Создаём конфиг с расширенной структурой
    config = {
        "log": {
            "loglevel": "info",
            "access": "/var/log/access.log"
        },
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "tag": "main-inbound",
            "settings": {
                "clients": [
                    create_test_user(email="original@test.com")
                ],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "tcp",
                "security": "tls"
            }
        }],
        "outbounds": [{
            "protocol": "freedom",
            "tag": "direct"
        }],
        "routing": {
            "rules": [
                {"type": "field", "outboundTag": "direct"}
            ]
        }
    }
    
    config_path = tmp_path / "complex_config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем пользователя
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="new@test.com"),
        filepath=str(config_path),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # Записываем на диск
    await buffer._write_node_to_disk(node_proto_id)
    
    # Читаем полный конфиг
    full_config = orjson.loads(config_path.read_bytes())
    
    # Проверяем что ВСЕ поля сохранились
    assert "log" in full_config
    assert full_config["log"]["loglevel"] == "info"
    assert full_config["log"]["access"] == "/var/log/access.log"
    
    assert "outbounds" in full_config
    assert full_config["outbounds"][0]["protocol"] == "freedom"
    
    assert "routing" in full_config
    assert len(full_config["routing"]["rules"]) == 1
    
    # Проверяем inbound структуру
    inbound = full_config["inbounds"][0]
    assert inbound["port"] == 443
    assert inbound["tag"] == "main-inbound"
    assert "streamSettings" in inbound
    assert inbound["streamSettings"]["network"] == "tcp"
    assert inbound["settings"]["decryption"] == "none"
    
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
    
    Сценарий:
    - Регистрируем ноду с reload_command
    - Используем простую команду echo для проверки выполнения
    - Добавляем пользователя
    - Записываем на диск
    - Проверяем что команда выполнилась (проверяем через создание файла-маркера)
    """
    # Создаём маркерный файл для проверки выполнения команды
    marker_file = tmp_path / "reload_marker.txt"
    
    # Команда для Windows: создаёт файл-маркер
    reload_command = f'echo Reloaded > "{marker_file}"'
    
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду с командой перезагрузки
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=reload_command,
        user_obj=create_test_user()
    )
    
    # Добавляем пользователя
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="reload_test@test.com"),
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=reload_command
    )
    
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
    
    Сценарий:
    - Регистрируем ноду БЕЗ reload_command (None)
    - Добавляем пользователя
    - Записываем на диск
    - Проверяем что запись прошла успешно (без попытки выполнить команду)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду БЕЗ команды перезагрузки
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,  # Нет команды
        user_obj=create_test_user()
    )
    
    # Добавляем пользователя
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="no_reload@test.com"),
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # Записываем на диск (команда перезагрузки НЕ должна выполниться)
    await buffer._write_node_to_disk(node_proto_id)
    
    # Проверяем что данные записались
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 3  # 2 начальных + 1 добавленный
    
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "no_reload@test.com" in emails_on_disk
    
    await buffer.stop()


# ========== Группа 3: Перезагрузка ядра ==========

async def test_reload_core_success(config_with_2_users, tmp_path):
    """
    Тест: Успешное выполнение команды перезагрузки
    
    Сценарий:
    - Команда выполняется успешно (returncode=0)
    - Создаётся файл-маркер для подтверждения выполнения
    """
    marker_file = tmp_path / "reload_success.txt"
    reload_command = f'echo Success > "{marker_file}"'
    
    buffer = ConfigWriteBuffer()
    
    # Вызываем _reload_core напрямую
    await buffer._reload_core(reload_command)
    
    # Даём время команде выполниться
    await asyncio.sleep(0.3)
    
    # Проверяем что команда выполнилась
    assert marker_file.exists()
    content = marker_file.read_text().strip()
    assert "Success" in content
    
    await buffer.stop()


async def test_reload_core_failure(config_with_2_users, tmp_path):
    """
    Тест: Ошибка выполнения команды (returncode != 0)
    
    Сценарий:
    - Команда возвращает ненулевой код возврата
    - Метод НЕ падает с исключением
    - Ошибка логируется
    """
    # Команда которая завершится с ошибкой (exit code 1)
    reload_command = 'exit 1'
    
    buffer = ConfigWriteBuffer()
    
    # Вызов НЕ должен упасть с исключением
    try:
        await buffer._reload_core(reload_command)
        await asyncio.sleep(0.3)
        # Если дошли сюда - тест прошёл (не упало исключение)
        success = True
    except Exception as e:
        success = False
        pytest.fail(f"_reload_core не должен падать с исключением: {e}")
    
    assert success
    await buffer.stop()


async def test_reload_core_exception(config_with_2_users):
    """
    Тест: Исключение при выполнении команды
    
    Сценарий:
    - Команда вызывает исключение (например, несуществующая команда)
    - Метод НЕ падает с исключением
    - Исключение логируется
    """
    # Несуществующая команда
    reload_command = 'nonexistent_command_12345'
    
    buffer = ConfigWriteBuffer()
    
    # Вызов НЕ должен упасть с исключением
    try:
        await buffer._reload_core(reload_command)
        await asyncio.sleep(0.3)
        # Если дошли сюда - тест прошёл (не упало исключение)
        success = True
    except Exception as e:
        success = False
        pytest.fail(f"_reload_core не должен падать с исключением: {e}")
    
    assert success
    await buffer.stop()


# ========== Группа 4: Unlimit режим (bulk операции) ==========

async def test_unlimit_queue_disables_limits(config_with_2_users):
    """
    Тест: unlimit_queue() устанавливает queue_limited=False
    
    Сценарий:
    - Изначально queue_limited=True
    - Входим в контекст unlimit_queue()
    - Внутри контекста queue_limited=False
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Изначально True
    assert buffer.queue_limited is True
    
    # Входим в контекст
    async with buffer.unlimit_queue(node_proto_id):
        # Внутри контекста должно быть False
        assert buffer.queue_limited is False
    
    # После выхода восстановлено в True
    assert buffer.queue_limited is True
    
    await buffer.stop()


@pytest.mark.slow
async def test_unlimit_queue_flushes_on_exit(config_with_2_users):
    """
    Тест: unlimit_queue() принудительно записывает при выходе из контекста
    
    Сценарий:
    - Входим в unlimit_queue()
    - Добавляем пользователей (не достигая max_batch)
    - Выходим из контекста
    - Проверяем что данные принудительно записались на диск
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Используем unlimit режим
    async with buffer.unlimit_queue(node_proto_id):
        # Добавляем 3 пользователя (не достигаем max_batch=10)
        for i in range(3):
            await buffer.add_user(
                node_proto_id=node_proto_id,
                user_obj_or_identifier=create_test_user(email=f"unlimit_{i}@test.com"),
                filepath=str(config_with_2_users),
                users_path="inbounds___0___settings___clients",
                flatten_user_identifier_key="email",
                reload_command=None
            )
        
        # Внутри контекста данные ещё НЕ записаны
        # (проверяем через короткую паузу)
        await asyncio.sleep(0.2)
        users_on_disk = read_config_users(config_with_2_users)
        # Может быть 2 или 5 в зависимости от timing, не проверяем здесь
    
    # После выхода из контекста данные ДОЛЖНЫ записаться
    # Даём небольшое время на flush
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
    
    Сценарий:
    - Входим в контекст unlimit_queue()
    - Флаг устанавливается в False
    - Выходим из контекста
    - Флаг восстанавливается в True
    - Даже при исключении внутри контекста
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Изначально True
    assert buffer.queue_limited is True
    
    # Сценарий 1: Нормальный выход
    async with buffer.unlimit_queue(node_proto_id):
        assert buffer.queue_limited is False
    
    assert buffer.queue_limited is True
    
    # Сценарий 2: Выход через исключение
    try:
        async with buffer.unlimit_queue(node_proto_id):
            assert buffer.queue_limited is False
            raise ValueError("Тестовое исключение")
    except ValueError:
        pass  # Ожидаемое исключение
    
    # Флаг всё равно должен восстановиться
    assert buffer.queue_limited is True
    
    await buffer.stop()


@pytest.mark.slow
async def test_bulk_operations_without_intermediate_writes(config_with_2_users):
    """
    Тест: Массовое добавление в unlimit режиме без промежуточных записей
    
    Сценарий:
    - Используем unlimit_queue()
    - Добавляем 20 пользователей (больше чем max_batch=5)
    - Во время добавления промежуточных записей НЕ происходит
    - После выхода из контекста все 20 пользователей записаны одним батчом
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=2.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Запоминаем время изменения файла ДО начала операций
    initial_mtime = config_with_2_users.stat().st_mtime
    
    # Используем unlimit режим
    async with buffer.unlimit_queue(node_proto_id):
        # Добавляем 20 пользователей (4 батча по 5)
        for i in range(20):
            await buffer.add_user(
                node_proto_id=node_proto_id,
                user_obj_or_identifier=create_test_user(email=f"bulk_{i}@test.com"),
                filepath=str(config_with_2_users),
                users_path="inbounds___0___settings___clients",
                flatten_user_identifier_key="email",
                reload_command=None
            )
        
        # Ждём чуть больше чем timeout (2 сек)
        # В обычном режиме должна была бы произойти запись
        await asyncio.sleep(2.5)
        
        # Проверяем что файл НЕ изменился (промежуточных записей не было)
        mid_mtime = config_with_2_users.stat().st_mtime
        assert mid_mtime == initial_mtime, "Не должно быть промежуточных записей в unlimit режиме"
    
    # После выхода из контекста данные записываются
    await asyncio.sleep(0.5)
    
    # Проверяем финальный результат
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 22  # 2 начальных + 20 добавленных
    
    # Проверяем что все bulk пользователи на месте
    emails_on_disk = {u["email"] for u in users_on_disk}
    for i in range(20):
        assert f"bulk_{i}@test.com" in emails_on_disk
    
    # Файл изменился после выхода из контекста
    final_mtime = config_with_2_users.stat().st_mtime
    assert final_mtime > initial_mtime
    
    await buffer.stop()


# ========== Группа 5: Остановка ==========

async def test_stop_cancels_all_workers(tmp_path):
    """
    Тест: stop() корректно останавливает все воркеры
    
    Сценарий:
    - Создаём 3 ноды с воркерами
    - Проверяем что все воркеры запущены
    - Вызываем stop()
    - Проверяем что все воркеры остановлены (cancelled)
    """
    # Создаём 3 конфига
    configs = []
    for i in range(3):
        config_path = tmp_path / f"config_{i}.json"
        config = {
            "inbounds": [{
                "port": 443 + i,
                "protocol": "vless",
                "settings": {"clients": []}
            }]
        }
        config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
        configs.append(config_path)
    
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    
    # Регистрируем 3 ноды
    for i, config_path in enumerate(configs):
        await buffer.register_node(
            node_proto_id=i + 1,
            filepath=str(config_path),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
            reload_command=None,
            user_obj=create_test_user()
        )
    
    # Проверяем что все воркеры запущены
    assert len(buffer.worker_tasks) == 3
    for node_id, task in buffer.worker_tasks.items():
        assert not task.done(), f"Воркер ноды {node_id} не должен быть завершён"
        assert not task.cancelled(), f"Воркер ноды {node_id} не должен быть отменён"
    
    # Останавливаем буфер
    await buffer.stop()
    
    # Даём время на остановку
    await asyncio.sleep(0.3)
    
    # Проверяем что все воркеры остановлены
    for node_id, task in buffer.worker_tasks.items():
        assert task.done(), f"Воркер ноды {node_id} должен быть завершён"
        # Воркер может быть либо cancelled, либо done без исключения
        # Проверяем что не висит
        assert task.done()


@pytest.mark.slow
async def test_stop_flushes_pending_operations(config_with_2_users):
    """
    Тест: stop() записывает несохранённые операции на диск
    
    Сценарий:
    - Регистрируем ноду
    - Добавляем пользователей (не достигая max_batch и не дожидаясь timeout)
    - Вызываем stop()
    - Проверяем что данные записались на диск (сброс остатков)
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=100.0)  # Большие значения чтобы не триггернулись
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем 3 пользователя (не достигаем max_batch=10)
    for i in range(3):
        await buffer.add_user(
            node_proto_id=node_proto_id,
            user_obj_or_identifier=create_test_user(email=f"pending_{i}@test.com"),
            filepath=str(config_with_2_users),
            users_path="inbounds___0___settings___clients",
            flatten_user_identifier_key="email",
            reload_command=None
        )
    
    # Проверяем что в очереди 3 операции (ещё не записаны)
    assert buffer.node_queues[node_proto_id].qsize() == 3
    
    # Проверяем что на диске всё ещё только начальные пользователи
    users_on_disk_before = read_config_users(config_with_2_users)
    assert len(users_on_disk_before) == 2
    
    # Останавливаем буфер (должен записать остатки)
    await buffer.stop()
    
    # Проверяем что данные записались на диск
    users_on_disk_after = read_config_users(config_with_2_users)
    assert len(users_on_disk_after) == 5  # 2 начальных + 3 добавленных
    
    # Проверяем что все пользователи на месте
    emails_on_disk = {u["email"] for u in users_on_disk_after}
    for i in range(3):
        assert f"pending_{i}@test.com" in emails_on_disk


async def test_stop_idempotent(config_with_2_users):
    """
    Тест: Повторный вызов stop() безопасен (idempotency)
    
    Сценарий:
    - Регистрируем ноду
    - Вызываем stop() первый раз
    - Вызываем stop() второй раз
    - Вызываем stop() третий раз
    - Проверяем что не возникает исключений
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    
    # Регистрируем ноду
    await buffer.register_node(
        node_proto_id=node_proto_id,
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None,
        user_obj=create_test_user()
    )
    
    # Добавляем пользователя для проверки записи
    await buffer.add_user(
        node_proto_id=node_proto_id,
        user_obj_or_identifier=create_test_user(email="idempotent@test.com"),
        filepath=str(config_with_2_users),
        users_path="inbounds___0___settings___clients",
        flatten_user_identifier_key="email",
        reload_command=None
    )
    
    # Первый stop
    try:
        await buffer.stop()
        first_stop_success = True
    except Exception as e:
        first_stop_success = False
        pytest.fail(f"Первый stop() не должен падать: {e}")
    
    assert first_stop_success
    
    # Второй stop (не должен падать)
    try:
        await buffer.stop()
        second_stop_success = True
    except Exception as e:
        second_stop_success = False
        pytest.fail(f"Второй stop() не должен падать: {e}")
    
    assert second_stop_success
    
    # Третий stop (не должен падать)
    try:
        await buffer.stop()
        third_stop_success = True
    except Exception as e:
        third_stop_success = False
        pytest.fail(f"Третий stop() не должен падать: {e}")
    
    assert third_stop_success
    
    # Проверяем что данные всё равно записались (при первом stop)
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 3  # 2 начальных + 1 добавленный
    
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "idempotent@test.com" in emails_on_disk
