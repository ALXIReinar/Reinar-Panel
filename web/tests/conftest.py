import os

from starlette.requests import Request

"ВАЖНО: Устанавливаем переменную окружения ДО любых импортов из web/"
os.environ['ENV_LOCAL_TEST_FILE'] = 'web/.env.api.test'

from web.data.postgres import get_pg_pool
import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from web.config_dir.config import encryption
from redis.asyncio import Redis
from web.config_dir.config import redis_settings
from web.config_dir import config as cfg

env = cfg.env
pool_settings = cfg.pool_settings

from web.api import main_router
from web.schemas.cookie_settings_schema import JWTCookieDep


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database():
    """Проверяет что используется тестовая БД"""
    os.environ['PYTHONUTF8'] = '1'
    assert isinstance(env.pg_db, str), "env.pg_db is not set"
    assert env.pg_db.startswith("test_"), f"Refusing to run tests against non-test database: {env.pg_db}"


# ========== Function Scope Fixtures ==========

@pytest.fixture(scope="function")
async def db_pool():
    """
    Пул соединений для каждого теста (function scope).
    
    Function scope нужен для правильного event loop (asyncio_default_fixture_loop_scope = function).
    """
    pool = await asyncpg.create_pool(**pool_settings)
    yield pool
    await pool.close()


@pytest.fixture(scope="function", autouse=True)
async def db_seed(db_pool):
    """
    Очищает БД и заполняет начальными данными перед КАЖДЫМ тестом.
    
    autouse=True означает что выполняется автоматически для каждого теста.
    
    Выполняет:
    1. TRUNCATE всех таблиц
    2. Заполняет справочники (templates_statuses, online_statuses, pay_statuses)
    3. Создаёт тестового админа
    4. Создаёт софт-удалённых пользователей для проверки фильтрации
    
    Возвращает:
        dict: {"admin_id", "admin_login", "admin_pass", "deleted_user_ids"}
    """
    test_admin_login = "test_admin"
    test_admin_pass = "TestPass123!"  # Соответствует валидации пароля
    
    async with db_pool.acquire() as conn:
        # 1. Очищаем все таблицы (включая справочники, они будут пересозданы)
        await conn.execute("""
            TRUNCATE TABLE 
                sessions_admins, 
                admins, 
                nodes_protocoles_spec_params_values,
                template_spec_params,
                nodes_protocols, 
                nodes, 
                protocols, 
                proto_templates,
                protocols_commands,
                whitelist_commands,
                vnodes_sub_plans,
                sub_plans,
                remote_execute_history,
                payed_subs,
                sub_nodes_outbox,
                sub_nodes_operations,
                users,
                templates_statuses,
                online_statuses,
                pay_statuses,
                node_statuses
            RESTART IDENTITY CASCADE
        """)
        
        # 2. Заполняем справочники констант
        await conn.execute("""
            INSERT INTO templates_statuses (id, name) 
            OVERRIDING SYSTEM VALUE 
            VALUES (1, 'Системный'), (2, 'Пользовательский')
        """)

        await conn.execute("""
            INSERT INTO online_statuses (id, title) 
            OVERRIDING SYSTEM VALUE 
            VALUES (1, 'Не подключался'), (2, 'Оффлайн'), (3, 'Онлайн')
        """)

        await conn.execute("""
            INSERT INTO pay_statuses (id, name) 
            OVERRIDING SYSTEM VALUE 
            VALUES (1, 'pending'), (2, 'success'), (3, 'expired')
        """)

        # 3. Создаём тестового админа
        admin_id = await conn.fetchval(
            "INSERT INTO admins (login, passw) VALUES ($1, $2) RETURNING id",
            test_admin_login,
            encryption.hash(test_admin_pass)
        )

        # 4. Создаём софт-удалённых пользователей (константы для проверки фильтрации)
        # Гарантирует что все SQL запросы корректно игнорируют is_deleted = true
        deleted_user_1_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, true)
            RETURNING id
        """, 9999001, "deleted_user_1", "uuid-deleted-0001-0001-000000000001", "deleted_b64_token_1")

        deleted_user_2_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, true)
            RETURNING id
        """, 9999002, "deleted_user_2", "uuid-deleted-0002-0002-000000000002", "deleted_b64_token_2")
    
    return {
        "admin_id": admin_id,
        "admin_login": test_admin_login,
        "admin_pass": test_admin_pass,
        "deleted_user_ids": [deleted_user_1_id, deleted_user_2_id],
    }


