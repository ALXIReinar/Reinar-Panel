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
            nodes_protocols, 
            nodes, 
            protocols, 
            proto_templates 
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


@pytest.fixture(scope="function")
def seed_info(db_seed):
    return db_seed[1]


@pytest.fixture(scope="function")
def pg_pool(db_seed):
    return db_seed[0]



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