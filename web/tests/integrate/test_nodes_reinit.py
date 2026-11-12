"""
Интеграционные тесты точечной реинициализации виртуальных нод из админки (бэклог F1)

POST /api/v1/private/nodes/{node_id}/reinit → POST {private_ip}:{api_port}/api/v1/server/node/reinit нод-клиента

Тестируем:
- запрос уходит на нод-клиент этой физической ноды только по приватному адресу
- ответ нод-клиента передаётся админу: 200 (registered/removed), 422 (битый шаблон), 502 (нод-клиент недоступен или
  сам не получил данные от админки)
- чужие и несуществующие node_proto_ids отклоняются до запроса на нод-клиент
- push после confirm не уходит на публичный адрес, если приватного нет
"""

import pytest

from web.tests.conftest import FakeAiohttpSession

REINIT_PATH = "/api/v1/server/node/reinit"


def reinit_url(node_id: int) -> str:
    return f"/api/v1/private/nodes/{node_id}/reinit"


async def node_address(db_pool, node_id: int) -> str:
    """Ожидаемый адрес реинициализации нод-клиента физической ноды"""
    async with db_pool.acquire() as conn:
        node = await conn.fetchrow("SELECT private_ip, api_port FROM nodes WHERE id = $1", node_id)
    return f"http://{node['private_ip']}:{node['api_port']}{REINIT_PATH}"


def reinit_calls(session: FakeAiohttpSession) -> list[tuple]:
    return [c for c in session.calls if c[1].endswith(REINIT_PATH)]


@pytest.mark.asyncio
async def test_reinit_selected_vnodes(client, virtual_node_seed, db_pool):
    """Выбранные виртуальные ноды → один POST на нод-клиент их физической ноды; ответ нод-клиента — админу"""
    node_id, vnode_id = virtual_node_seed["node_id_1"], virtual_node_seed["vnode_id_1"]
    node_answer = {"success": True, "registered": [vnode_id], "removed": []}
    session = FakeAiohttpSession(json_data=node_answer)
    client.app.state.cmd_center_aiohttp = session

    response = await client.post(reinit_url(node_id), json={"node_proto_ids": [vnode_id]})

    assert response.status_code == 200
    assert response.json() == node_answer
    assert reinit_calls(session) == [("POST", await node_address(db_pool, node_id), {"node_proto_ids": [vnode_id]})]


@pytest.mark.asyncio
async def test_reinit_empty_list_means_all(client, virtual_node_seed):
    """Пустой список (или пустое тело) — нод-клиент реинициализирует все виртуальные ноды физической ноды"""
    session = FakeAiohttpSession(json_data={"success": True, "registered": [], "removed": []})
    client.app.state.cmd_center_aiohttp = session

    response = await client.post(reinit_url(virtual_node_seed["node_id_1"]), json={})

    assert response.status_code == 200
    assert [c[2] for c in reinit_calls(session)] == [{"node_proto_ids": []}]


@pytest.mark.asyncio
async def test_reinit_rejects_foreign_vnodes(client, virtual_node_seed):
    """Нода с другой физической ноды и несуществующая нода → 400 с их ID, нод-клиент не трогаем"""
    session = FakeAiohttpSession()
    client.app.state.cmd_center_aiohttp = session
    foreign = [virtual_node_seed["vnode_id_3"], 2_000_000_000]

    response = await client.post(
        reinit_url(virtual_node_seed["node_id_1"]),
        json={"node_proto_ids": [virtual_node_seed["vnode_id_1"], *foreign]},
    )

    assert response.status_code == 400
    assert sorted(response.json()["detail"]["foreign_node_proto_ids"]) == sorted(foreign)
    assert not reinit_calls(session)


@pytest.mark.asyncio
async def test_reinit_unknown_node(client, db_seed):
    """Физической ноды нет → 404"""
    session = FakeAiohttpSession()
    client.app.state.cmd_center_aiohttp = session

    response = await client.post(reinit_url(32_000), json={})

    assert response.status_code == 404
    assert not reinit_calls(session)


@pytest.mark.asyncio
async def test_reinit_node_id_out_of_range(client, db_seed):
    """nodes.id — smallint: ID вне диапазона → 422 валидации, а не 500 из БД"""
    response = await client.post(reinit_url(2_000_000_000), json={})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reinit_node_without_private_ip(client, physical_node_seed, db_pool):
    """Без приватного адреса реинициализация невозможна (публичный адрес не используем) → 409"""
    node_id = physical_node_seed["node_id_1"]
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE nodes SET private_ip = NULL WHERE id = $1", node_id)
    session = FakeAiohttpSession()
    client.app.state.cmd_center_aiohttp = session

    response = await client.post(reinit_url(node_id), json={})

    assert response.status_code == 409
    assert not session.calls


@pytest.mark.asyncio
async def test_reinit_broken_template_passes_422(client, virtual_node_seed):
    """Нод-клиент не скомпилировал шаблон (память не изменена) → 422 с нодой, полем и причиной"""
    vnode_id = virtual_node_seed["vnode_id_1"]
    node_error = {
        "success": False,
        "node_proto_id": vnode_id,
        "field": "user_injectors[0].extractor_script",
        "reason": "SyntaxError",
    }
    client.app.state.cmd_center_aiohttp = FakeAiohttpSession(json_data=node_error, status=422)

    response = await client.post(reinit_url(virtual_node_seed["node_id_1"]), json={"node_proto_ids": [vnode_id]})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert (detail["node_proto_id"], detail["field"], detail["reason"]) == (
        vnode_id,
        "user_injectors[0].extractor_script",
        "SyntaxError",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session",
    [
        FakeAiohttpSession(raise_error=True),
        FakeAiohttpSession(
            json_data={"success": False, "message": "Не удалось получить данные от админки"}, status=502
        ),
        FakeAiohttpSession(json_data={"detail": "Forbidden"}, status=403),
    ],
    ids=["нод-клиент недоступен", "нод-клиент не достучался до админки", "нод-клиент отказал"],
)
async def test_reinit_node_client_failure_is_502(client, virtual_node_seed, session):
    """Любая неудача на стороне нод-клиента → 502 с причиной; статус нод-клиента виден в ответе"""
    client.app.state.cmd_center_aiohttp = session

    response = await client.post(reinit_url(virtual_node_seed["node_id_1"]), json={})

    assert response.status_code == 502
    assert response.json()["detail"]["success"] is False


# ========== push после confirm: только приватный адрес ==========


@pytest.mark.asyncio
async def test_confirm_push_never_uses_public_ip(client, physical_node_seed, proto_template_seed, db_pool):
    """Нет private_ip → push не уходит на публичный адрес, подтверждение регистрации при этом проходит"""
    node_id = physical_node_seed["node_id_1"]
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE nodes SET private_ip = NULL WHERE id = $1", node_id)
        node_proto_id = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, tmp_id, title, proto_port, config_path, reg_status)
            VALUES ($1, $2, 'No Private IP', 8471, '/tmp/no-private-ip.json', 1) RETURNING id
            """,
            node_id,
            proto_template_seed["tmp_id"],
        )
    session = FakeAiohttpSession()
    client.app.state.cmd_center_aiohttp = session

    response = await client.post(
        "/api/v1/server/nodes/protocols/confirm", json={"node_proto_id": node_proto_id, "status": 2}
    )

    assert response.status_code == 200
    assert not reinit_calls(session), f"push ушёл в обход приватной сети: {session.calls}"