# ========== FastAPI Client и App ==========

@pytest.fixture(scope="session")
def test_app():
    """
    FastAPI приложение (создаётся один раз на сессию).
    
    Middleware добавляет test_admin_id и test_session_id в request.state.
    """
    app = FastAPI()

    @app.middleware("http")
    async def add_state(request: Request, call_next):
        request.state.client_ip = "127.0.0.1"
        
        # Проверяем есть ли access_token в cookies
        # Если есть - извлекаем admin_id и session_id из него
        access_token_cookie = request.cookies.get('access_token')
        if access_token_cookie:
            try:
                import jwt
                decoded = jwt.decode(access_token_cookie, options={"verify_signature": False})
                request.state.admin_id = int(decoded.get('sub', 0))
                request.state.session_id = decoded.get('s_id', 'unknown')
            except Exception:
                # Если токен невалидный - используем fallback
                request.state.admin_id = getattr(request.app.state, 'default_admin_id', None)
                request.state.session_id = getattr(request.app.state, 'default_session_id', None)
        else:
            # Нет токена - используем fallback значения для простых тестов
            request.state.admin_id = getattr(
                request.state, 'test_admin_id',
                getattr(request.app.state, 'default_admin_id', None)
            )
            request.state.session_id = getattr(
                request.state, 'test_session_id',
                getattr(request.app.state, 'default_session_id', None)
            )
        return await call_next(request)

    app.include_router(main_router)
    return app


@pytest.fixture(scope="function")
async def client(test_app, db_pool, db_seed):
    """
    HTTP клиент для тестирования API (создаётся для каждого теста).
    
    Setup:
    1. Устанавливает db_pool в app.state.pg_pool
    2. Создаёт Redis соединение
    3. Настраивает моки (aiohttp, JWT)
    4. Создаёт httpx.AsyncClient
    
    Teardown:
    1. Закрывает AsyncClient (автоматически через context manager)
    2. Закрывает Redis
    3. Очищает state и overrides
    """
    # Setup: создаём Redis
    redis = Redis(**redis_settings)
    
    try:
        # Настраиваем app.state
        test_app.state.pg_pool = db_pool
        test_app.state.redis = redis
        test_app.state.default_admin_id = db_seed["admin_id"]
        test_app.state.default_session_id = 'test-session'
        test_app.state.seed_info = db_seed
        test_app.state.cmd_center_aiohttp = FakeAiohttpSession()
        
        # Настраиваем dependency overrides
        test_app.dependency_overrides.clear()
        test_app.dependency_overrides[JWTCookieDep] = lambda: None
        
        # Создаём HTTP клиент
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            ac.app = test_app
            yield ac
            
    finally:
        # Teardown: очищаем ресурсы
        await redis.aclose()
        test_app.dependency_overrides.clear()
        
        # Очищаем state (чтобы избежать утечек между тестами)
        for attr in ['pg_pool', 'redis', 'seed_info', 'cmd_center_aiohttp']:
            if hasattr(test_app.state, attr):
                delattr(test_app.state, attr)

# ========== Utility Fixtures ==========

@pytest.fixture(autouse=True)
async def flush_redis():
    """
    Fixture to flush Redis before each test.

    This ensures test isolation by clearing all Redis data before each test runs.
    Used by rate limiter and other Redis-dependent features.
    """
    redis = Redis(**redis_settings)
    await redis.flushdb()
    try:
        yield redis
    finally:
        await redis.close()


