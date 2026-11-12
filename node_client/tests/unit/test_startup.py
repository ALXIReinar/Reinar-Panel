"""
Unit тесты старта нод-клиента: ConfigWriteBuffer.fetch_startup_data, phys_node_sys_init, lifespan

Тестируем:
- число попыток подключения: при старте — env.startup_retries с паузой между ними (требование 3.6),
  при явном retries=1 (реинициализация) — одна попытка без пауз
- запросы к админке идут через переданную сессию (одна на всё приложение, создаётся в lifespan)
- lifespan закрывает сессию и буфер, даже если инициализация упала
- проверку элемента /startup схемой: ошибка называет поле
"""

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from fastapi import FastAPI
from pydantic import ValidationError

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.config import env
from node_client.exceptions import AdminPanelError, NodeInitError
from node_client.tests.utils.test_data_factory import create_vnode_item_with_config

SLEEP_PATH = "node_client.api.proto_core.write_behind_caching_file.asyncio.sleep"


@pytest_asyncio.fixture(loop_scope="function")
async def admin_session():
    """Сессия к админке, как её создаёт lifespan (короткий таймаут — тесты не висят)"""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        yield session


@pytest.fixture
def unreachable_admin():
    """Порт 1 закрыт: соединение отклоняется сразу, без ожидания таймаута"""
    with patch.object(env, "admin_panel_private_ip", "127.0.0.1"), patch.object(env, "admin_panel_port", 1):
        yield


@pytest.mark.asyncio
async def test_fetch_startup_data_retries_by_settings(admin_session, unreachable_admin):
    """Без явного retries делается env.startup_retries попыток, между ними пауза"""
    sleep = AsyncMock()
    with (
        patch.object(env, "startup_retries", 3),
        patch(SLEEP_PATH, sleep),
        pytest.raises(AdminPanelError, match="попыток: 3"),
    ):
        await ConfigWriteBuffer().fetch_startup_data(admin_session, [])

    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_fetch_startup_data_single_attempt(admin_session, unreachable_admin):
    """retries=1 — одна попытка, без пауз, сразу ошибка"""
    sleep = AsyncMock()
    with (
        patch.object(env, "startup_retries", 30),
        patch(SLEEP_PATH, sleep),
        pytest.raises(AdminPanelError, match="попыток: 1"),
    ):
        await ConfigWriteBuffer().fetch_startup_data(admin_session, [1], retries=1)

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
    with (
        patch.object(env, "admin_panel_private_ip", "127.0.0.1"),
        patch.object(env, "admin_panel_port", port),
        patch.object(env, "startup_retries", 1),
    ):
        yield state
    await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_startup_data_sends_node_title_and_ids(fake_admin, admin_session):
    """Запрос идёт на /startup с NODE_TITLE в пути и списком нод в теле; ответ возвращается как есть"""
    fake_admin["body"] = {"node_title": env.node_title, "nodes": [], "missing": [3]}

    data = await ConfigWriteBuffer().fetch_startup_data(admin_session, [3])

    assert data == fake_admin["body"]
    assert fake_admin["requests"] == [(env.node_title, {"node_proto_ids": [3]})]


@pytest.mark.asyncio
async def test_fetch_startup_data_unknown_node_fails_fast(fake_admin, admin_session):
    """404 (админка не знает NODE_TITLE) — ошибка настройки: падаем сразу, без повторов"""
    fake_admin["status"] = 404
    fake_admin["body"] = {"detail": {"success": False, "message": "Физическая нода не найдена"}}
    sleep = AsyncMock()

    with (
        patch.object(env, "startup_retries", 30),
        patch(SLEEP_PATH, sleep),
        pytest.raises(AdminPanelError, match="не знает ноду"),
    ):
        await ConfigWriteBuffer().fetch_startup_data(admin_session, [])

    assert len(fake_admin["requests"]) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_startup_data_quotes_node_title(fake_admin, admin_session):
    """Спецсимволы в NODE_TITLE экранируются в пути: '#' и '?' не обрезают URL"""
    with patch.object(env, "node_title", "DE #1?x"):
        await ConfigWriteBuffer().fetch_startup_data(admin_session, [])

    assert fake_admin["requests"][0][0] == "DE #1?x"


@pytest.mark.asyncio
async def test_phys_node_sys_init_registers_all_nodes(tmp_path, admin_session):
    """Старт: каждая нода из ответа /startup зарегистрирована, у каждой свой воркер; запрос — через переданную сессию"""
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    answer = {
        "nodes": [create_vnode_item_with_config(tmp_path, 1), create_vnode_item_with_config(tmp_path, 2)],
        "missing": [],
    }
    try:
        with patch.object(buffer, "fetch_startup_data", AsyncMock(return_value=answer)) as fetch:
            await buffer.phys_node_sys_init(admin_session)

        fetch.assert_awaited_once_with(admin_session, node_proto_ids=[])
        assert set(buffer.node_metadata) == {1, 2}
        assert set(buffer.worker_tasks) == {1, 2}
    finally:
        await buffer.stop()


