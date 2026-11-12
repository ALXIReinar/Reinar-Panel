"""
Unit тесты для воркеров и батчинга ConfigWriteBuffer

Тестируем:
- _node_worker() - триггеры батчинга (max_batch, timeout)
- Одна запись и один перезапуск ядра на цикл воркера (пачки не пишутся порциями)
- Изоляция воркеров между нодами
"""

import asyncio  # noqa: I001
from unittest.mock import patch

import pytest
import orjson
from pathlib import Path

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.tests.utils.test_data_factory import (
    create_test_user,
    create_vnode_service_data,
)


# ========== Fixtures ==========


@pytest.fixture
def config_with_2_users(tmp_path):
    """Конфиг с 2 пользователями + state.json"""
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        create_test_user(email="existing1@test.com", uuid="uuid-ex1", as_superuser=False),
                        create_test_user(email="existing2@test.com", uuid="uuid-ex2", as_superuser=False),
                    ]
                },
            }
        ]
    }
    config_path = tmp_path / "config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
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
    Тест: Воркер записывает на диск при достижении max_batch операций
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=2.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    for i in range(5):
        user = create_test_user(email=f"batch_user_{i}@test.com", uuid=f"uuid-batch-{i}", as_superuser=True)
        await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)

    await asyncio.sleep(0.3)
    user6 = create_test_user(email="batch_user_5@test.com", uuid="uuid-batch-5", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user6)

    queue = buffer.node_queues[node_proto_id]
    assert queue.qsize() == 1

    await asyncio.sleep(2.5)
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 8  # 2 начальных + 6 добавленных
    emails_on_disk = {u["email"] for u in users_on_disk}
    for i in range(6):
        assert f"batch_user_{i}@test.com" in emails_on_disk
    await buffer.stop()


@pytest.mark.slow
async def test_worker_triggers_on_timeout(config_with_2_users):
    """
    Тест: Воркер записывает на диск по истечению timeout
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=1.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    user1 = create_test_user(email="timeout_user_1@test.com", uuid="uuid-t1", as_superuser=True)
    user2 = create_test_user(email="timeout_user_2@test.com", uuid="uuid-t2", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user1)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user2)

    await asyncio.sleep(1.5)
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 4  # 2 начальных + 2 добавленных
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "timeout_user_1@test.com" in emails_on_disk
    assert "timeout_user_2@test.com" in emails_on_disk
    await buffer.stop()


async def test_worker_handles_empty_queue(config_with_2_users):
    """
    Тест: Воркер корректно работает с пустой очередью
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    initial_mtime = config_with_2_users.stat().st_mtime
    await asyncio.sleep(1.0)
    final_mtime = config_with_2_users.stat().st_mtime
    assert initial_mtime == final_mtime
    assert len(buffer.buffer_storage[node_proto_id]) == 2
    assert buffer.node_queues[node_proto_id].qsize() == 0
    await buffer.stop()


@pytest.mark.slow
async def test_worker_isolation_between_nodes(tmp_path):
    """
    Тест: Изоляция воркеров - ошибка в одной ноде не влияет на другие
    """
    config1 = tmp_path / "config1.json"
    config2 = tmp_path / "config2.json"
    for config_path in [config1, config2]:
        config = {"inbounds": [{"port": 443, "protocol": "vless", "settings": {"clients": []}}]}
        config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
        state = {"users": []}
        state_path = Path(str(config_path) + ".state.json")
        state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))

    buffer = ConfigWriteBuffer(max_batch=2, timeout=1.0)
    await buffer.register_node(create_vnode_service_data(node_proto_id=1, filepath=str(config1)))
    await buffer.register_node(create_vnode_service_data(node_proto_id=2, filepath=str(config2)))

    for i in range(2):
        user1 = create_test_user(email=f"node1_user_{i}@test.com", uuid=f"uuid-n1-{i}", as_superuser=True)
        user2 = create_test_user(email=f"node2_user_{i}@test.com", uuid=f"uuid-n2-{i}", as_superuser=True)
        await buffer.add_user(node_proto_id=1, user_obj=user1)
        await buffer.add_user(node_proto_id=2, user_obj=user2)

    buffer.node_metadata[1]['filepath'] = str(tmp_path / "nonexistent.json")
    await asyncio.sleep(1.5)

    users_node2 = read_config_users(config2)
    assert len(users_node2) == 2
    emails_node2 = {u["email"] for u in users_node2}
    assert "node2_user_0@test.com" in emails_node2
    assert "node2_user_1@test.com" in emails_node2
    assert not buffer.worker_tasks[2].done()
    await buffer.stop()