@pytest.fixture
def mock_arq(client):
    """
    Мокируем ARQ очередь для тестирования фоновых задач.
    Используется в тестах, где нужно проверить что задача отправлена в ARQ,
    но не нужно реально её выполнять.
    
    Returns:
        AsyncMock с методом enqueue_job, который возвращает job с id "test-job-12345"
    """
    from unittest.mock import AsyncMock, MagicMock
    
    mock_arq_pool = AsyncMock()
    mock_job = MagicMock()
    mock_job.job_id = "test-job-12345"
    mock_arq_pool.enqueue_job = AsyncMock(return_value=mock_job)
    
    # Заменяем ARQ в app state (используется arq_pool, а не arq)
    client.app.state.arq_pool = mock_arq_pool
    return mock_arq_pool


# ========== Seed Fixtures (создают уникальные данные для каждого теста) ==========

@pytest.fixture
async def physical_node_seed(db_pool, db_seed):
    """
    Создаёт тестовые физические ноды для теста.
    
    Возвращает:
        dict: {"node_id_1": int, "node_id_2": int, "node_id_3": int}
    """
    async with db_pool.acquire() as conn:
        # Создаём первую тестовую физическую ноду (активная)
        node_id_1 = await conn.fetchval(
            """
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "192.168.1.100",
            "10.0.0.100",
            8100,
            "test-node-1",
            "Test Physical Node 1",
            True
        )
        
        # Создаём вторую ноду (неактивная)
        node_id_2 = await conn.fetchval(
            """
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "192.168.1.101",
            "10.0.0.101",
            8101,
            "test-node-2",
            "Test Physical Node 2",
            False
        )
        
        # Создаём третью ноду (активная) - для усиления тестов фильтрации
        node_id_3 = await conn.fetchval(
            """
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "192.168.1.102",
            "10.0.0.102",
            8102,
            "test-node-3",
            "Test Physical Node 3",
            True
        )
        
        return {
            "node_id_1": node_id_1,
            "node_id_2": node_id_2,
            "node_id_3": node_id_3
        }


@pytest.fixture
async def proto_template_seed(db_pool, db_seed):
    """
    Создаёт тестовые шаблоны протоколов для теста.
    
    Возвращает:
        dict: {"tmp_id": int, "tmp_id_2": int}
    """
    async with db_pool.acquire() as conn:
        # Создаём первый тестовый шаблон протокола
        tmp_id = await conn.fetchval(
            """
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted, 
                reload_core_command, sub_prepare_script,
                proto_python_lib, api_add_user_script, api_delete_user_script,
                flatten_json_users_key, flatten_user_identifier_key,
                add_script_custom_params, delete_script_custom_params
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id
            """,
            "TestProtocol Template",
            "https://example.com/proto_template",
            1,
            True,
            "systemctl reload test-proto",
            "#!/bin/bash\necho 'test'",
            "vless",  # proto_python_lib
            "python /opt/add_user.py",  # api_add_user_script
            "python /opt/delete_user.py",  # api_delete_user_script
            "inbounds.0.settings.clients",  # flatten_json_users_key
            "email",  # flatten_user_identifier_key
            '{}',  # add_script_custom_params (пустой JSON)
            '{}'   # delete_script_custom_params (пустой JSON)
        )
        
        # Создаём второй шаблон для разнообразия
        tmp_id_2 = await conn.fetchval(
            """
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted,
                reload_core_command, sub_prepare_script
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "AnotherTemplate",
            "https://example.com/another_template",
            1,
            True,
            "systemctl reload another",
            "#!/bin/bash\necho 'another'"
        )
        
        return {"tmp_id": tmp_id, "tmp_id_2": tmp_id_2}