@pytest.mark.asyncio
async def test_phys_node_sys_init_fails_on_broken_node(tmp_path, admin_session):
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
            patch.object(buffer, "fetch_startup_data", AsyncMock(return_value=answer)),
            pytest.raises(NodeInitError) as exc_info,
        ):
            await buffer.phys_node_sys_init(admin_session)

        assert exc_info.value.node_proto_id == 2
        assert exc_info.value.field == "user_injectors[0].extractor_script"
    finally:
        await buffer.stop()


# ========== lifespan и сессия к админке ==========


@pytest.mark.asyncio
async def test_lifespan_closes_session_when_init_fails():
    """Админка недоступна при старте: исключение уходит наружу, но сессия закрыта, а буфер остановлен"""
    from node_client.main import lifespan

    app = FastAPI()
    stop = AsyncMock()
    with (
        patch.object(ConfigWriteBuffer, "phys_node_sys_init", AsyncMock(side_effect=AdminPanelError("нет админки"))),
        patch.object(ConfigWriteBuffer, "stop", stop),
        pytest.raises(AdminPanelError),
    ):
        async with lifespan(app):
            pass

    assert app.state.admin_aiohttp.closed
    stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_passes_one_session_to_init():
    """Инициализация получает ту же сессию, что лежит в app.state (её же отдаёт AioHttpAdminDep)"""
    from node_client.main import lifespan

    app = FastAPI()
    init = AsyncMock()
    with (
        patch.object(ConfigWriteBuffer, "phys_node_sys_init", init),
        patch.object(ConfigWriteBuffer, "stop", AsyncMock()),
    ):
        async with lifespan(app):
            session = app.state.admin_aiohttp
            assert not session.closed

    init.assert_awaited_once_with(session)
    assert session.closed


# ========== Настройки ==========


def test_settings_accept_legacy_node_name(monkeypatch):
    """Старые .env с NODE_NAME (до переименования) продолжают работать: обновление кода без install.sh не кладёт ноду"""
    from node_client.config import Settings

    monkeypatch.delenv("NODE_TITLE", raising=False)
    monkeypatch.setenv("NODE_NAME", "legacy-node")

    assert Settings().node_title == "legacy-node"


def test_settings_require_admin_panel_port(monkeypatch):
    """ADMIN_PANEL_PORT обязателен: без него нод-клиент не стартует, а не идёт молча на порт по умолчанию"""
    from node_client.config import Settings

    monkeypatch.delenv("ADMIN_PANEL_PORT", raising=False)

    with pytest.raises(ValidationError, match="admin_panel_port"):
        Settings()


# ========== Проверка элемента /startup ==========


@pytest.mark.asyncio
async def test_compile_node_rejects_empty_extractor(tmp_path):
    """Пустой extractor_script — ошибка регистрации, а не молча падающие записи конфига"""
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    item = create_vnode_item_with_config(tmp_path, 1, extractor_script="")

    with pytest.raises(NodeInitError) as exc_info:
        await buffer.compile_node(item)

    assert exc_info.value.field == "user_injectors[0].extractor_script"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("patch_item", "node_proto_id", "field"),
    [
        ({"node_proto_id": 0}, 0, "node_proto_id"),
        ({"node_proto_id": "abc"}, None, "node_proto_id"),
        ({"filepath": ""}, 1, "filepath"),
        ({"user_injectors": "не список"}, 1, "user_injectors"),
        ({"user_injectors": ["не словарь"]}, 1, "user_injectors[0]"),
        (
            {"user_injectors": [{"extractor_script": "def transform(u): return u"}]},
            1,
            "user_injectors[0].flatten_array_cursor",
        ),
    ],
)
async def test_compile_node_schema_errors_name_the_field(tmp_path, patch_item, node_proto_id, field):
    """Неверный элемент /startup — NodeInitError с именем поля (в reinit это 422 с полем), а не AttributeError/500"""
    item = create_vnode_item_with_config(tmp_path, 1) | patch_item

    with pytest.raises(NodeInitError) as exc_info:
        await ConfigWriteBuffer().compile_node(item)

    assert exc_info.value.node_proto_id == node_proto_id
    assert exc_info.value.field == field


@pytest.mark.asyncio
async def test_reload_core_respects_command_timeout():
    """Зависшая команда перезагрузки ядра не вешает запись (а с ней reinit и остановку) — обрывается по таймауту"""
    import time

    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    start = time.monotonic()
    with patch.object(env, "command_timeout", 1):
        await buffer._reload_core("sleep 30")
    assert time.monotonic() - start < 5