# ========== Группа 2: Запись на диск ==========


async def test_write_to_disk_success(config_with_2_users):
    """
    Тест: Успешная атомарная запись на диск
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    for i in range(3):
        user = create_test_user(email=f"write_user_{i}@test.com", uuid=f"uuid-w-{i}", as_superuser=True)
        await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)

    assert len(buffer.buffer_storage[node_proto_id]) == 5
    await buffer._write_node_to_disk(node_proto_id)

    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 5
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "existing1@test.com" in emails_on_disk
    assert "existing2@test.com" in emails_on_disk
    for i in range(3):
        assert f"write_user_{i}@test.com" in emails_on_disk
    await buffer.stop()


async def test_write_preserves_file_structure(tmp_path):
    """
    Тест: Запись сохраняет структуру конфиг-файла
    """
    config = {
        "log": {"loglevel": "info", "access": "/var/log/access.log"},
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "tag": "main-inbound",
                "settings": {
                    "clients": [create_test_user(email="original@test.com", uuid="uuid-orig", as_superuser=False)],
                    "decryption": "none",
                },
                "streamSettings": {"network": "tcp", "security": "tls"},
            }
        ],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
        "routing": {"rules": [{"type": "field", "outboundTag": "direct"}]},
    }
    config_path = tmp_path / "complex_config.json"
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state = {"users": [create_test_user(email="original@test.com", uuid="uuid-orig", as_superuser=True)]}
    state_path = tmp_path / "complex_config.json.state.json"
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))

    buffer = ConfigWriteBuffer(max_batch=10, timeout=10.0)
    node_proto_id = 1
    await buffer.register_node(create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_path)))

    new_user = create_test_user(email="new@test.com", uuid="uuid-new", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=new_user)
    await buffer._write_node_to_disk(node_proto_id)

    full_config = orjson.loads(config_path.read_bytes())
    assert "log" in full_config
    assert "outbounds" in full_config
    assert "routing" in full_config
    clients = full_config["inbounds"][0]["settings"]["clients"]
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

    await buffer.register_node(
        create_vnode_service_data(
            node_proto_id=node_proto_id,
            filepath=str(config_with_2_users),
            reload_command=reload_command,
        )
    )

    user = create_test_user(email="reload_test@test.com", uuid="uuid-reload", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)
    assert not marker_file.exists()

    await buffer._write_node_to_disk(node_proto_id)
    await asyncio.sleep(0.5)

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
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    user = create_test_user(email="no_reload@test.com", uuid="uuid-noreload", as_superuser=True)
    await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)
    await buffer._write_node_to_disk(node_proto_id)

    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 3
    emails_on_disk = {u["email"] for u in users_on_disk}
    assert "no_reload@test.com" in emails_on_disk
    await buffer.stop()


# ========== Группа 3: одна запись и один перезапуск ядра на цикл воркера ==========


def count_writes_and_reloads(buffer: ConfigWriteBuffer):
    """Подменяет запись и перезапуск ядра счётчиками; запись при этом настоящая"""
    counts = {"writes": 0, "reloads": 0}
    real_write = buffer._write_node_to_disk

    async def write(node_id):
        counts["writes"] += 1
        await real_write(node_id)

    async def reload(_command):
        counts["reloads"] += 1

    return counts, patch.object(buffer, "_write_node_to_disk", write), patch.object(buffer, "_reload_core", reload)


async def test_bulk_action_one_write_and_one_reload(config_with_2_users):
    """
    Пачка больше max_batch: эндпоинт только кладёт операции в буфер (ядро не трогает),
    воркер пишет конфиг один раз и один раз перезапускает ядро — а не порциями по max_batch
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=1, filepath=str(config_with_2_users), reload_command="true")
    )
    users = [create_test_user(email=f"bulk_{i}@test.com", uuid=f"uuid-bulk-{i}", as_superuser=True) for i in range(12)]
    counts, patch_write, patch_reload = count_writes_and_reloads(buffer)
    try:
        with patch_write, patch_reload:
            await buffer.bulk_action(node_proto_id=1, users=users, action="add")
            assert counts == {"writes": 0, "reloads": 0}, "эндпоинт сам пишет конфиг или перезапускает ядро"

            await asyncio.sleep(buffer.timeout * 3)

        assert counts == {"writes": 1, "reloads": 1}
        assert len(read_config_users(config_with_2_users)) == 14
    finally:
        await buffer.stop()


