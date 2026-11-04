"""
Unit тесты старта нод-клиента: fetch_startup_data и phys_node_sys_init

Тестируем число попыток подключения:
- при старте — env.startup_retries попыток с паузой между ними (требование 3.6)
- при явном retries=1 (реинициализация) — одна попытка без пауз
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from aiohttp import web

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.config import env
from node_client.exceptions import NodeInitError
from node_client.startup import fetch_startup_data, phys_node_sys_init
from node_client.tests.utils.test_data_factory import create_vnode_item_with_config

# Порт 1 закрыт: соединение отклоняется сразу, без ожидания таймаута
UNREACHABLE_ADMIN = "http://127.0.0.1:1"


@pytest.mark.asyncio
async def test_fetch_startup_data_retries_by_settings():
    """Без явного retries делается env.startup_retries попыток, между ними пауза"""
    sleep = AsyncMock()
    with (
        patch.object(env, "admin_panel_url", UNREACHABLE_ADMIN),
        patch.object(env, "startup_retries", 3),
        patch("node_client.startup.asyncio.sleep", sleep),
        pytest.raises(RuntimeError, match="попыток: 3"),
    ):
        await fetch_startup_data([])

    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_fetch_startup_data_single_attempt():
    """retries=1 — одна попытка, без пауз, сразу ошибка"""
    sleep = AsyncMock()
    with (
        patch.object(env, "admin_panel_url", UNREACHABLE_ADMIN),
        patch.object(env, "startup_retries", 30),
        patch("node_client.startup.asyncio.sleep", sleep),
        pytest.raises(RuntimeError, match="попыток: 1"),
    ):
        await fetch_startup_data([1], retries=1)

    sleep.assert_not_awaited()


# ========== Ответы админки и инициализация при старте ==========


@pytest_asyncio.fixture(loop_scope="function")
async def fake_admin():
    """
    Настоящий HTTP-сервер вместо админки: POST /api/v1/server/nodes/{node_title}/startup.

    Возвращает изменяемое состояние: status/body ответа и список полученных запросов (node_title, тело).
    Цикл событий — тот же, что у теста (иначе сервер не отвечает: в pytest.ini фикстуры по умолчанию в цикле сессии).
    Одна попытка подключения по умолчанию: если тест сломается, он упадёт сразу, а не через 30 повторов.
    """
    state = {"status": 200, "body": {"node_title": "x", "nodes": [], "missing": []}, "requests": []}

    async def handler(request: web.Request) -> web.Response:
        state["requests"].append((request.match_info["node_title"], await request.json()))
        return web.json_response(state["body"], status=state["status"])

    app = web.Application()
    app.router.add_post("/api/v1/server/nodes/{node_title}/startup", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    with patch.object(env, "admin_panel_url", f"http://127.0.0.1:{port}"), patch.object(env, "startup_retries", 1):
        yield state
    await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_startup_data_sends_node_title_and_ids(fake_admin):
    """Запрос идёт на /startup с NODE_TITLE в пути и списком нод в теле; ответ возвращается как есть"""
    fake_admin["body"] = {"node_title": env.node_title, "nodes": [], "missing": [3]}

    data = await fetch_startup_data([3])

    assert data == fake_admin["body"]
    assert fake_admin["requests"] == [(env.node_title, {"node_proto_ids": [3]})]


@pytest.mark.asyncio
async def test_fetch_startup_data_unknown_node_fails_fast(fake_admin):
    """404 (админка не знает NODE_TITLE) — ошибка настройки: падаем сразу, без повторов"""
    fake_admin["status"] = 404
    fake_admin["body"] = {"detail": {"success": False, "message": "Физическая нода не найдена"}}
    sleep = AsyncMock()

    with (
        patch.object(env, "startup_retries", 30),
        patch("node_client.startup.asyncio.sleep", sleep),
        pytest.raises(RuntimeError, match="не знает ноду"),
    ):
        await fetch_startup_data([])

    assert len(fake_admin["requests"]) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_phys_node_sys_init_registers_all_nodes(tmp_path):
    """Старт: каждая нода из ответа /startup зарегистрирована, у каждой свой воркер"""
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    answer = {
        "nodes": [create_vnode_item_with_config(tmp_path, 1), create_vnode_item_with_config(tmp_path, 2)],
        "missing": [],
    }
    try:
        with patch("node_client.startup.fetch_startup_data", AsyncMock(return_value=answer)) as fetch:
            await phys_node_sys_init(buffer)

        fetch.assert_awaited_once_with(node_proto_ids=[])
        assert set(buffer.node_metadata) == {1, 2}
        assert set(buffer.worker_tasks) == {1, 2}
    finally:
        await buffer.stop()


@pytest.mark.asyncio
async def test_phys_node_sys_init_fails_on_broken_node(tmp_path):
    """Принцип Trust: битый скрипт любой ноды прерывает старт с понятной ошибкой (node_proto_id и поле)"""
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    answer = {
        "nodes": [
            create_vnode_item_with_config(tmp_path, 1),
            create_vnode_item_with_config(tmp_path, 2, extractor_script="def transform(u) не компилируется"),
        ],
        "missing": [],
    }
    try:
        with (
            patch("node_client.startup.fetch_startup_data", AsyncMock(return_value=answer)),
            pytest.raises(NodeInitError) as exc_info,
        ):
            await phys_node_sys_init(buffer)

        assert exc_info.value.node_proto_id == 2
        assert exc_info.value.field == "user_injectors[0].extractor_script"
    finally:
        await buffer.stop()
