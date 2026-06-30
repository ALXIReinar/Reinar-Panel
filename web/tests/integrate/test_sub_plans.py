"""
Интеграционные тесты для API планов подписок (sub_plans_api.py)
Тестируют CRUD операции с планами подписок и привязку виртуальных нод
"""
import pytest


class TestCreateSubPlan:
    """Тесты для POST /api/v1/private/subscriptions/plans/create"""
    
    @pytest.mark.asyncio
    async def test_create_plan_success(self, client, db_seed):
        """Успешное создание плана подписки"""
        response = await client.post(
            "/api/v1/private/subscriptions/plans/create",
            json={
                "title": "New Test Plan"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plan" in data
        assert data["message"] == "Группа подписок создана"
        assert isinstance(data["plan"], int)
    
    @pytest.mark.asyncio
    async def test_create_plan_duplicate(self, client, sub_plan_seed):
        """Дубликат title (409 Conflict) - ON CONFLICT DO NOTHING"""
        response = await client.post(
            "/api/v1/private/subscriptions/plans/create",
            json={
                "title": "Basic Plan"  # Уже существует в sub_plan_seed
            }
        )
        
        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["success"] is False
        assert "уже существует" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_create_plan_empty_title(self, client, db_seed):
        """Валидация: пустое название (422)"""
        response = await client.post(
            "/api/v1/private/subscriptions/plans/create",
            json={
                "title": ""
            }
        )
        
        assert response.status_code == 422  # Pydantic validation error


class TestUpdateSubPlan:
    """Тесты для PUT /api/v1/private/subscriptions/plans/update"""
    
    @pytest.mark.asyncio
    async def test_update_plan_full(self, client, sub_plan_seed):
        """Полное обновление всех полей плана"""
        plan_id = sub_plan_seed["plan_id_1"]
        
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "title": "Updated Basic Plan",
                "description": "Updated description for basic plan",
                "ttl_days": 60,
                "cost": 1000,
                "traffic_limit_day": 20480,
                "is_active": False
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Группа подписок обновлена"
        
        # Проверяем что данные обновились в БД
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        updated_plan = get_response.json()["plan"]
        assert updated_plan["title"] == "Updated Basic Plan"
        assert updated_plan["description"] == "Updated description for basic plan"
        assert updated_plan["ttl_days"] == 60
        assert updated_plan["cost"] == 1000
        assert updated_plan["traffic_limit_day"] == 20480
        assert updated_plan["is_active"] is False
    
    @pytest.mark.asyncio
    async def test_update_plan_partial(self, client, sub_plan_seed):
        """Частичное обновление (только title)"""
        plan_id = sub_plan_seed["plan_id_2"]
        
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "title": "Renamed Premium Plan"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что только title изменился, остальные поля остались прежними
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        updated_plan = get_response.json()["plan"]
        assert updated_plan["title"] == "Renamed Premium Plan"
        # Старые значения сохранились
        assert updated_plan["ttl_days"] == 90
        assert updated_plan["cost"] == 2000
        assert updated_plan["traffic_limit_day"] == -1
        assert updated_plan["is_active"] is False
    
    @pytest.mark.asyncio
    async def test_update_plan_attach_vnodes(self, client, sub_plan_seed, virtual_node_seed):
        """Обновление с attach виртуальных нод (add_node_proto_ids)"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "add_node_proto_ids": [vnode_id_1, vnode_id_2]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["attache_res"]["status_code"] == 200
        assert "2 нод" in data["attache_res"]["attached_msg"]
        
        # Проверяем что виртуальные ноды привязались
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        vnodes = get_response.json()["vnodes"]
        assert len(vnodes) == 2
        vnode_ids = [vnode["node_proto_id"] for vnode in vnodes]
        assert vnode_id_1 in vnode_ids
        assert vnode_id_2 in vnode_ids
    
    @pytest.mark.asyncio
    async def test_update_plan_detach_vnodes(self, client, sub_plan_seed, virtual_node_seed, pg_pool):
        """Обновление с detach виртуальных нод (remove_node_proto_ids)"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        # Сначала привязываем ноды
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2), ($1, $3)",
                plan_id, vnode_id_1, vnode_id_2
            )
        
        # Теперь отвязываем одну ноду
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "remove_node_proto_ids": [vnode_id_1]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["detach_res"]["status_code"] == 200
        assert "Успешно открепили" in data["detach_res"]["detach_message"]
        
        # Проверяем что осталась только одна нода
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        vnodes = get_response.json()["vnodes"]
        assert len(vnodes) == 1
        assert vnodes[0]["node_proto_id"] == vnode_id_2
    
    @pytest.mark.asyncio
    async def test_update_plan_attach_and_detach(self, client, sub_plan_seed, virtual_node_seed, pg_pool):
        """Одновременный attach + detach виртуальных нод"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        vnode_id_3 = virtual_node_seed["vnode_id_3"]
        
        # Привязываем vnode_id_1
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2)",
                plan_id, vnode_id_1
            )
        
        # Отвязываем vnode_id_1 и привязываем vnode_id_2, vnode_id_3
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "add_node_proto_ids": [vnode_id_2, vnode_id_3],
                "remove_node_proto_ids": [vnode_id_1]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["attache_res"]["status_code"] == 200
        assert data["detach_res"]["status_code"] == 200
        
        # Проверяем результат
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        vnodes = get_response.json()["vnodes"]
        assert len(vnodes) == 2
        vnode_ids = [vnode["node_proto_id"] for vnode in vnodes]
        assert vnode_id_1 not in vnode_ids
        assert vnode_id_2 in vnode_ids
        assert vnode_id_3 in vnode_ids
    
    @pytest.mark.asyncio
    async def test_update_plan_attach_nonexistent_vnode(self, client, sub_plan_seed):
        """Attach несуществующих виртуальных нод (404 ForeignKeyViolation)"""
        plan_id = sub_plan_seed["plan_id_1"]
        
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "add_node_proto_ids": [9999, 8888]  # Несуществующие ID
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # attach вернёт статус 404 с сообщением об ошибке FK
        assert data["attache_res"]["status_code"] == 404
        assert "не существуют" in data["attache_res"]["attached_msg"]
    
    @pytest.mark.asyncio
    async def test_update_plan_detach_not_attached(self, client, sub_plan_seed, virtual_node_seed):
        """Detach виртуальных нод которые не привязаны (409 - частичный успех)"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        # Пытаемся открепить ноды, которые не привязаны
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": plan_id,
                "remove_node_proto_ids": [vnode_id_1, vnode_id_2]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # detach вернёт статус 409 если не все ноды откреплены
        assert data["detach_res"]["status_code"] == 409
        assert "Некоторые ноды не были откреплены" in data["detach_res"]["detach_message"]
    
    @pytest.mark.asyncio
    async def test_update_plan_not_found(self, client, db_seed):
        """План не найден (404)"""
        response = await client.put(
            "/api/v1/private/subscriptions/plans/update",
            json={
                "id": 9999,
                "title": "Non-Existent Plan"
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдена" in data["detail"]["message"]


class TestDeleteSubPlan:
    """Тесты для DELETE /api/v1/private/subscriptions/plans/delete"""
    
    @pytest.mark.asyncio
    async def test_delete_plan_success(self, client, sub_plan_seed, pg_pool):
        """Успешное удаление плана"""
        plan_id = sub_plan_seed["plan_id_2"]
        
        response = await client.request(
            "DELETE",
            "/api/v1/private/subscriptions/plans/delete",
            json={"id": plan_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Группа подписок удалена"
        
        # Проверяем что план действительно удалён
        async with pg_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_plans WHERE id = $1)",
                plan_id
            )
            assert exists is False
    
    @pytest.mark.asyncio
    async def test_delete_plan_cascade(self, client, sub_plan_seed, virtual_node_seed, pg_pool):
        """CASCADE удаление связей в vnodes_sub_plans"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Привязываем виртуальную ноду к плану
        async with pg_pool.acquire() as conn:
            link_id = await conn.fetchval(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2) RETURNING id",
                plan_id, vnode_id
            )
        
        # Проверяем что связь существует
        async with pg_pool.acquire() as conn:
            link_exists_before = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM vnodes_sub_plans WHERE id = $1)",
                link_id
            )
            assert link_exists_before is True
        
        # Удаляем план
        response = await client.request(
            "DELETE",
            "/api/v1/private/subscriptions/plans/delete",
            json={"id": plan_id}
        )
        assert response.status_code == 200
        
        # Проверяем что связь тоже удалилась (CASCADE)
        async with pg_pool.acquire() as conn:
            link_exists_after = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM vnodes_sub_plans WHERE id = $1)",
                link_id
            )
            assert link_exists_after is False


class TestGetAllSubPlans:
    """Тесты для GET /api/v1/private/subscriptions/plans/all"""
    
    @pytest.mark.asyncio
    async def test_get_all_plans_empty(self, client, db_seed):
        """Получение пустого списка планов"""
        response = await client.get("/api/v1/private/subscriptions/plans/all?limit=20")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plans" in data
        assert len(data["plans"]) == 0
    
    @pytest.mark.asyncio
    async def test_get_all_plans_with_data(self, client, sub_plan_seed):
        """Получение списка с несколькими планами"""
        response = await client.get("/api/v1/private/subscriptions/plans/all?limit=20")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plans" in data
        assert len(data["plans"]) == 2
        
        # Проверяем структуру данных
        plan = data["plans"][0]
        assert "id" in plan
        assert "title" in plan
        assert "cost" in plan
        assert "ttl_days" in plan
        assert "traffic_limit_day" in plan
        assert "is_active" in plan


class TestGetSubPlanById:
    """Тесты для GET /api/v1/private/subscriptions/plans/get/{plan_id}"""
    
    @pytest.mark.asyncio
    async def test_get_plan_with_vnodes(self, client, sub_plan_seed, virtual_node_seed, pg_pool):
        """Успешное получение плана с привязанными виртуальными нодами"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        # Привязываем виртуальные ноды к плану
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2), ($1, $3)",
                plan_id, vnode_id_1, vnode_id_2
            )
        
        response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plan" in data
        assert "vnodes" in data
        
        # Проверяем данные плана
        plan = data["plan"]
        assert plan["title"] == "Basic Plan"
        assert plan["ttl_days"] == 30
        assert plan["cost"] == 500
        
        # Проверяем виртуальные ноды
        vnodes = data["vnodes"]
        assert len(vnodes) == 2
        vnode_ids = [vnode["node_proto_id"] for vnode in vnodes]
        assert vnode_id_1 in vnode_ids
        assert vnode_id_2 in vnode_ids
        
        # Проверяем структуру данных виртуальных нод
        vnode = vnodes[0]
        assert "link_id" in vnode
        assert "node_proto_id" in vnode
        assert "node_id" in vnode
        assert "proto_id" in vnode
        assert "node_title" in vnode
        assert "proto_title" in vnode
    
    @pytest.mark.asyncio
    async def test_get_plan_without_vnodes(self, client, sub_plan_seed):
        """План без привязанных виртуальных нод"""
        plan_id = sub_plan_seed["plan_id_2"]
        
        response = await client.get(f"/api/v1/private/subscriptions/plans/get/{plan_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plan" in data
        assert "vnodes" in data
        assert len(data["vnodes"]) == 0
    
    @pytest.mark.asyncio
    async def test_get_plan_not_found(self, client, db_seed):
        """План не найден (404)"""
        response = await client.get("/api/v1/private/subscriptions/plans/get/9999")
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Группа подписок не найдена"