async def test_full_batch_written_without_waiting_interval(config_with_2_users):
    """Набралось max_batch операций — запись сразу, не дожидаясь интервала (здесь он заведомо больше теста)"""
    buffer = ConfigWriteBuffer(max_batch=5, timeout=30.0)
    await buffer.register_node(create_vnode_service_data(node_proto_id=1, filepath=str(config_with_2_users)))
    users = [create_test_user(email=f"full_{i}@test.com", uuid=f"uuid-full-{i}", as_superuser=True) for i in range(12)]
    try:
        await buffer.bulk_action(node_proto_id=1, users=users, action="add")
        await asyncio.sleep(0.5)

        assert len(read_config_users(config_with_2_users)) == 14
    finally:
        await buffer.stop()


async def test_bulk_delete_one_write(config_with_2_users):
    """Пакетное удаление — так же одной записью"""
    buffer = ConfigWriteBuffer(max_batch=1, timeout=0.5)
    await buffer.register_node(create_vnode_service_data(node_proto_id=1, filepath=str(config_with_2_users)))
    counts, patch_write, patch_reload = count_writes_and_reloads(buffer)
    try:
        with patch_write, patch_reload:
            existing = [{"user_uuid": "uuid-ex1"}, {"user_uuid": "uuid-ex2"}]
            await buffer.bulk_action(node_proto_id=1, users=existing, action="delete")
            await asyncio.sleep(buffer.timeout * 3)

        assert counts["writes"] == 1
        assert read_config_users(config_with_2_users) == []
    finally:
        await buffer.stop()


# ========== Группа 4: Остановка и cleanup ==========


async def test_stop_cancels_all_workers(tmp_path):
    """
    Тест: stop() корректно останавливает все воркеры
    """
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
    for i, config_path in enumerate(configs):
        await buffer.register_node(create_vnode_service_data(node_proto_id=i + 1, filepath=str(config_path)))

    for i in range(1, 4):
        assert i in buffer.worker_tasks
        assert not buffer.worker_tasks[i].done()

    tasks = {i: buffer.worker_tasks[i] for i in range(1, 4)}
    await buffer.stop()
    for i in range(1, 4):
        assert tasks[i].done()


@pytest.mark.slow
async def test_stop_flushes_pending_operations(config_with_2_users):
    """
    Тест: stop() записывает несохранённые операции на диск
    """
    buffer = ConfigWriteBuffer(max_batch=10, timeout=100.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    for i in range(3):
        user = create_test_user(email=f"pending_{i}@test.com", uuid=f"uuid-pend-{i}", as_superuser=True)
        await buffer.add_user(node_proto_id=node_proto_id, user_obj=user)

    await buffer.stop()
    users_on_disk = read_config_users(config_with_2_users)
    assert len(users_on_disk) == 5


async def test_stop_idempotent(config_with_2_users):
    """
    Тест: Повторный вызов stop() безопасен
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    node_proto_id = 1
    await buffer.register_node(
        create_vnode_service_data(node_proto_id=node_proto_id, filepath=str(config_with_2_users))
    )

    await buffer.stop()
    await buffer.stop()
    await buffer.stop()
    assert True
