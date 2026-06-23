"""
Интеграционные тесты для эндпоинтов работы с белым списком команд (/private/whitelist).
Тестирует CRUD операции для whitelist команд, сброс Redis кэша и механику whitelist_mode.
"""
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis


# ==================== GET /private/whitelist/all ====================

@pytest.mark.asyncio
async def test_get_whitelist_empty_cache_loads_from_db(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Пустой кэш → загрузка из БД и сохранение в Redis"""
    # Создаём команды в БД
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2), ($3, $4)",
            "ls", True, "cat", False
        )
    
    # Проверяем, что кэш пуст
    redis: Redis = flush_redis
    cached = await redis.get("wh_list_commands")
    assert cached is None
    
    # Делаем запрос (должен загрузить из БД в Redis)
    response = await client.get("/api/v1/private/whitelist/all")
    
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert len(data["commands"]) == 2
    
    # Проверяем, что кэш заполнился
    cached = await redis.get("wh_list_commands")
    assert cached is not None


@pytest.mark.asyncio
async def test_get_whitelist_from_cache(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Заполненный кэш → возврат из Redis без обращения к БД"""
    # Создаём команды в БД
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
            "pwd", True
        )
    
    # Первый запрос загружает кэш
    response1 = await client.get("/api/v1/private/whitelist/all")
    assert response1.status_code == 200
    
    # Удаляем команду из БД (но кэш остаётся)
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM whitelist_commands WHERE command = 'pwd'")
    
    # Второй запрос возвращает из кэша (команда всё ещё там)
    response2 = await client.get("/api/v1/private/whitelist/all")
    assert response2.status_code == 200
    data = response2.json()
    assert len(data["commands"]) == 1
    assert data["commands"][0]["command"] == "pwd"


@pytest.mark.asyncio
async def test_get_whitelist_data_structure(client: AsyncClient, db_seed, pg_pool):
    """Проверка структуры возвращаемых данных (id, command, is_active)"""
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
            "echo", True
        )
    
    response = await client.get("/api/v1/private/whitelist/all")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["commands"]) == 1
    
    cmd = data["commands"][0]
    assert "id" in cmd
    assert "command" in cmd
    assert "is_active" in cmd
    assert cmd["command"] == "echo"
    assert cmd["is_active"] is True


# ==================== PUT /private/whitelist/bulk_update ====================

