"""
Интеграционные тесты для эндпоинтов работы с шаблонами протоколов (/private/templates).
Тестирует CRUD операции для шаблонов конфиг-ссылок.
"""
import pytest
from httpx import AsyncClient


# ==================== GET /private/templates/all ====================

@pytest.mark.asyncio
async def test_get_all_templates_multiple(client: AsyncClient, proto_template_seed):
    """Получение списка с несколькими шаблонами (включая seed_data)"""
    # proto_template_seed создаёт 2 тестовых шаблона, но в БД также есть seed_data шаблоны
    response = await client.get("/api/v1/private/templates/all")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "templates" in data
    # Должно быть минимум 2 шаблона (наши тестовые) + seed_data
    assert len(data["templates"]) >= 2
    
    # Проверяем структуру данных первого шаблона
    first_tmp = data["templates"][0]
    assert "id" in first_tmp
    assert "title" in first_tmp
    assert "url_tmp" in first_tmp
    assert "status" in first_tmp
    assert "is_accepted" in first_tmp
    assert "proto_python_lib" in first_tmp
    # Теперь spec_params встроены в каждый шаблон
    assert "spec_params" in first_tmp


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
    # Создаём 50 тестовых шаблонов (в БД уже есть ~24 seed_data шаблона)
    async with db_pool.acquire() as conn:
        for i in range(50):
            await conn.execute(
                "INSERT INTO proto_templates (title, status) VALUES ($1, $2)",
                f"test-LimitBoundary-{i:02d}",
                1
            )
    
    # Запрос с максимальным limit
    response = await client.get("/api/v1/private/templates/all?limit=100")
    assert response.status_code == 200
    data = response.json()
    # Должно быть 50 наших + seed_data (всего ~74), но ограничено лимитом 100
    assert len(data["templates"]) >= 50
    assert len(data["templates"]) <= 100


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
    response = await client.get(f"/api/v1/private/templates/{tmp_id}?so=false")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "template" in data
    
    # API возвращает template напрямую (без лишней вложенности)
    template = data["template"]
    assert template["id"] == tmp_id
    assert template["title"] == "test-TestProtocol-1"
    
    # Проверяем spec_params
    assert "spec_params" in template
    assert len(template["spec_params"]) == 2
    spec_keys = [param["key_name"] for param in template["spec_params"]]
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
    response = await client.get(f"/api/v1/private/templates/{tmp_id}?so=true")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # spec_only=true возвращает spec_params напрямую (без лишней вложенности)
    assert "spec_params" in data
    assert len(data["spec_params"]) >= 1


@pytest.mark.asyncio
async def test_get_template_by_id_not_found(client: AsyncClient, db_seed):
    """Несуществующий tmp_id возвращает 404"""
    response = await client.get("/api/v1/private/templates/9999?so=false")
    
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Шаблон не найден"


# ==================== POST /private/templates/add ====================

@pytest.mark.asyncio
async def test_add_template_success(client: AsyncClient, db_seed):
    """Успешное создание шаблона"""
    response = await client.post(
        "/api/v1/private/templates/create",
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
        "/api/v1/private/templates/create",
        json={"title": "test-TestProtocol-1"}  # Исправлено название из фикстуры
    )
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["success"] is False
    assert "уже существует" in data["detail"]["message"]


# ==================== PUT /private/templates/update ====================

