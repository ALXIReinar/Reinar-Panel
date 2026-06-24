import os

"ВАЖНО: Устанавливаем переменную окружения ДО любых импортов"
os.environ['ENV_LOCAL_TEST_FILE'] = 'web/.env.api.test'

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from web.config_dir import config as cfg

env = cfg.env
pool_settings = cfg.pool_settings

from web.api import main_router
from web.data.postgres import PgSql, get_custom_pgsql
from web.schemas.cookie_settings_schema import JWTCookieDep


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database():
    os.environ['PYTHONUTF8'] = '1'
    assert isinstance(env.pg_db, str), "env.pg_db is not set"
    assert env.pg_db.startswith("test_"), f"Refusing to run tests against non-test database: {env.pg_db}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)



async def _truncate_and_seed(conn: asyncpg.Connection):
    """
    Очищает и заполняет БД базовыми тестовыми данными для ReinarPanel.
    """
    # Очищаем таблицы для тестов админов, протоколов и нод
    # CASCADE автоматически очистит зависимые таблицы
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
            whitelist_commands,
            vnodes_sub_plans,
            sub_plans,
            remote_execute_history,
            payed_subs,
            sub_nodes_outbox
        RESTART IDENTITY CASCADE
    """)

    # Создаём базового тестового админа
    from web.config_dir.config import encryption
    
    test_admin_login = "test_admin"
    test_admin_pass = "TestPass123!"  # Соответствует валидации пароля
    
    admin_id = await conn.fetchval(
        "INSERT INTO admins (login, passw) VALUES ($1, $2) RETURNING id",
        test_admin_login,
        encryption.hash(test_admin_pass)
    )
    
    return {
        "admin_id": admin_id,
        "admin_login": test_admin_login,
        "admin_pass": test_admin_pass,
    }


@pytest.fixture(scope="function")
async def db_pool():
    """
    Создаёт пул соединений для каждого теста.
    """
    pool = await asyncpg.create_pool(**pool_settings)
    yield pool
    await pool.close()


@pytest.fixture(scope="function")
async def db_seed(db_pool):
    """
    Очищает и заполняет БД базовыми тестовыми данными для каждого теста.
    """
    async with db_pool.acquire() as conn:
        seed_info = await _truncate_and_seed(conn)

    yield db_pool, seed_info


@pytest.fixture(scope="function")
async def client(db_seed):
    pg_pool, seed_info = db_seed
    app = FastAPI()
    app.include_router(main_router)
    app.state.pg_pool = pg_pool
    app.state.seed_info = seed_info
    
    # Инициализация Redis для тестов
    from redis.asyncio import Redis
    from web.config_dir.config import redis_settings
    redis = Redis(**redis_settings)
    app.state.redis = redis

    # Инициализация фейковой aiohttp.ClientSession
    app.state.cmd_center_aiohttp = FakeAiohttpSession()

    @app.middleware("http")
    async def add_state(request, call_next):
        request.state.client_ip = "127.0.0.1"
        # Берём admin_id из app.state если установлен в тесте, иначе дефолтный
        request.state.admin_id = getattr(app.state, 'test_admin_id', 1)
        request.state.session_id = getattr(app.state, 'test_session_id', "test-session")
        return await call_next(request)

    async def override_pgsql():
        async with pg_pool.acquire() as conn:
            yield PgSql(conn)

    app.dependency_overrides[get_custom_pgsql] = override_pgsql
    app.dependency_overrides[JWTCookieDep] = lambda: None

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # Сохраняем ссылку на app в клиенте
        ac.app = app
        yield ac
    
    # Закрываем Redis после тестов
    await redis.aclose()

# Фейк классы для моков aiohttp ответов
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



@pytest.fixture
async def virtual_node_seed(pg_pool, physical_node_seed, proto_template_seed):
    """
    Создаёт тестовые виртуальные ноды (nodes_protocols) в БД.
    Возвращает словарь с vnode_id для использования в тестах.
    Зависит от physical_node_seed и proto_template_seed.
    """
    async with pg_pool.acquire() as conn:
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
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, proto_port, config_path)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            physical_node_seed["node_id_1"],
            proto_id,
            "VNode1 With Ports",  # Укорочено до 30 символов
            "vnode1.example.com",
            9090,  # metrics_port
            8443,  # proto_port
            "/etc/test-proto/config1.json"
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


@pytest.fixture(autouse=True)
async def flush_redis():
    """
    Fixture to flush Redis before each test.

    This ensures test isolation by clearing all Redis data before each test runs.
    Used by rate limiter and other Redis-dependent features.
    """
    from redis.asyncio import Redis
    from web.config_dir.config import redis_settings

    redis = Redis(**redis_settings)
    await redis.flushdb()
    try:
        yield redis
    finally:
        await redis.close()


@pytest.fixture(scope="function")
def seed_info(db_seed):
    return db_seed[1]


@pytest.fixture(scope="function")
def pg_pool(db_seed):
    return db_seed[0]



@pytest.fixture
async def proto_template_seed(pg_pool, db_seed):
    """
    Создаёт тестовый шаблон протокола в БД.
    Возвращает tmp_id для использования в тестах.
    Зависит от db_seed для очистки БД перед каждым тестом.
    """
    async with pg_pool.acquire() as conn:
        # Создаём первый тестовый шаблон протокола
        tmp_id = await conn.fetchval(
            """
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted, 
                reload_core_command, sub_prepare_script
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "TestProtocol Template",
            "https://example.com/proto_template",
            1,
            True,
            "systemctl reload test-proto",
            "#!/bin/bash\necho 'test'"
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
async def sub_plan_seed(pg_pool, db_seed):
    """
    Создаёт тестовые планы подписок в БД.
    Возвращает словарь с plan_id для использования в тестах.
    Зависит от db_seed для очистки БД перед каждым тестом.
    """
    async with pg_pool.acquire() as conn:
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
async def physical_node_seed(pg_pool, db_seed):
    """
    Создаёт тестовые физические ноды в БД.
    Возвращает словарь с node_id для использования в тестах.
    Зависит от db_seed для очистки БД перед каждым тестом.
    """
    async with pg_pool.acquire() as conn:
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
