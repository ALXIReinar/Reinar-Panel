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
        offer_id = sub_plan_seed["offer_id_1"]
        
        response = await client.put(
            f"/api/v1/private/subscriptions/plans/{plan_id}",
            json={
                "title": "Updated Basic Plan",
                "description": "Updated description for basic plan",
                "is_active": False,
                "offers": [
                    {
                        "offer_id": offer_id,
                        "ttl_days": 60,
                        "cost": 1000,
                        "traffic_limit_day": 20480,
                        "traffic_limit_total": None,
                        "infinite_traffic": False,
                        "infinite_expire": False,
                        "is_active": False
                    }
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Группа подписок обновлена"
        assert data["offer_update_count"] == 1
        
        # Проверяем что данные обновились в БД
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        get_data = get_response.json()
        updated_plan = get_data["plan"]
        assert updated_plan["title"] == "Updated Basic Plan"
        assert updated_plan["description"] == "Updated description for basic plan"
        assert updated_plan["is_active"] is False
        
        # Проверяем offer
        offers = get_data["plan"]["offers"]
        assert len(offers) == 1
        offer = offers[0]
        assert offer["ttl_days"] == 60
        assert offer["cost"] == 1000
        assert offer["traffic_day_limit"] == 20480
        assert offer["is_active"] is False
    
    @pytest.mark.asyncio
    async def test_update_plan_partial(self, client, sub_plan_seed):
        """Частичное обновление (только title)"""
        plan_id = sub_plan_seed["plan_id_2"]
        offer_id = sub_plan_seed["offer_id_2"]
        
        response = await client.put(
            f"/api/v1/private/subscriptions/plans/{plan_id}",
            json={
                "title": "Renamed Premium Plan",
                "offers": []  # Пустой массив - ничего не обновляем в offers
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Проверяем что только title изменился, остальные поля остались прежними
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        get_data = get_response.json()
        updated_plan = get_data["plan"]
        assert updated_plan["title"] == "Renamed Premium Plan"
        
        # Старые значения в offer сохранились
        offers = get_data["plan"]["offers"]
        assert len(offers) == 1
        offer = offers[0]
        assert offer["ttl_days"] == 90
        assert offer["cost"] == 2000
        assert offer["infinite_traffic"] is True
        assert offer["is_active"] is False
    
    @pytest.mark.asyncio
    async def test_update_plan_attach_vnodes(self, client, sub_plan_seed, virtual_node_seed, mock_arq):
        """Добавление виртуальных нод через /locations endpoint"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        response = await client.put(
            f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
            json={
                "add_vnodes": [vnode_id_1, vnode_id_2],
                "remove_vnodes": []
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Поле attache_job_id может быть None если нет активных подписок на этот план
        assert "attache_job_id" in data
        assert data["detache_job_id"] is None  # Удаления не было
        
        # Проверяем что виртуальные ноды привязались
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        get_data = get_response.json()
        vnodes = get_data["plan"]["vnodes"]
        assert len(vnodes) == 2
        vnode_ids = [vnode["node_proto_id"] for vnode in vnodes]
        assert vnode_id_1 in vnode_ids
        assert vnode_id_2 in vnode_ids
    
    @pytest.mark.asyncio
    async def test_update_plan_detach_vnodes(self, client, sub_plan_seed, virtual_node_seed, db_pool, mock_arq):
        """Удаление виртуальных нод через /locations endpoint"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        # Сначала привязываем ноды
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2), ($1, $3)",
                plan_id, vnode_id_1, vnode_id_2
            )
        
        # Теперь отвязываем одну ноду
        response = await client.put(
            f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
            json={
                "add_vnodes": [],
                "remove_vnodes": [vnode_id_1]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Поле detache_job_id может быть None если нет активных подписок на этот план
        assert "detache_job_id" in data
        assert data["attache_job_id"] is None  # Добавления не было
        
        # Проверяем что осталась только одна нода
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        get_data = get_response.json()
        vnodes = get_data["plan"]["vnodes"]
        assert len(vnodes) == 1
        assert vnodes[0]["node_proto_id"] == vnode_id_2
    
    @pytest.mark.asyncio
    async def test_update_plan_attach_and_detach(self, client, sub_plan_seed, virtual_node_seed, db_pool, mock_arq):
        """Одновременный attach + detach виртуальных нод через /locations endpoint"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        vnode_id_3 = virtual_node_seed["vnode_id_3"]
        
        # Привязываем vnode_id_1
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2)",
                plan_id, vnode_id_1
            )
        
        # Отвязываем vnode_id_1 и привязываем vnode_id_2, vnode_id_3
        response = await client.put(
            f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
            json={
                "add_vnodes": [vnode_id_2, vnode_id_3],
                "remove_vnodes": [vnode_id_1]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Поля могут быть None если нет активных подписок на этот план
        assert "attache_job_id" in data
        assert "detache_job_id" in data
        
        # Проверяем результат
        get_response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        get_data = get_response.json()
        vnodes = get_data["plan"]["vnodes"]
        assert len(vnodes) == 2
        vnode_ids = [vnode["node_proto_id"] for vnode in vnodes]
        assert vnode_id_1 not in vnode_ids
        assert vnode_id_2 in vnode_ids
        assert vnode_id_3 in vnode_ids
    
    @pytest.mark.asyncio
    async def test_update_plan_attach_nonexistent_vnode(self, client, sub_plan_seed, mock_arq):
        """Attach несуществующих виртуальных нод через /locations endpoint - должен провалиться с ForeignKeyViolation"""
        plan_id = sub_plan_seed["plan_id_1"]
        
        # Пытаемся прикрепить несуществующие node_proto_id
        # ForeignKeyViolation должна быть поймана и преобразована в HTTP ошибку
        with pytest.raises(Exception):  # asyncpg.ForeignKeyViolationError поднимается как необработанное исключение
            response = await client.put(
                f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
                json={
                    "add_vnodes": [99999, 88888],  # Несуществующие ID
                    "remove_vnodes": []
                }
            )
    
    @pytest.mark.asyncio
    async def test_update_plan_detach_not_attached(self, client, sub_plan_seed, virtual_node_seed, mock_arq):
        """Detach виртуальных нод которые не привязаны - успешный DELETE но 0 строк удалено"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        # Пытаемся открепить ноды, которые не привязаны (без предварительного INSERT)
        response = await client.put(
            f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
            json={
                "add_vnodes": [],
                "remove_vnodes": [vnode_id_1, vnode_id_2]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Если ноды не были прикреплены, detache_job_id должен быть None (0 записей в outbox)
        # Или может быть job_id но с 0 операций
        # В зависимости от реализации - проверяем что нет ошибки
        assert "detache_job_id" in data
    
    @pytest.mark.asyncio
    async def test_update_plan_not_found_404(self, client, db_seed):
        """UPDATE несуществующего плана возвращает 404"""
        response = await client.put(
            "/api/v1/private/subscriptions/plans/99999",
            json={
                "title": "Updated Non-Existent Plan",
                "offers": []
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        detail = data.get("detail", data)
        assert detail["success"] is False
        assert "не найдена" in detail["message"]


class TestDeleteSubPlan:
    """Тесты для DELETE /api/v1/private/subscriptions/plans/delete"""
    
    @pytest.mark.asyncio
    async def test_delete_plan_success(self, client, sub_plan_seed, db_pool):
        """Успешное удаление плана"""
        plan_id = sub_plan_seed["plan_id_2"]
        
        response = await client.delete(
            f"/api/v1/private/subscriptions/plans/{plan_id}"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Группа подписок удалена"
        
        # Проверяем что план действительно удалён
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_plans WHERE id = $1)",
                plan_id
            )
            assert exists is False
    
    @pytest.mark.asyncio
    async def test_delete_plan_cascade(self, client, sub_plan_seed, virtual_node_seed, db_pool):
        """CASCADE удаление связей в vnodes_sub_plans"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Привязываем виртуальную ноду к плану
        async with db_pool.acquire() as conn:
            link_id = await conn.fetchval(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2) RETURNING id",
                plan_id, vnode_id
            )
        
        # Проверяем что связь существует
        async with db_pool.acquire() as conn:
            link_exists_before = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM vnodes_sub_plans WHERE id = $1)",
                link_id
            )
            assert link_exists_before is True
        
        # Удаляем план
        response = await client.delete(
            f"/api/v1/private/subscriptions/plans/{plan_id}"
        )
        assert response.status_code == 200
        
        # Проверяем что связь тоже удалилась (CASCADE)
        async with db_pool.acquire() as conn:
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
        assert "is_active" in plan
        assert "sub_nodes_count" in plan
        assert "offers_count" in plan


class TestGetSubPlanById:
    """Тесты для GET /api/v1/private/subscriptions/plans/get/{plan_id}"""
    
    @pytest.mark.asyncio
    async def test_get_plan_with_vnodes(self, client, sub_plan_seed, virtual_node_seed, db_pool):
        """Успешное получение плана с привязанными виртуальными нодами"""
        plan_id = sub_plan_seed["plan_id_1"]
        vnode_id_1 = virtual_node_seed["vnode_id_1"]
        vnode_id_2 = virtual_node_seed["vnode_id_2"]
        
        # Привязываем виртуальные ноды к плану
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) VALUES ($1, $2), ($1, $3)",
                plan_id, vnode_id_1, vnode_id_2
            )
        
        response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plan" in data
        assert "vnodes" in data["plan"]
        assert "offers" in data["plan"]
        
        # Проверяем данные плана
        plan = data["plan"]
        assert plan["title"] == "Basic Plan"
        assert plan["is_active"] is True
        
        # Проверяем offers
        offers = data["plan"]["offers"]
        assert len(offers) == 1
        offer = offers[0]
        assert offer["ttl_days"] == 30
        assert offer["cost"] == 500
        assert offer["traffic_day_limit"] == 10240
        
        # Проверяем виртуальные ноды
        vnodes = data["plan"]["vnodes"]
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
        
        response = await client.get(f"/api/v1/private/subscriptions/plans/{plan_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "plan" in data
        assert "vnodes" in data["plan"]
        assert "offers" in data["plan"]
        assert len(data["plan"]["vnodes"]) == 0
        
        # Проверяем offers
        offers = data["plan"]["offers"]
        assert len(offers) == 1
        offer = offers[0]
        assert offer["ttl_days"] == 90
        assert offer["cost"] == 2000
        assert offer["infinite_traffic"] is True
    
    @pytest.mark.asyncio
    async def test_get_plan_not_found(self, client, db_seed):
        """План не найден (404)"""
        response = await client.get("/api/v1/private/subscriptions/plans/9999")
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Группа подписок не найдена"
