"""
Интеграционные тесты эндпоинта реинициализации POST /api/v1/server/node/reinit

Тестируем:
- атомарность: ошибка одной ноды → 422, метаданные остальных не меняются (требования 4.5, 4.6)
- удаление нод из missing: воркер останавливается, очередь и данные ноды очищаются (требование 4.4)
- повторная регистрация сохраняет buffer_storage и local_state (требование 4.3)
- запрос к админке при реинициализации делается одной попыткой, без стартовых повторов
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from node_client.tests.utils.test_data_factory import create_vnode_item_with_config as make_item

REINIT_URL = "/api/v1/server/node/reinit"
FETCH_PATH = "node_client.api.reinit_api.fetch_startup_data"
BROKEN_EXTRACTOR = "def transform(user_obj) этот скрипт не компилируется"


def startup_answer(nodes: list[dict], missing: list[int] | None = None) -> AsyncMock:
    """Мок fetch_startup_data, возвращающий заданный ответ админки"""
    return AsyncMock(return_value={"node_title": "test", "nodes": nodes, "missing": missing or []})


@pytest.mark.asyncio
async def test_reinit_broken_node_keeps_old_metadata(client_with_real_buffer, fast_buffer, tmp_path):
    """Битая нода 2 → 422, а метаданные исправной ноды 1 остаются прежними"""
    await fast_buffer.register_node(make_item(tmp_path, 1))
    await fast_buffer.register_node(make_item(tmp_path, 2))
    old_meta_1 = fast_buffer.node_metadata[1]
    old_meta_2 = fast_buffer.node_metadata[2]

    new_1 = make_item(tmp_path, 1, extractor_script="def transform(user_obj):\n    return {'changed': True}\n")
    broken_2 = make_item(tmp_path, 2, extractor_script=BROKEN_EXTRACTOR)

    with patch(FETCH_PATH, startup_answer([new_1, broken_2])):
        resp = await client_with_real_buffer.post(REINIT_URL, json={"node_proto_ids": [1, 2]})

    assert resp.status_code == 422
    body = resp.json()
    assert body["node_proto_id"] == 2
    assert body["field"] == "user_injectors[0].extractor_script"
    assert fast_buffer.node_metadata[1] is old_meta_1, "метаданные ноды 1 подменены несмотря на ошибку"
    assert fast_buffer.node_metadata[2] is old_meta_2


@pytest.mark.asyncio
async def test_reinit_broken_node_does_not_start_new_nodes(client_with_real_buffer, fast_buffer, tmp_path):
    """Новая валидная нода 3 не регистрируется и не получает воркер, если в пачке есть битая нода"""
    broken_2 = make_item(tmp_path, 2, extractor_script=BROKEN_EXTRACTOR)
    new_3 = make_item(tmp_path, 3)

    with patch(FETCH_PATH, startup_answer([new_3, broken_2])):
        resp = await client_with_real_buffer.post(REINIT_URL, json={"node_proto_ids": [2, 3]})

    assert resp.status_code == 422
    assert 3 not in fast_buffer.node_metadata
    assert 3 not in fast_buffer.worker_tasks
    assert 3 not in fast_buffer.node_queues


@pytest.mark.asyncio
async def test_reinit_success_keeps_users_and_local_state(client_with_real_buffer, fast_buffer, tmp_path):
    """Успешная реинициализация меняет метаданные, но не трогает пользователей и local_state"""
    await fast_buffer.register_node(make_item(tmp_path, 1))
    fast_buffer.buffer_storage[1]["uuid-1"] = {"user_uuid": "uuid-1"}
    fast_buffer.local_state[1]["counter"] = 42
    old_meta = fast_buffer.node_metadata[1]
    old_worker = fast_buffer.worker_tasks[1]

    new_1 = make_item(tmp_path, 1, extractor_script="def transform(user_obj):\n    return {'changed': True}\n")
    with patch(FETCH_PATH, startup_answer([new_1])):
        resp = await client_with_real_buffer.post(REINIT_URL, json={"node_proto_ids": [1]})

    assert resp.status_code == 200
    assert resp.json()["registered"] == [1]
    assert fast_buffer.node_metadata[1] is not old_meta
    assert fast_buffer.buffer_storage[1] == {"uuid-1": {"user_uuid": "uuid-1"}}
    assert fast_buffer.local_state[1] == {"counter": 42}
    assert fast_buffer.worker_tasks[1] is old_worker, "воркер пересоздан при повторной регистрации"


@pytest.mark.asyncio
async def test_reinit_missing_node_stops_worker(client_with_real_buffer, fast_buffer, tmp_path):
    """Нода из missing удаляется полностью: воркер остановлен, очередь и данные очищены, event loop жив"""
    await fast_buffer.register_node(make_item(tmp_path, 1))
    worker = fast_buffer.worker_tasks[1]

    with patch(FETCH_PATH, startup_answer([], missing=[1])):
        resp = await client_with_real_buffer.post(REINIT_URL, json={"node_proto_ids": [1]})

    assert resp.status_code == 200
    assert resp.json()["removed"] == [1]
    # Структурные проверки идут до ожидания: при живом воркере event loop зависнет на следующем шаге
    assert worker.done(), "воркер удалённой ноды продолжает работать"
    for storage in (
        fast_buffer.node_metadata,
        fast_buffer.worker_tasks,
        fast_buffer.node_queues,
        fast_buffer.pending_writes,
        fast_buffer.buffer_storage,
        fast_buffer.local_state,
    ):
        assert 1 not in storage

    # Ждём дольше таймаута воркера: event loop должен оставаться отзывчивым
    await asyncio.wait_for(asyncio.sleep(fast_buffer.timeout * 1.5), timeout=fast_buffer.timeout * 3)


@pytest.mark.asyncio
async def test_reinit_requests_admin_once(client_with_real_buffer, fast_buffer, tmp_path):
    """Реинициализация не использует стартовую политику повторов: одна попытка запроса к админке"""
    fetch = startup_answer([make_item(tmp_path, 1)])
    with patch(FETCH_PATH, fetch):
        resp = await client_with_real_buffer.post(REINIT_URL, json={"node_proto_ids": [1]})

    assert resp.status_code == 200
    fetch.assert_awaited_once_with(node_proto_ids=[1], retries=1)