@pytest.mark.asyncio
async def test_update_template_success(client: AsyncClient, proto_template_seed, db_pool):
    """Успешное обновление базовых полей шаблона"""
    tmp_id = proto_template_seed["tmp_id"]
    
    update_data = {
        # НЕ обновляем title - оставляем как есть, чтобы шаблон не попал под очистку
        "url_tmp": "vless://{user_uuid}@updated.example.com:8443",
        "reload_core_command": "systemctl reload xray-updated",
        "proto_python_lib": "grpcio-updated",
        "required_user_data_obj": {"email": "{email}", "uuid": "{uuid}", "updated": "true"},
        "constant_user_data_obj": {"protocol": "vless", "encryption": "none", "updated": "true"}
    }
    
    response = await client.put(
        f"/api/v1/private/templates/{tmp_id}",
        json=update_data
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Шаблон обновлён"
    
    # Проверяем, что данные действительно обновились в БД (проверяем все кроме title)
    async with db_pool.acquire() as conn:
        template = await conn.fetchrow(
            """
            SELECT url_tmp, reload_core_command, proto_python_lib, 
                   required_user_data_obj, constant_user_data_obj 
            FROM proto_templates WHERE id = $1
            """,
            tmp_id
        )
        assert template is not None
        assert template["url_tmp"] == "vless://{user_uuid}@updated.example.com:8443"
        assert template["reload_core_command"] == "systemctl reload xray-updated"
        assert template["proto_python_lib"] == "grpcio-updated"
        assert template["required_user_data_obj"]["updated"] == "true"
        assert template["constant_user_data_obj"]["updated"] == "true"


@pytest.mark.asyncio
async def test_update_template_not_found(client: AsyncClient, db_seed):
    """Обновление несуществующего шаблона возвращает 404"""
    response = await client.put(
        f"/api/v1/private/templates/9999",
        json={
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
        f"/api/v1/private/templates/{tmp_id}",
        json={
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
    response = await client.delete(f"/api/v1/private/templates/{tmp_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Шаблон удалён"
    
    # Проверяем, что шаблон действительно удалён
    get_response = await client.get(f"/api/v1/private/templates/{tmp_id}?so=false")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_template_not_found(client: AsyncClient, db_seed):
    """Удаление несуществующего шаблона возвращает 404"""
    response = await client.delete("/api/v1/private/templates/9999")
    
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
    response = await client.delete(f"/api/v1/private/templates/{tmp_id}")
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["success"] is False
    assert "используется" in data["detail"]["message"]


# ==================== PUT /private/templates/{tmp_id}/user_injectors ====================

@pytest.mark.asyncio
async def test_update_user_injectors_success(client: AsyncClient, proto_template_seed, db_pool):
    """Успешное обновление user_injectors шаблона"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Данные для user_injectors с валидным extractor_script (должна быть функция def transform)
    injectors_data = {
        "user_injectors": [
            {
                "flatten_array_cursor": "inbounds___0___settings___clients",
                "extractor_script": "def transform(user_obj):\n    return user_obj['id']",
                "libs": None  # Может быть None
            },
            {
                "flatten_array_cursor": "inbounds___0___settings___users",
                "extractor_script": "def transform(user_obj):\n    return user_obj['password']",
                "libs": "hashlib"  # Строка
            },
            {
                "flatten_array_cursor": "inbounds___1___settings___auth",
                "extractor_script": "def transform(user_obj):\n    return user_obj.get('token', '')",
                "libs": ["json", "base64"]  # Список строк
            }
        ]
    }
    
    response = await client.put(
        f"/api/v1/private/templates/{tmp_id}/user_injectors",
        json=injectors_data
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Инжекторы обновлены"
    
    # Проверяем что инжекторы действительно сохранились в templates_users_extractors
    async with db_pool.acquire() as conn:
        injectors = await conn.fetch(
            "SELECT flatten_array_cursor, extractor_script, libs FROM templates_users_extractors WHERE tmp_id = $1 ORDER BY id",
            tmp_id
        )
        assert len(injectors) == 3
        assert injectors[0]["flatten_array_cursor"] == "inbounds___0___settings___clients"
        assert "def transform" in injectors[0]["extractor_script"]
        assert injectors[0]["libs"] is None
        assert injectors[1]["flatten_array_cursor"] == "inbounds___0___settings___users"
        assert "def transform" in injectors[1]["extractor_script"]
        assert injectors[1]["libs"] == "hashlib"
        assert injectors[2]["flatten_array_cursor"] == "inbounds___1___settings___auth"
        assert "def transform" in injectors[2]["extractor_script"]
        assert injectors[2]["libs"] == "json,base64"  # Список преобразуется в строку через запятую


@pytest.mark.asyncio
async def test_update_user_injectors_replaces_existing(client: AsyncClient, proto_template_seed, db_pool):
    """Обновление user_injectors заменяет существующие (удаляет старые и вставляет новые)"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Создаём начальные инжекторы с валидным extractor_script
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO templates_users_extractors (tmp_id, flatten_array_cursor, extractor_script) VALUES ($1, $2, $3), ($1, $4, $5)",
            tmp_id, 
            "old_cursor_1", "def transform(user_obj):\n    return user_obj['old1']",
            "old_cursor_2", "def transform(user_obj):\n    return user_obj['old2']"
        )
    
    # Обновляем инжекторы (должны заменить старые)
    new_injectors = {
        "user_injectors": [
            {
                "flatten_array_cursor": "new_cursor",
                "extractor_script": "def transform(user_obj):\n    return user_obj['new_field']",
                "libs": ["json"]  # Список строк
            }
        ]
    }
    
    response = await client.put(
        f"/api/v1/private/templates/{tmp_id}/user_injectors",
        json=new_injectors
    )
    
    assert response.status_code == 200
    
    # Проверяем что старые удалены, новые вставлены
    async with db_pool.acquire() as conn:
        injectors = await conn.fetch(
            "SELECT flatten_array_cursor, extractor_script, libs FROM templates_users_extractors WHERE tmp_id = $1",
            tmp_id
        )
        assert len(injectors) == 1
        assert injectors[0]["flatten_array_cursor"] == "new_cursor"
        assert "def transform" in injectors[0]["extractor_script"]
        assert "new_field" in injectors[0]["extractor_script"]
        assert injectors[0]["libs"] == "json"


@pytest.mark.asyncio
async def test_update_user_injectors_empty_list(client: AsyncClient, proto_template_seed, db_pool):
    """Передача пустого списка удаляет все существующие инжекторы"""
    tmp_id = proto_template_seed["tmp_id"]
    
    # Создаём начальные инжекторы с валидным extractor_script
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO templates_users_extractors (tmp_id, flatten_array_cursor, extractor_script) VALUES ($1, $2, $3)",
            tmp_id, "cursor_to_delete", "def transform(user_obj):\n    return user_obj['to_delete']"
        )
    
    # Передаём пустой список
    response = await client.put(
        f"/api/v1/private/templates/{tmp_id}/user_injectors",
        json={"user_injectors": []}
    )
    
    assert response.status_code == 200
    
    # Проверяем что все инжекторы удалены
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM templates_users_extractors WHERE tmp_id = $1",
            tmp_id
        )
        assert count == 0


@pytest.mark.asyncio
async def test_update_user_injectors_nonexistent_template(client: AsyncClient, db_seed):
    """Обновление инжекторов несуществующего шаблона возвращает 404"""
    response = await client.put(
        "/api/v1/private/templates/9999/user_injectors",
        json={"user_injectors": []}
    )
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["message"] == "Шаблон с таким tmp_id не существует"
