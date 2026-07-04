"""
Интеграционные тесты для эндпоинтов работы с шаблонами протоколов (/private/templates).
Тестирует CRUD операции для шаблонов конфиг-ссылок.
"""
import pytest
from httpx import AsyncClient


# ==================== GET /private/templates/all ====================

@pytest.mark.asyncio
async def test_get_all_templates_empty(client: AsyncClient, db_seed):
    """Получение пустого списка шаблонов"""
    response = await client.get("/api/v1/private/templates/all")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "templates" in data
    assert data["templates"] == []
    assert "spec_params" in data
    assert data["spec_params"] == []


@pytest.mark.asyncio
async def test_get_all_templates_multiple(client: AsyncClient, proto_template_seed):
    """Получение списка с несколькими шаблонами"""
    # proto_template_seed создаёт 2 шаблона
    response = await client.get("/api/v1/private/templates/all")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["templates"]) == 2
    
    # Проверяем структуру данных
    first_tmp = data["templates"][0]
    assert "id" in first_tmp
    assert "title" in first_tmp
    assert "url_tmp" in first_tmp
    assert "status" in first_tmp
    assert "is_accepted" in first_tmp
    assert "proto_python_lib" in first_tmp


@pytest.mark.asyncio
async def test_get_all_templates_pagination(client: AsyncClient, db_seed, db_pool):
    """Проверка cursor-based пагинации (last_id, asc/desc)"""
    # Создаём 5 шаблонов
    async with db_pool.acquire() as conn:
        tmp_ids = []
        for i in range(5):
            tmp_id = await conn.fetchval(
                "INSERT INTO proto_templates (title, status) VALUES ($1, $2) RETURNING id",
                f"Template_{i}",
                1
            )
            tmp_ids.append(tmp_id)
    
    # Запрос с limit=2, desc (по умолчанию)
    response = await client.get("/api/v1/private/templates/all?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["templates"]) == 2
    # DESC: получаем последние 2 (с наибольшими ID)
    first_id = data["templates"][0]["id"]
    
    # Запрос со следующей страницей (last_id)
    response = await client.get(f"/api/v1/private/templates/all?limit=2&last_id={first_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["templates"]) <= 2
    # Все ID должны быть меньше first_id (т.к. sort_by=desc)
    for tmp in data["templates"]:
        assert tmp["id"] < first_id
    
    # Запрос с asc сортировкой
    response = await client.get("/api/v1/private/templates/all?limit=2&sort_by=asc")
    assert response.status_code == 200
    data = response.json()
    assert len(data["templates"]) == 2
    # ASC: получаем первые 2 (с наименьшими ID)
    assert data["templates"][0]["id"] < data["templates"][1]["id"]


@pytest.mark.asyncio
async def test_get_all_templates_limit_boundary(client: AsyncClient, db_seed, db_pool):
    """Граничный случай: limit=100 (максимум)"""
    # Создаём 50 шаблонов
    async with db_pool.acquire() as conn:
        for i in range(50):
            await conn.execute(
                "INSERT INTO proto_templates (title, status) VALUES ($1, $2)",
                f"Template_{i:02d}",
                1
            )
    
    # Запрос с максимальным limit
    response = await client.get("/api/v1/private/templates/all?limit=100")
    assert response.status_code == 200
    data = response.json()
    assert len(data["templates"]) == 50


# ==================== GET /private/templates/by_id ====================

@pytest.mark.asyncio
async def test_get_template_by_id_full(client: AsyncClient, proto_template_seed, db_pool):
    """Успешное получение полных данных шаблона с spec_params (spec_only=false)"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Создаём spec параметры для шаблона
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO template_spec_params (key, tmp_id) VALUES ($1, $2), ($3, $4)",
            "pbk", tmp_id, "flow", tmp_id
        )
    
    # Получаем полные данные
    response = await client.get(f"/api/v1/private/templates/by_id?tmp_id={tmp_id}&so=false")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "template" in data
    
    template = data["template"]
    assert "template" in template
    assert template["template"]["id"] == tmp_id
    assert template["template"]["title"] == "TestProtocol Template"
    
    # Проверяем spec_params
    assert "spec_params" in template
    assert len(template["spec_params"]) == 2
    spec_keys = [param["key"] for param in template["spec_params"]]
    assert "pbk" in spec_keys
    assert "flow" in spec_keys


@pytest.mark.asyncio
async def test_get_template_by_id_spec_only(client: AsyncClient, proto_template_seed, db_pool):
    """Облегчённая версия (spec_only=true) - только spec_params"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Создаём spec параметры
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO template_spec_params (key, tmp_id) VALUES ($1, $2)",
            "security", tmp_id
        )
    
    # Получаем только spec_params
    response = await client.get(f"/api/v1/private/templates/by_id?tmp_id={tmp_id}&so=true")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "template" in data
    
    # spec_only=true возвращает только spec_params
    template = data["template"]
    assert "spec_params" in template
    assert len(template["spec_params"]) >= 1


@pytest.mark.asyncio
async def test_get_template_by_id_not_found(client: AsyncClient, db_seed):
    """Несуществующий tmp_id возвращает 404"""
    response = await client.get("/api/v1/private/templates/by_id?tmp_id=9999&so=false")
    
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Шаблон не найден"


# ==================== POST /private/templates/add ====================

@pytest.mark.asyncio
async def test_add_template_success(client: AsyncClient, db_seed):
    """Успешное создание шаблона"""
    response = await client.post(
        "/api/v1/private/templates/add",
        json={"title": "New Template"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "template_id" in data
    assert data["template_id"] is not None
    assert data["message"] == "Шаблон создан"


@pytest.mark.asyncio
async def test_add_template_duplicate_title(client: AsyncClient, proto_template_seed):
    """Попытка создать дубликат title (409 Conflict)"""
    # Пытаемся создать шаблон с существующим title
    response = await client.post(
        "/api/v1/private/templates/add",
        json={"title": "TestProtocol Template"}  # Уже существует из фикстуры
    )
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["success"] is False
    assert "уже существует" in data["detail"]["message"]


# ==================== PUT /private/templates/update ====================

@pytest.mark.asyncio
async def test_update_template_success(client: AsyncClient, proto_template_seed):
    """Успешное обновление базовых полей шаблона"""
    tmp_id = proto_template_seed["tmp_id"]
    
    update_data = {
        "tmp_id": tmp_id,
        "title": "Updated Template",
        "url_tmp": "vless://{user_uuid}@example.com:443",
        "reload_core_command": "systemctl reload xray",
        "proto_python_lib": "grpcio",
        "required_user_data_obj": {"email": "{email}", "uuid": "{uuid}"},
        "constant_user_data_obj": {"protocol": "vless", "encryption": "none"}
    }
    
    response = await client.put(
        "/api/v1/private/templates/update",
        json=update_data
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Шаблон обновлён"
    
    # Проверяем, что данные действительно обновились
    get_response = await client.get(f"/api/v1/private/templates/by_id?tmp_id={tmp_id}&so=false")
    template_data = get_response.json()["template"]["template"]
    assert template_data["title"] == "Updated Template"
    assert template_data["proto_python_lib"] == "grpcio"


@pytest.mark.asyncio
async def test_update_template_not_found(client: AsyncClient, db_seed):
    """Обновление несуществующего шаблона возвращает 404"""
    response = await client.put(
        "/api/v1/private/templates/update",
        json={
            "tmp_id": 9999,
            "title": "NonExistent"
        }
    )
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["message"] == "Шаблон не найден"


@pytest.mark.asyncio
async def test_update_template_url_validation(client: AsyncClient, proto_template_seed):
    """Валидация url_tmp: должен содержать {user_uuid}"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Пытаемся обновить url_tmp без обязательного плейсхолдера
    response = await client.put(
        "/api/v1/private/templates/update",
        json={
            "tmp_id": tmp_id,
            "url_tmp": "vless://invalid@example.com:443"  # Нет {user_uuid}
        }
    )
    
    assert response.status_code == 422  # Validation error
    data = response.json()
    assert "detail" in data
    # Проверяем, что ошибка связана с валидацией url_tmp
    error_msg = str(data["detail"])
    assert "user_uuid" in error_msg.lower() or "плейсхолдер" in error_msg.lower()


# ==================== DELETE /private/templates/delete ====================

@pytest.mark.asyncio
async def test_delete_template_success(client: AsyncClient, db_seed, db_pool):
    """Успешное удаление шаблона"""
    # Создаём шаблон для удаления
    async with db_pool.acquire() as conn:
        tmp_id = await conn.fetchval(
            "INSERT INTO proto_templates (title, status) VALUES ($1, $2) RETURNING id",
            "ToDelete",
            1
        )
    
    # Удаляем шаблон
    response = await client.delete(f"/api/v1/private/templates/delete?tmp_id={tmp_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Шаблон удалён"
    
    # Проверяем, что шаблон действительно удалён
    get_response = await client.get(f"/api/v1/private/templates/by_id?tmp_id={tmp_id}&so=false")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_template_not_found(client: AsyncClient, db_seed):
    """Удаление несуществующего шаблона возвращает 404"""
    response = await client.delete("/api/v1/private/templates/delete?tmp_id=9999")
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["message"] == "Шаблон не найден"


@pytest.mark.asyncio
async def test_delete_template_used_by_protocol(client: AsyncClient, proto_template_seed, db_pool):
    """Удаление шаблона, используемого протоколом (409 Conflict)"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Создаём протокол, использующий этот шаблон
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO protocols (name, tmp_id) VALUES ($1, $2)",
            "UsedProtocol",
            tmp_id
        )
    
    # Пытаемся удалить используемый шаблон
    response = await client.delete(f"/api/v1/private/templates/delete?tmp_id={tmp_id}")
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["success"] is False
    assert "используется" in data["detail"]["message"]
