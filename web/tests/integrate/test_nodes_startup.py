"""
Интеграционные тесты для эндпоинта POST /api/v1/server/nodes/{node_title}/startup
"""

import pytest


class TestNodeStartup:
    """Тесты эндпоинта выдачи служебных данных виртуальных нод для нод-клиента."""

    @pytest.mark.asyncio
    async def test_startup_all_nodes_success(self, client, virtual_node_seed, db_pool):
        """WHEN node_proto_ids пуст THE админка возвращает все зарегистрированные ноды физической ноды."""
        node_title = "Test Physical Node 1"
        vnode_id_1 = virtual_node_seed["vnode_id_1"]

        # Добавим для полноты user_injectors к шаблону
        async with db_pool.acquire() as conn:
            tmp_id = await conn.fetchval("SELECT tmp_id FROM nodes_protocols WHERE id = $1", vnode_id_1)
            await conn.execute(
                """
                INSERT INTO templates_users_extractors (tmp_id, flatten_array_cursor, extractor_script, libs)
                VALUES ($1, $2, $3, $4)
                """,
                tmp_id,
                "inbounds___0___settings___clients",
                "def transform(user_obj):\n    return {'uuid': user_obj.get('uuid')}",
                "json,uuid",
            )

        response = await client.post(
            f"/api/v1/server/nodes/{node_title}/startup",
            json={"node_proto_ids": []},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["node_title"] == node_title
        assert data["missing"] == []
        # vnode_id_1 имеет reg_status=2 (success), vnode_id_2 имеет reg_status=1 (pending)
        vnode_ids = [n["node_proto_id"] for n in data["nodes"]]
        assert vnode_id_1 in vnode_ids
        assert virtual_node_seed["vnode_id_2"] not in vnode_ids

        # Проверяем структуру возвращаемых данных
        target_vnode = next(n for n in data["nodes"] if n["node_proto_id"] == vnode_id_1)
        assert target_vnode["filepath"] == "/etc/test-proto/config1.json"
        assert len(target_vnode["user_injectors"]) >= 1
        injector = target_vnode["user_injectors"][0]
        assert injector["flatten_array_cursor"] == "inbounds___0___settings___clients"
        assert "def transform" in injector["extractor_script"]
        assert injector["libs"] == "json,uuid"

    @pytest.mark.asyncio
    async def test_startup_filtered_nodes_and_missing(self, client, virtual_node_seed):
        """WHEN переданы конкретные node_proto_ids THE админка возвращает только их, а незарегистрированные в missing."""
        node_title = "Test Physical Node 1"
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]  # reg_status = 1 (pending)
        non_existent_id = 999999

        response = await client.post(
            f"/api/v1/server/nodes/{node_title}/startup",
            json={"node_proto_ids": [vnode_id_1, vnode_id_2, non_existent_id]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["node_title"] == node_title
        vnode_ids = [n["node_proto_id"] for n in data["nodes"]]
        assert vnode_ids == [vnode_id_1]
        assert set(data["missing"]) == {vnode_id_2, non_existent_id}

    @pytest.mark.asyncio
    async def test_startup_unknown_physical_node_404(self, client):
        """IF физической ноды с таким node_title нет THEN админка отвечает 404."""
        response = await client.post(
            "/api/v1/server/nodes/UnknownNonExistentPhysicalNode/startup",
            json={"node_proto_ids": []},
        )

        assert response.status_code == 404
        data = response.json()
        detail_msg = (
            data.get("detail", {}).get("message") if isinstance(data.get("detail"), dict) else data.get("detail", "")
        )
        assert "не найдена" in detail_msg

    @pytest.mark.asyncio
    async def test_startup_response_fields_match_schema(self, client, virtual_node_seed):
        """Ответ содержит ровно поля VnodeServiceData: без лишних столбцов (требование 1.9).

        В частности, нет metrics_parser_libs: в dev-базе этого столбца уже нет, а его выборка роняла /startup.
        """
        from web.schemas.node_schema import StartupResponse, VnodeServiceData

        response = await client.post(
            "/api/v1/server/nodes/Test Physical Node 1/startup",
            json={"node_proto_ids": [virtual_node_seed["vnode_id_1"]]},
        )

        assert response.status_code == 200
        data = response.json()
        assert set(data) == set(StartupResponse.model_fields)
        assert set(data["nodes"][0]) == set(VnodeServiceData.model_fields)

    @pytest.mark.asyncio
    async def test_startup_ignores_user_visible(self, client, virtual_node_seed, db_pool):
        """user_visible управляет только списком локаций у пользователей: скрытая нода всё равно обслуживается"""
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE nodes_protocols SET user_visible = false WHERE id = $1", vnode_id_1)

        response = await client.post("/api/v1/server/nodes/Test Physical Node 1/startup", json={"node_proto_ids": []})

        assert response.status_code == 200
        assert vnode_id_1 in [n["node_proto_id"] for n in response.json()["nodes"]]

    @pytest.mark.asyncio
    async def test_startup_excludes_other_physical_node(self, client, virtual_node_seed, db_pool):
        """Зарегистрированная нода другой физической ноды не отдаётся; запрошенная явно — попадает в missing"""
        async with db_pool.acquire() as conn:
            foreign_id = await conn.fetchval(
                """
                INSERT INTO nodes_protocols (node_id, tmp_id, title, config_path, reg_status)
                VALUES ($1, $2, 'Foreign Registered', '/etc/test-proto/foreign.json', 2)
                RETURNING id
                """,
                virtual_node_seed["node_id_2"],
                virtual_node_seed["tmp_id"],
            )

        all_nodes = await client.post("/api/v1/server/nodes/Test Physical Node 1/startup", json={"node_proto_ids": []})
        explicit = await client.post(
            "/api/v1/server/nodes/Test Physical Node 1/startup", json={"node_proto_ids": [foreign_id]}
        )

        assert foreign_id not in [n["node_proto_id"] for n in all_nodes.json()["nodes"]]
        assert explicit.json()["nodes"] == []
        assert explicit.json()["missing"] == [foreign_id]