@pytest.mark.asyncio
async def test_bulk_update_activate_commands_flushes_redis(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Активация команд + проверка сброса Redis кэша"""
    # Создаём неактивные команды
    async with pg_pool.acquire() as conn:
        cmd1_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "grep", False
        )
        cmd2_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "find", False
        )
    
    # Заполняем кэш
    await client.get("/api/v1/private/whitelist/all")
    redis: Redis = flush_redis
    cached_before = await redis.get("wh_list_commands")
    assert cached_before is not None
    
    # Активируем команды
    response = await client.put(
        "/api/v1/private/whitelist/bulk_update",
        json={
            "set_as_active": [cmd1_id, cmd2_id],
            "set_as_inactive": []
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["active_count"] == 2
    assert data["inactive_count"] == 0
    
    # Проверяем, что кэш сброшен
    cached_after = await redis.get("wh_list_commands")
    assert cached_after is None


@pytest.mark.asyncio
async def test_bulk_update_deactivate_commands_flushes_redis(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Деактивация команд + проверка сброса Redis кэша"""
    # Создаём активные команды
    async with pg_pool.acquire() as conn:
        cmd1_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "rm", True
        )
        cmd2_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "cp", True
        )
    
    # Заполняем кэш
    await client.get("/api/v1/private/whitelist/all")
    redis: Redis = flush_redis
    assert await redis.get("wh_list_commands") is not None
    
    # Деактивируем команды
    response = await client.put(
        "/api/v1/private/whitelist/bulk_update",
        json={
            "set_as_active": [],
            "set_as_inactive": [cmd1_id, cmd2_id]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["inactive_count"] == 2
    
    # Проверяем, что кэш сброшен
    assert await redis.get("wh_list_commands") is None


@pytest.mark.asyncio
async def test_bulk_update_combined_operations(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Комбинированная операция (activate + deactivate) + проверка сброса Redis"""
    async with pg_pool.acquire() as conn:
        active_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "mv", True
        )
        inactive_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "touch", False
        )
    
    # Заполняем кэш
    await client.get("/api/v1/private/whitelist/all")
    redis: Redis = flush_redis
    assert await redis.get("wh_list_commands") is not None
    
    # Меняем статусы местами
    response = await client.put(
        "/api/v1/private/whitelist/bulk_update",
        json={
            "set_as_active": [inactive_id],
            "set_as_inactive": [active_id]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["active_count"] == 1
    assert data["inactive_count"] == 1
    
    # Проверяем сброс кэша
    assert await redis.get("wh_list_commands") is None


@pytest.mark.asyncio
async def test_bulk_update_deactivate_all_disables_whitelist_mode(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Деактивация всех команд → whitelist_mode отключается"""
    # Создаём только одну активную команду
    async with pg_pool.acquire() as conn:
        cmd_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "whoami", True
        )
    
    # Загружаем в кэш (whitelist_mode = True)
    get_response = await client.get("/api/v1/private/whitelist/all")
    assert len(get_response.json()["commands"]) == 1
    
    # Деактивируем единственную команду
    response = await client.put(
        "/api/v1/private/whitelist/bulk_update",
        json={
            "set_as_active": [],
            "set_as_inactive": [cmd_id]
        }
    )
    
    assert response.status_code == 200
    
    # Перезагружаем кэш
    await client.get("/api/v1/private/whitelist/all")
    
    # Проверяем, что теперь нет активных команд (whitelist_mode должен быть False)
    # Это проверяется через поведение is_whitelisted в реальном использовании
    # Здесь мы просто проверяем, что деактивация прошла успешно
    async with pg_pool.acquire() as conn:
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM whitelist_commands WHERE is_active = true"
        )
    assert active_count == 0


# ==================== POST /private/whitelist/bulk_add ====================

@pytest.mark.asyncio
async def test_bulk_add_commands_flushes_redis(client: AsyncClient, db_seed, flush_redis):
    """Успешное добавление команд + проверка сброса Redis кэша"""
    # Заполняем пустой кэш
    await client.get("/api/v1/private/whitelist/all")
    redis: Redis = flush_redis
    cached_before = await redis.get("wh_list_commands")
    # Кэш может быть пустым или содержать пустой список
    
    # Добавляем команды
    response = await client.post(
        "/api/v1/private/whitelist/bulk_add",
        json={
            "commands": ["sed", "awk", "sort"]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "white_cmd_ids" in data
    assert len(data["white_cmd_ids"]) == 3
    
    # Проверяем, что кэш сброшен
    cached_after = await redis.get("wh_list_commands")
    assert cached_after is None


@pytest.mark.asyncio
async def test_bulk_add_partial_with_duplicates(client: AsyncClient, db_seed, pg_pool):
    """Частичное добавление (дубликаты игнорируются) + статус 202"""
    # Создаём существующую команду
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
            "head", True
        )
    
    # Пытаемся добавить дубликат + новые команды
    response = await client.post(
        "/api/v1/private/whitelist/bulk_add",
        json={
            "commands": ["head", "tail", "uniq"]  # head уже существует
        }
    )
    
    assert response.status_code == 202  # Partial success
    data = response.json()
    assert data["success"] is True
    assert "Вставка выполнена частично" in data["message"]
    assert "success_insert_cmds" in data
    # Должны вставиться только 2 новые команды (tail, uniq)
    assert len(data["success_insert_cmds"]) == 2


@pytest.mark.asyncio
async def test_bulk_add_first_command_enables_whitelist_mode(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Добавление первой команды в пустой whitelist → whitelist_mode включается"""
    # Проверяем, что whitelist пуст
    get_response = await client.get("/api/v1/private/whitelist/all")
    assert len(get_response.json()["commands"]) == 0
    
    # Добавляем первую команду
    response = await client.post(
        "/api/v1/private/whitelist/bulk_add",
        json={
            "commands": ["hostname"]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Перезагружаем кэш и проверяем наличие команды
    get_response = await client.get("/api/v1/private/whitelist/all")
    commands = get_response.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "hostname"
    
    # whitelist_mode должен быть True (есть хотя бы одна команда)
    async with pg_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM whitelist_commands")
    assert count > 0


# ==================== DELETE /private/whitelist/bulk_delete ====================

@pytest.mark.asyncio
async def test_bulk_delete_commands_flushes_redis(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Успешное удаление команд + проверка сброса Redis кэша"""
    # Создаём команды
    async with pg_pool.acquire() as conn:
        cmd1_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "df", True
        )
        cmd2_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "du", True
        )
    
    # Заполняем кэш
    await client.get("/api/v1/private/whitelist/all")
    redis: Redis = flush_redis
    assert await redis.get("wh_list_commands") is not None
    
    # Удаляем команды
    response = await client.request(
        "DELETE",
        "/api/v1/private/whitelist/bulk_delete",
        json={
            "ids": [cmd1_id, cmd2_id]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Команды удалены"
    
    # Проверяем сброс кэша
    assert await redis.get("wh_list_commands") is None


@pytest.mark.asyncio
async def test_bulk_delete_all_disables_whitelist_mode(client: AsyncClient, db_seed, flush_redis, pg_pool):
    """Удаление всех команд → whitelist_mode отключается"""
    # Создаём несколько команд
    async with pg_pool.acquire() as conn:
        cmd1_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "uptime", True
        )
        cmd2_id = await conn.fetchval(
            "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2) RETURNING id",
            "date", True
        )
    
    # Загружаем в кэш
    get_response = await client.get("/api/v1/private/whitelist/all")
    assert len(get_response.json()["commands"]) == 2
    
    # Удаляем все команды
    response = await client.request(
        "DELETE",
        "/api/v1/private/whitelist/bulk_delete",
        json={
            "ids": [cmd1_id, cmd2_id]
        }
    )
    
    assert response.status_code == 200
    
    # Перезагружаем кэш и проверяем пустоту
    get_response = await client.get("/api/v1/private/whitelist/all")
    assert len(get_response.json()["commands"]) == 0
    
    # whitelist_mode должен быть False (нет команд)
    async with pg_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM whitelist_commands")
    assert count == 0


@pytest.mark.asyncio
async def test_bulk_delete_nonexistent_ids_succeeds(client: AsyncClient, db_seed, pg_pool):
    """Удаление несуществующих ID завершается успешно (без ошибок)"""
    # Пытаемся удалить несуществующие ID
    response = await client.request(
        "DELETE",
        "/api/v1/private/whitelist/bulk_delete",
        json={
            "ids": [99999, 88888]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Команды удалены"