@pytest.fixture
async def sub_plan_seed(db_pool, db_seed):
    """
    Создаёт тестовые планы подписок для теста.
    
    Возвращает:
        dict: {"plan_id_1": int, "plan_id_2": int}
    """
    async with db_pool.acquire() as conn:
        # Создаём первый план подписки (активный)
        plan_id_1 = await conn.fetchval(
            """
            INSERT INTO sub_plans (title, description, ttl_days, cost, traffic_limit_day, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "Basic Plan",
            "Basic subscription plan for testing",
            30,  # 30 дней
            500,  # 5.00 руб (в копейках)
            10240,  # 10 GB в МБ
            True
        )
        
        # Создаём второй план (неактивный, безлимитный трафик)
        plan_id_2 = await conn.fetchval(
            """
            INSERT INTO sub_plans (title, description, ttl_days, cost, traffic_limit_day, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "Premium Plan",
            "Premium unlimited plan",
            90,  # 90 дней
            2000,  # 20.00 руб
            -1,  # Безлимит
            False
        )
        
        return {
            "plan_id_1": plan_id_1,
            "plan_id_2": plan_id_2
        }


@pytest.fixture
async def virtual_node_seed(db_pool, physical_node_seed, proto_template_seed):
    """
    Создаёт тестовые виртуальные ноды (nodes_protocols) в БД.
    Возвращает словарь с vnode_id для использования в тестах.
    Зависит от physical_node_seed и proto_template_seed.
    """
    async with db_pool.acquire() as conn:
        # Создаём протокол для тестирования виртуальных нод
        proto_id = await conn.fetchval(
            """
            INSERT INTO protocols (tmp_id, name)
            VALUES ($1, $2)
            RETURNING id
            """,
            proto_template_seed["tmp_id"],
            "Test Protocol for VNodes"
        )
        
        # Создаём виртуальную ноду 1: с портами (для тестов конфликтов)
        vnode_id_1 = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, proto_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            physical_node_seed["node_id_1"],
            proto_id,
            "VNode1 With Ports",  # Укорочено до 30 символов
            "vnode1.example.com",
            9090,  # metrics_port
            8443,  # proto_port
            "/etc/test-proto/config1.json",
            True  # user_visible = True (ВАЖНО для тестов)
        )
        
        # Создаём виртуальную ноду 2: без портов (для тестов установки портов)
        vnode_id_2 = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            physical_node_seed["node_id_1"],
            proto_id,
            "VNode2 No Ports",  # Укорочено
            "vnode2.example.com"
        )
        
        # Создаём виртуальную ноду 3: на другой физической ноде (для проверки изоляции портов)
        vnode_id_3 = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, proto_port)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            physical_node_seed["node_id_2"],
            proto_id,
            "VNode3 Other Node",  # Укорочено
            "vnode3.example.com",
            9090,  # Тот же порт что и vnode1, но на другой физ. ноде - это ОК
            8443   # Тот же порт что и vnode1, но на другой физ. ноде - это ОК
        )
        
        return {
            "proto_id": proto_id,
            "vnode_id_1": vnode_id_1,
            "vnode_id_2": vnode_id_2,
            "vnode_id_3": vnode_id_3,
            "node_id_1": physical_node_seed["node_id_1"],
            "node_id_2": physical_node_seed["node_id_2"],
        }
class FakeAiohttpResponse:
    def __init__(self, json_data: dict, status: int = 200):
        self._json_data = json_data
        self.status = status

    async def json(self):
        return self._json_data
    
    def raise_for_status(self):
        """Имитация raise_for_status из aiohttp"""
        if self.status >= 400:
            from aiohttp import ClientResponseError
            raise ClientResponseError(
                request_info=None,
                history=None,
                status=self.status,
                message=f"HTTP {self.status}"
            )
        return self._json_data

class FakeAiohttpGetContext:
    def __init__(self, json_data: dict, status: int = 200):
        self.json_data = json_data
        self.status = status

    async def __aenter__(self):
        return FakeAiohttpResponse(self.json_data, self.status)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class FakeAiohttpSession:
    def __init__(self, json_data: dict | None = None, status: int = 200, raise_error: bool = False):
        self.json_data = {} if json_data is None else json_data
        self.status = status
        self.raise_error = raise_error

    def get(self, url: str, *args, **kwargs):
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        return FakeAiohttpGetContext(self.json_data, self.status)

    # Добавляем POST по аналогии
    def post(self, url: str, *args, **kwargs):
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        return FakeAiohttpGetContext(self.json_data, self.status)


