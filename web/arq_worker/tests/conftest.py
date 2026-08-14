import os

from yarl import URL

"ВАЖНО: Устанавливаем переменную окружения ДО любых импортов из web/"
os.environ['ENV_FILE'] = os.getenv('ENV_FILE') if os.getenv('ENV_FILE') else 'web/arq_worker/.env.arq.test'

import asyncpg
import pytest
from arq import create_pool as create_arq_pool
from aiohttp import ClientResponseError, ClientError, RequestInfo
from unittest.mock import AsyncMock, MagicMock
from redis.asyncio import Redis

from web.arq_worker import config as cfg

env = cfg.env
pool_settings = cfg.pool_settings


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
    """
    pool = await asyncpg.create_pool(**pool_settings)
    yield pool
    await pool.close()


@pytest.fixture(scope="function")
async def db_seed(db_pool):
    """
    Очищает БД и заполняет начальными данными перед КАЖДЫМ тестом.
    
    Используется только для integration/e2e тестов.
    Unit-тесты должны отключать эту фикстуру через pytestmark.
    """
    async with db_pool.acquire() as conn:
        # 1. Очищаем ТОЛЬКО пользовательские данные (НЕ ТРОГАЕМ СПРАВОЧНИКИ И ШАБЛОНЫ!)
        await conn.execute("""
            TRUNCATE TABLE 
                sessions_admins, 
                admins, 
                nodes_protocoles_spec_params_values,
                nodes_protocols, 
                nodes, 
                remote_execute_history,
                user_subs,
                pay_orders,
                sub_nodes_outbox,
                users,
                vnodes_sub_plans,
                sub_plan_offers,
                sub_plans
            RESTART IDENTITY CASCADE
        """)
        
        # 2. Справочники уже должны быть залиты через seed_data.py
        # Проверяем наличие
        templates_count = await conn.fetchval("SELECT COUNT(*) FROM proto_templates")
        if templates_count == 0:
            raise RuntimeError(
                "proto_templates пуста! Запустите: python -m web.db.seed_data"
            )
    
    return {"db_cleaned": True}


# ========== ARQ Fixtures ==========

@pytest.fixture(scope="function")
async def arq_pool():
    """Реальный ARQ pool для тестирования очереди"""
    from web.arq_worker.config import get_arq_redis_settings, get_arq_worker_settings
    
    pool = await create_arq_pool(get_arq_redis_settings(), **get_arq_worker_settings())
    yield pool
    
    # Очищаем очередь после теста
    await pool.aclose()


@pytest.fixture(scope="function")
async def arq_ctx(db_pool, arq_pool):
    """
    ARQ контекст для декораторов (@pg_sql_dep, @arq_dep, @aiohttp_dep).
    
    Использует реальный ARQ pool и БД pool, но fake aiohttp.
    """
    aio_http = FakeAiohttpSession()
    
    yield {
        'pg_pool': db_pool,
        'arq_redis': arq_pool,
        'aio_http': aio_http,
    }


@pytest.fixture
def mock_arq_ctx(db_pool):
    """
    Mock ARQ контекст (для unit-тестов без реального ARQ).
    
    Использует AsyncMock для arq_redis и fake aiohttp.
    """
    mock_arq = AsyncMock()
    mock_job = MagicMock()
    mock_job.job_id = "test-job-12345"
    mock_arq.enqueue_job = AsyncMock(return_value=mock_job)
    
    return {
        'pg_pool': db_pool,
        'arq_redis': mock_arq,
        'aio_http': FakeAiohttpSession(),
    }


# ========== AioHttp Fake Fixtures ==========

class FakeAiohttpResponse:
    """Имитация aiohttp.ClientResponse"""
    def __init__(self, json_data: dict, status: int = 200):
        self._json_data = json_data
        self.status = status

    async def json(self):
        return self._json_data
    
    def release(self):
        """Имитация release из aiohttp (освобождение соединения)"""
        pass
    
    def raise_for_status(self):
        """Имитация raise_for_status из aiohttp"""
        if self.status >= 400:

            # Создаём минимальный request_info для ClientResponseError
            request_info = RequestInfo(
                url=URL("http://fake-node:8000/api"),
                method="POST",
                headers={},
                real_url=URL("http://fake-node:8000/api")
            )
            
            raise ClientResponseError(
                request_info=request_info,
                history=(),
                status=self.status,
                message=f"HTTP {self.status}",
                headers={}
            )


class FakeAiohttpContext:
    """Контекстный менеджер для async with"""
    def __init__(self, json_data: dict, status: int = 200):
        self.json_data = json_data
        self.status = status

    async def __aenter__(self):
        return FakeAiohttpResponse(self.json_data, self.status)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class FakeAiohttpSession:
    """
    Fake aiohttp.ClientSession для тестирования HTTP-запросов.
    
    Поддерживает:
    - Spy-функционал (отслеживание вызовов)
    - Настройка status и json_data
    - Имитация ошибок
    """
    def __init__(self, json_data: dict | None = None, status: int = 200, raise_error: bool = False):
        self.json_data = {} if json_data is None else json_data
        self.status = status
        self.raise_error = raise_error
        
        # Spy attributes
        self.post_calls = []
        self.put_calls = []
        self.delete_calls = []
        self.get_calls = []

    def post(self, url: str, *args, **kwargs):
        """POST request spy"""
        self.post_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def put(self, url: str, *args, **kwargs):
        """PUT request spy"""
        self.put_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def delete(self, url: str, *args, **kwargs):
        """DELETE request spy"""
        self.delete_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def get(self, url: str, *args, **kwargs):
        """GET request spy"""
        self.get_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)
    
    async def close(self):
        """Имитация close"""
        pass


@pytest.fixture
def mock_aiohttp_success():
    """Mock успешного HTTP ответа от ноды (200 OK)"""
    return FakeAiohttpSession(json_data={'success': True}, status=200)


@pytest.fixture
def mock_aiohttp_error():
    """Mock HTTP ошибки от ноды (500 Internal Server Error)"""
    return FakeAiohttpSession(json_data={'error': 'Internal error'}, status=500)


@pytest.fixture
def mock_aiohttp_validation_error():
    """Mock валидационной ошибки от ноды (422 Unprocessable Entity)"""
    return FakeAiohttpSession(json_data={'detail': 'Validation failed'}, status=422)


# ========== Seed Fixtures (данные для тестов) ==========

@pytest.fixture
async def physical_node_seed(db_pool):
    """Создаёт тестовые физические ноды"""
    async with db_pool.acquire() as conn:
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
            True
        )
        
        return {
            "node_id_1": node_id_1,
            "node_id_2": node_id_2,
        }


@pytest.fixture
async def proto_template_seed(db_pool):
    """
    Загружает первый активный шаблон протокола из БД
    
    Вместо создания нового шаблона, используем существующий из seed_data.
    """
    async with db_pool.acquire() as conn:
        tmp_id = await conn.fetchval(
            """
            SELECT id 
            FROM proto_templates 
            WHERE is_accepted = true 
            ORDER BY id 
            LIMIT 1
            """
        )
        
        if not tmp_id:
            raise RuntimeError(
                "Не найдено ни одного активного шаблона в proto_templates! "
                "Запустите: python -m web.db.seed_data"
            )
        
        return {"tmp_id": tmp_id}


@pytest.fixture
async def sub_plan_seed(db_pool):
    """Создаёт тестовые планы подписок с офферами"""
    async with db_pool.acquire() as conn:
        # Создаём план
        plan_id_1 = await conn.fetchval(
            """
            INSERT INTO sub_plans (title, description, is_active, position)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "Basic Plan",
            "Basic subscription plan for testing",
            True,
            1
        )
        
        # Создаём оффер для плана
        offer_id_1 = await conn.fetchval(
            """
            INSERT INTO sub_plan_offers (
                sub_plan_id, ttl_days, cost, 
                traffic_limit_day_mb, traffic_limit_mb,
                infinite_traffic, infinite_expire, is_active, position
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            plan_id_1,
            30,          # ttl_days
            500,         # cost
            10240,       # traffic_limit_day_mb
            None,        # traffic_limit_mb (общий лимит)
            False,       # infinite_traffic
            False,       # infinite_expire
            True,        # is_active
            1            # position
        )
        
        return {
            "plan_id_1": plan_id_1,
            "offer_id_1": offer_id_1,
        }


@pytest.fixture
async def user_seed(db_pool):
    """Создаёт тестовых пользователей"""
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
            """,
            123456,
            "test_user"
        )
        
        return {
            "user_id": user_id,
            "tg_username": "test_user"
        }


@pytest.fixture
async def virtual_node_seed(db_pool, physical_node_seed, proto_template_seed):
    """Создаёт тестовые виртуальные ноды (nodes_protocols)"""
    async with db_pool.acquire() as conn:
        # Используем существующий протокол из seed_data
        proto_id = await conn.fetchval(
            """
            SELECT id 
            FROM protocols 
            WHERE tmp_id = $1 
            ORDER BY id 
            LIMIT 1
            """,
            proto_template_seed["tmp_id"]
        )
        
        if not proto_id:
            raise RuntimeError(
                f"Не найдено протокола для tmp_id={proto_template_seed['tmp_id']} в protocols! "
                f"Запустите: python -m web.db.seed_data"
            )
        
        vnode_id_1 = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, proto_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            physical_node_seed["node_id_1"],
            proto_id,
            "VNode1",
            "vnode1.example.com",
            9090,
            8443,
            "/etc/test-proto/config1.json",
            True
        )
        
        return {
            "proto_id": proto_id,
            "vnode_id_1": vnode_id_1,
            "node_id_1": physical_node_seed["node_id_1"],
        }


@pytest.fixture
async def arq_test_seed(db_pool, db_seed):
    """
    Создаёт обогащённый набор данных для ARQ-тестов:
    - 4 пользователя с разными состояниями подписок
    - Виртуальные ноды (активные + неактивные/невидимые)
    - Outbox записи для тестирования bulk операций
    """
    async with db_pool.acquire() as conn:
        # 1. Создаём планы подписок (несколько разных для разных подписок)
        plan_id = await conn.fetchval("""
            INSERT INTO sub_plans (title, description, is_active, position)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, "ARQ Test Plan 1", "Plan for testing", True, 1)
        
        # Создаём оффер для плана 1
        offer_id = await conn.fetchval("""
            INSERT INTO sub_plan_offers (
                sub_plan_id, ttl_days, cost,
                traffic_limit_day_mb, traffic_limit_mb,
                infinite_traffic, infinite_expire, is_active, position
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, plan_id, 30, 500, 10240, None, False, False, True, 1)
        
        plan_id_2 = await conn.fetchval("""
            INSERT INTO sub_plans (title, description, is_active, position)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, "ARQ Test Plan 2", "Plan for testing", True, 2)
        
        # Создаём оффер для плана 2
        offer_id_2 = await conn.fetchval("""
            INSERT INTO sub_plan_offers (
                sub_plan_id, ttl_days, cost,
                traffic_limit_day_mb, traffic_limit_mb,
                infinite_traffic, infinite_expire, is_active, position
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, plan_id_2, 30, 500, 10240, None, False, False, True, 1)
        
        plan_id_3 = await conn.fetchval("""
            INSERT INTO sub_plans (title, description, is_active, position)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, "ARQ Test Plan 3", "Plan for testing", True, 3)
        
        # Создаём оффер для плана 3
        offer_id_3 = await conn.fetchval("""
            INSERT INTO sub_plan_offers (
                sub_plan_id, ttl_days, cost,
                traffic_limit_day_mb, traffic_limit_mb,
                infinite_traffic, infinite_expire, is_active, position
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, plan_id_3, 30, 500, 10240, None, False, False, True, 1)
        
        # 2. Создаём физические ноды
        # 2.1. Активная физическая нода
        node_id_active = await conn.fetchval("""
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "192.168.1.100", "10.0.0.100", 8100, "arq-test-node-active", "ARQ Active Node", True)
        
        # 2.2. Неактивная физическая нода (для проверки фильтрации)
        node_id_inactive = await conn.fetchval("""
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "192.168.1.101", "10.0.0.101", 8101, "arq-test-node-inactive", "ARQ Inactive Node", False)
        
        # 3. Используем существующий шаблон протокола из seed_data
        tmp_id = await conn.fetchval("""
            SELECT id 
            FROM proto_templates 
            WHERE is_accepted = true 
            ORDER BY id 
            LIMIT 1
        """)
        
        if not tmp_id:
            raise RuntimeError(
                "Не найдено активных шаблонов в proto_templates! "
                "Запустите: python -m web.db.seed_data"
            )
        
        # 4. Используем существующий протокол из seed_data (связанный с tmp_id)
        proto_id = await conn.fetchval("""
            SELECT id 
            FROM protocols 
            WHERE tmp_id = $1 
            ORDER BY id 
            LIMIT 1
        """, tmp_id)
        
        if not proto_id:
            raise RuntimeError(
                f"Не найдено протокола для tmp_id={tmp_id} в protocols! "
                f"Запустите: python -m web.db.seed_data"
            )
        
        # 5. Создаём виртуальные ноды
        # 5.1. Активная виртуальная нода на активной физической ноде (user_visible=true)
        vnode_id_10 = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "VNode 10 Active", "vnode10.test.com", 9090, "/etc/config10.json", True)
        
        # 5.2. Вторая активная виртуальная нода на активной физической ноде
        vnode_id_11 = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "VNode 11 Active", "vnode11.test.com", 9091, "/etc/config11.json", True)
        
        # 5.3. Невидимая виртуальная нода на активной физической ноде (user_visible=false)
        vnode_id_invisible = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "VNode Invisible", "vnode-invisible.test.com", 9092, "/etc/config-invisible.json", False)
        
        # 5.4. Активная виртуальная нода на неактивной физической ноде
        vnode_id_on_inactive = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_inactive, proto_id, "VNode On Inactive Node", "vnode-inactive.test.com", 9093, "/etc/config-on-inactive.json", True)
        
        # 6. Связываем подписки с виртуальными нодами (для всех планов)
        await conn.execute("""
            INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
            VALUES 
                ($1, $2), ($3, $2), ($4, $2), ($5, $2),
                ($1, $6), ($3, $6), ($4, $6), ($5, $6),
                ($1, $7), ($3, $7), ($4, $7), ($5, $7)
        """, vnode_id_10, plan_id, vnode_id_11, vnode_id_invisible, vnode_id_on_inactive, plan_id_2, plan_id_3)
        
        # ========== ПОЛЬЗОВАТЕЛИ И ПОДПИСКИ ==========
        
        # User 1: Soft-deleted с неактивными подписками
        user1_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, true)
            RETURNING id
        """, 100001, "deleted_user")
        
        # Создаём платежи для User 1
        pay_order1_1 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user1_id, offer_id)
        
        pay_order1_2 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user1_id, offer_id_2)
        
        user1_order1 = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, false, now() - interval '10 days', $4, $5, false, false, 10240, $6, 0, 0, false)
            RETURNING id
        """, user1_id, plan_id, pay_order1_1, "uuid-deleted-user-sub1", "b64-deleted-sub1", None)
        
        user1_order2 = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, false, now() - interval '5 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user1_id, plan_id_2, pay_order1_2, "uuid-deleted-user-sub2", "b64-deleted-sub2")
        
        # User 2: Живой без активной подписки (3 неактивных)
        user2_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100002, "inactive_subs_user")
        
        user2_orders = []
        plans_for_user2 = [plan_id, plan_id_2, plan_id_3]
        offers_for_user2 = [offer_id, offer_id_2, offer_id_3]
        for i in range(3):
            pay_order = await conn.fetchval("""
                INSERT INTO pay_orders (
                    user_id, status, 
                    infinite_expire, infinite_traffic, 
                    traffic_limit_mb, traffic_limit_day_mb, 
                    ttl_days, cost
                )
                SELECT $1, 3, 
                    infinite_expire, infinite_traffic,
                    traffic_limit_mb, traffic_limit_day_mb,
                    ttl_days, cost
                FROM sub_plan_offers 
                WHERE id = $2
                RETURNING id
            """, user2_id, offers_for_user2[i])
            
            order_id = await conn.fetchval("""
                INSERT INTO user_subs (
                    user_id, sub_plan_id, order_id, is_active, expire_date,
                    uuid, b64_id, infinite_traffic, infinite_expire,
                    traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
                )
                VALUES ($1, $2, $3, false, now() - interval '1 days' * $4, $5, $6, false, false, 10240, NULL, 0, 0, false)
                RETURNING id
            """, user2_id, plans_for_user2[i], pay_order, (i + 1) * 10, f"uuid-inactive-user-sub{i+1}", f"b64-inactive-sub{i+1}")
            user2_orders.append(order_id)
        
        # User 3: Живой с 2 неактивными + 1 активной подпиской (для ADD операции)
        user3_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100003, "active_add_user")
        
        # Неактивные подписки User 3
        pay_order3_1 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user3_id, offer_id_2)
        
        user3_order1 = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, false, now() - interval '20 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user3_id, plan_id_2, pay_order3_1, "uuid-active-add-user-sub1", "b64-active-add-sub1")
        
        pay_order3_2 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user3_id, offer_id_3)
        
        user3_order2 = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, false, now() - interval '15 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user3_id, plan_id_3, pay_order3_2, "uuid-active-add-user-sub2", "b64-active-add-sub2")
        
        # Активная подписка User 3
        pay_order3_active = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user3_id, offer_id)
        
        user3_order_active = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user3_id, plan_id, pay_order3_active, "uuid-active-add-user", "b64-active-add")
        
        # User 4: Живой с 1 активной подпиской (для DELETE операции)
        user4_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100004, "active_delete_user")
        
        pay_order4_active = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user4_id, offer_id)
        
        user4_order_active = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user4_id, plan_id, pay_order4_active, "uuid-active-delete-user", "b64-active-delete")
        
        # ========== OUTBOX ЗАПИСИ ==========
        
        # Для User 3: ADD операции на обе активные ноды
        await conn.execute("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 1, $3), ($1, $2, 1, $4)
        """, "uuid-active-add-user", user3_order_active, vnode_id_10, vnode_id_11)
        
        # Для User 4: DELETE операции на обе активные ноды
        await conn.execute("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 2, $3), ($1, $2, 2, $4)
        """, "uuid-active-delete-user", user4_order_active, vnode_id_10, vnode_id_11)
        
        return {
            # План подписки
            "plan_id": plan_id,
            "offer_id": offer_id,
            "plan_id_2": plan_id_2,
            "offer_id_2": offer_id_2,
            "plan_id_3": plan_id_3,
            "offer_id_3": offer_id_3,
            
            # Физические ноды
            "node_id_active": node_id_active,
            "node_id_inactive": node_id_inactive,
            
            # Виртуальные ноды
            "vnode_id_10": vnode_id_10,  # Активная, видимая
            "vnode_id_11": vnode_id_11,  # Активная, видимая
            "vnode_id_invisible": vnode_id_invisible,  # Невидимая
            "vnode_id_on_inactive": vnode_id_on_inactive,  # На неактивной физ. ноде
            
            # Обратная совместимость для старых тестов
            "order_id": user3_order_active,
            
            # User 1: Soft-deleted
            "user1_deleted": {
                "user_id": user1_id,
                "user_sub_id": user1_order1,  # ID первой подписки
                "uuid": "uuid-deleted-user-sub1",  # Берём uuid из первой подписки
                "tg_username": "deleted_user",
                "orders": [user1_order1, user1_order2]
            },
            
            # User 2: Живой без активных подписок
            "user2_inactive_subs": {
                "user_id": user2_id,
                "user_sub_id": user2_orders[0],  # ID первой подписки
                "uuid": "uuid-inactive-user-sub1",  # Берём uuid из первой подписки
                "tg_username": "inactive_subs_user",
                "orders": user2_orders
            },
            
            # User 3: Живой с активной подпиской для ADD
            "user3_active_for_add": {
                "user_id": user3_id,
                "user_sub_id": user3_order_active,  # ID активной подписки
                "uuid": "uuid-active-add-user",
                "tg_username": "active_add_user",
                "order_inactive_1": user3_order1,
                "order_inactive_2": user3_order2,
                "order_active": user3_order_active
            },
            
            # User 4: Живой с активной подпиской для DELETE
            "user4_active_for_delete": {
                "user_id": user4_id,
                "user_sub_id": user4_order_active,  # ID активной подписки
                "uuid": "uuid-active-delete-user",
                "tg_username": "active_delete_user",
                "order_active": user4_order_active
            },
        }


@pytest.fixture
async def real_parser_scripts(db_pool):
    """
    Загружает реальные парсеры метрик из proto_templates.
    
    Используется для тестирования parse_node_output с реальными парсерами из БД.
    
    Если БД пустая (после db_seed), вставляет реальный парсер xray.
    """
    async with db_pool.acquire() as conn:
        parsers = await conn.fetch("""
            SELECT id, title, metrics_parser_code, sub_required_libs, proto_python_lib
            FROM proto_templates
            WHERE metrics_parser_code IS NOT NULL
        """)
        
        if not parsers:
            # БД пустая, вставляем реальный парсер xray
            parser_code = '''def parse(raw_metrics):
    """Универсальный парсер метрик для Xray"""
    
    def _parse_plain_text(text):
        """Fallback парсер для plain text формата"""
        lines = text.strip().split('\\n')
        traffic_map = defaultdict(int)
        
        for line in lines:
            if '>>>' not in line:
                continue
            
            parts = line.split('>>>')
            if len(parts) >= 2:
                username = parts[1]
                numbers = re.findall(r'\\d+', line)
                if numbers:
                    traffic_map[username] += int(numbers[-1])
        
        return [
            {'user_sub_id': int(u), 'total_mb_used': mb}
            for u, mb in traffic_map.items()
        ], []
    
    if isinstance(raw_metrics, str):
        try:
            json_obj = json.loads(raw_metrics)
        except json.JSONDecodeError:
            return _parse_plain_text(raw_metrics)
    else:
        json_obj = raw_metrics
    
    traffic_map = defaultdict(int)
    troubles = []
    
    stats_list = json_obj.get('stat', [])
    if not stats_list:
        return [], []
    
    for user in stats_list:
        name = user.get('name', '')
        if not name or 'user>>>' not in name:
            troubles.append(user)
            continue
        
        parts = name.split('>>>')
        if len(parts) < 2:
            troubles.append(user)
            continue
        
        user_sub_id = int(parts[1])
        traffic_bytes = int(user.get('value', 0))
        traffic_mb = traffic_bytes // 1024 // 1024
        
        traffic_map[user_sub_id] += traffic_mb
    
    users_traffics = [
        {'user_sub_id': username, 'total_mb_used': used_mb} 
        for username, used_mb in traffic_map.items()
    ]
    
    return users_traffics, troubles
'''
            
            tmp_id = await conn.fetchval("""
                INSERT INTO proto_templates (
                    title, url_tmp, status, is_accepted,
                    reload_core_command, sub_prepare_script,
                    proto_python_lib, metrics_parser_code,
                    api_add_user_script, api_delete_user_script,
                    flatten_json_users_key, flatten_user_identifier_key,
                    metrics_command, api_metrics_script
                )
                VALUES (
                    'vless_tcp_sni_based', 'https://example.com', 1, true,
                    'systemctl reload xray', '#!/bin/bash',
                    'xtlsapi', $1,
                    'python add.py', 'python del.py',
                    'clients', 'email',
                    'xray api statsquery', 'python metrics.py'
                )
                RETURNING id
            """, parser_code)
            
            # Перечитываем
            parsers = await conn.fetch("""
                SELECT id, title, metrics_parser_code, sub_required_libs, proto_python_lib
                FROM proto_templates
                WHERE metrics_parser_code IS NOT NULL
            """)
        
        return {p['title']: dict(p) for p in parsers}


@pytest.fixture
def sample_xray_outputs():
    """
    Реальные примеры stdout от xray в разных форматах.
    
    Поддерживаемые форматы:
    1. JSON dict (от xtlsapi библиотеки) - Python dict
    2. JSON string (от CLI команды xray api statsquery) - строка
    """
    return {
        # Формат 1: JSON dict от xtlsapi (чистый случай)
        'json_dict_clean': {
            'stat': [
                {'name': 'user>>>100>>>traffic>>>downlink', 'value': 104857600},  # 100MB
                {'name': 'user>>>100>>>traffic>>>uplink', 'value': 52428800},     # 50MB
                {'name': 'user>>>200>>>traffic>>>downlink', 'value': 209715200},    # 200MB
                {'name': 'user>>>200>>>traffic>>>uplink', 'value': 104857600},      # 100MB
            ]
        },
        
        # Формат 2: JSON string от CLI (реальный пример с отсутствующим value)
        'json_string_from_cli': '''{
    "stat": [
        {
            "name": "user>>>300>>>traffic>>>downlink"
        },
        {
            "name": "user>>>300>>>traffic>>>uplink",
            "value": 3331331376938
        },
        {
            "name": "user>>>400>>>traffic>>>downlink",
            "value": 31331376938
        },
        {
            "name": "user>>>400>>>traffic>>>uplink",
            "value": 31331376938
        }
    ]
}''',
        
        # С troubles: отсутствует user>>>, неправильный формат
        'with_troubles': {
            'stat': [
                {'name': 'user>>>500>>>traffic>>>downlink', 'value': 104857600},
                {'name': 'invalid_format_no_user_prefix', 'value': 999999},  # troubles - нет "user>>>"
                {'name': 'user>>>600>>>traffic>>>uplink'},  # value отсутствует (0)
            ]
        },
        
        # Пустой список статистики
        'empty_stats': {
            'stat': []
        },
    }


@pytest.fixture
async def traffic_reset_seed(db_pool, arq_test_seed):
    """
    Создаёт тестовые данные для проверки reset_day_user_traffic (крона сброса трафика).
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, план).
    Создаёт ОТДЕЛЬНЫХ пользователей с tg_id 400001-400006 для изоляции.
    
    Критические SQL фильтры в reset_user_traffic_per_day():
    - is_active = true (только активные подписки)
    - is_limited = true (только ограниченные пользователи)
    - u.is_deleted = false (только неудалённые пользователи)
    - np.user_visible = true (только видимые ноды)
    - n.is_active = true (только активные физические ноды)
    """
    async with db_pool.acquire() as conn:
        # Очищаем outbox от записей arq_test_seed для изоляции
        await conn.execute("DELETE FROM sub_nodes_outbox")
        
        # Получаем plan_id из arq_test_seed
        plan_id = arq_test_seed['plan_id']
        
        # ========== СОЗДАЁМ ПОЛЬЗОВАТЕЛЕЙ ДЛЯ ПРОВЕРКИ SQL ФИЛЬТРОВ ==========
        
        # User A: ДОЛЖЕН разблокироваться (is_limited=true, is_active=true, is_deleted=false)
        user_a_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400001, "user_a_limited")
        
        pay_order_a = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_a_id, arq_test_seed['offer_id'])
        
        order_a = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, true, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 500)
            RETURNING id
        """, user_a_id, plan_id, pay_order_a, "uuid-reset-user-a", "b64-reset-a")
        
        # User B: ДОЛЖЕН разблокироваться (is_limited=true, is_active=true, is_deleted=false)
        user_b_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400002, "user_b_limited")
        
        pay_order_b = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_b_id, arq_test_seed['offer_id'])
        
        order_b = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, true, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 800)
            RETURNING id
        """, user_b_id, plan_id, pay_order_b, "uuid-reset-user-b", "b64-reset-b")
        
        # User C: НЕ должен попасть (is_limited=false - уже разблокирован)
        user_c_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400003, "user_c_not_limited")
        
        pay_order_c = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_c_id, arq_test_seed['offer_id'])
        
        order_c = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, true, false, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 300)
            RETURNING id
        """, user_c_id, plan_id, pay_order_c, "uuid-reset-user-c", "b64-reset-c")
        
        # User D: НЕ должен попасть (is_active=false - неактивная подписка)
        user_d_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400004, "user_d_inactive_sub")
        
        pay_order_d = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_d_id, arq_test_seed['offer_id'])
        
        order_d = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, false, true, now() - interval '5 days', $4, $5, false, false, 10240, NULL, 0, 600)
            RETURNING id
        """, user_d_id, plan_id, pay_order_d, "uuid-reset-user-d", "b64-reset-d")
        
        # User E: НЕ должен попасть (is_deleted=true - пользователь удалён)
        user_e_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, true)
            RETURNING id
        """, 400005, "user_e_deleted")
        
        pay_order_e = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_e_id, arq_test_seed['offer_id'])
        
        order_e = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, true, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 700)
            RETURNING id
        """, user_e_id, plan_id, pay_order_e, "uuid-reset-user-e", "b64-reset-e")
        
        # User F: ДОЛЖЕН разблокироваться, но НЕ на невидимой ноде (для теста фильтра user_visible)
        user_f_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400006, "user_f_invisible_node")
        
        pay_order_f = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_f_id, arq_test_seed['offer_id'])
        
        order_f = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb
            )
            VALUES ($1, $2, $3, true, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 900)
            RETURNING id
        """, user_f_id, plan_id, pay_order_f, "uuid-reset-user-f", "b64-reset-f")
        
        return {
            # Инфраструктура из arq_test_seed
            "plan_id": plan_id,
            "node_id_active": arq_test_seed['node_id_active'],
            "vnode_id_10": arq_test_seed['vnode_id_10'],
            "vnode_id_11": arq_test_seed['vnode_id_11'],
            "vnode_id_invisible": arq_test_seed['vnode_id_invisible'],
            
            # Пользователи которые ДОЛЖНЫ разблокироваться
            "should_unlock": {
                "user_a": {"user_id": user_a_id, "order_id": order_a, "username": "user_a_limited", "uuid": "uuid-reset-user-a", "traffic_mb": 500},
                "user_b": {"user_id": user_b_id, "order_id": order_b, "username": "user_b_limited", "uuid": "uuid-reset-user-b", "traffic_mb": 800},
            },
            
            # Пользователи которые НЕ должны попасть в результат
            "should_not_unlock": {
                "user_c": {"user_id": user_c_id, "order_id": order_c, "username": "user_c_not_limited", "reason": "not limited"},
                "user_d": {"user_id": user_d_id, "order_id": order_d, "username": "user_d_inactive_sub", "reason": "inactive subscription"},
                "user_e": {"user_id": user_e_id, "order_id": order_e, "username": "user_e_deleted", "reason": "user deleted"},
                "user_f": {"user_id": user_f_id, "order_id": order_f, "username": "user_f_invisible_node", "reason": "on invisible node"},
            },
        }


@pytest.fixture
async def outbox_cleaner_seed(db_pool, arq_test_seed):
    """
    Создаёт тестовые данные для проверки retry_stuck_core_proto_actions.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, план).
    Создаёт ОТДЕЛЬНЫХ пользователей с tg_id 500001-500005 для изоляции.
    Создаёт записи в outbox с разными состояниями для проверки фильтров.
    
    Критические SQL фильтры в get_stuck_actions():
    - is_retried = false (только не ретраенные)
    - created_at < now() - interval '1 hour' (только старые > 1 часа)
    """
    async with db_pool.acquire() as conn:
        # Очищаем outbox от записей arq_test_seed для изоляции
        await conn.execute("DELETE FROM sub_nodes_outbox")
        
        # Получаем plan_id из arq_test_seed
        plan_id = arq_test_seed['plan_id']
        vnode_id_10 = arq_test_seed['vnode_id_10']
        vnode_id_11 = arq_test_seed['vnode_id_11']
        
        # ========== СОЗДАЁМ ПОЛЬЗОВАТЕЛЕЙ ДЛЯ ПРОВЕРКИ SQL ФИЛЬТРОВ ==========
        
        # User A: ДОЛЖЕН ретраиться (is_retried=false, created_at старая)
        user_a_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 500001, "user_a_stuck")
        
        pay_order_a = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_a_id, arq_test_seed['offer_id'])
        
        order_a = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_a_id, plan_id, pay_order_a, "uuid-stuck-user-a", "b64-stuck-a")
        
        # Создаём старую outbox запись для User A (2 часа назад, is_retried=false)
        outbox_a = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id, is_retried, created_at)
            VALUES ($1, $2, 1, $3, false, now() - interval '2 hours')
            RETURNING id
        """, "uuid-stuck-user-a", order_a, vnode_id_10)
        
        # User B: ДОЛЖЕН ретраиться (is_retried=false, created_at старая)
        user_b_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 500002, "user_b_stuck")
        
        pay_order_b = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_b_id, arq_test_seed['offer_id'])
        
        order_b = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_b_id, plan_id, pay_order_b, "uuid-stuck-user-b", "b64-stuck-b")
        
        # Создаём старую outbox запись для User B (3 часа назад, is_retried=false)
        outbox_b = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id, is_retried, created_at)
            VALUES ($1, $2, 2, $3, false, now() - interval '3 hours')
            RETURNING id
        """, "uuid-stuck-user-b", order_b, vnode_id_11)
        
        # User C: НЕ должен ретраиться (created_at свежая - 30 минут)
        user_c_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 500003, "user_c_fresh")
        
        pay_order_c = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_c_id, arq_test_seed['offer_id'])
        
        order_c = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_c_id, plan_id, pay_order_c, "uuid-stuck-user-c", "b64-stuck-c")
        
        # Создаём свежую outbox запись для User C (30 минут назад - меньше 1 часа)
        outbox_c = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id, is_retried, created_at)
            VALUES ($1, $2, 1, $3, false, now() - interval '30 minutes')
            RETURNING id
        """, "uuid-stuck-user-c", order_c, vnode_id_10)
        
        # User D: НЕ должен ретраиться (is_retried=true - уже ретраился)
        user_d_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 500004, "user_d_already_retried")
        
        pay_order_d = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_d_id, arq_test_seed['offer_id'])
        
        order_d = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_d_id, plan_id, pay_order_d, "uuid-stuck-user-d", "b64-stuck-d")
        
        # Создаём старую outbox запись для User D (2 часа назад, но is_retried=true)
        outbox_d = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id, is_retried, created_at)
            VALUES ($1, $2, 1, $3, true, now() - interval '2 hours')
            RETURNING id
        """, "uuid-stuck-user-d", order_d, vnode_id_10)
        
        # User E: ДОЛЖЕН попасть в выборку, но НЕ получит задачу (подписка неактивна - len(sub_nodes)=0)
        user_e_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 500005, "user_e_no_nodes")
        
        pay_order_e = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_e_id, arq_test_seed['offer_id'])
        
        # Создаём неактивную подписку для User E (get_nodes_to_core_proto_action вернёт [])
        order_e = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, false, now() - interval '5 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_e_id, plan_id, pay_order_e, "uuid-stuck-user-e", "b64-stuck-e")
        
        outbox_e = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id, is_retried, created_at)
            VALUES ($1, $2, 1, $3, false, now() - interval '2 hours')
            RETURNING id
        """, "uuid-stuck-user-e", order_e, vnode_id_10)
        
        return {
            # Инфраструктура из arq_test_seed
            "plan_id": plan_id,
            "node_id_active": arq_test_seed['node_id_active'],
            "vnode_id_10": vnode_id_10,
            "vnode_id_11": vnode_id_11,
            
            # Записи которые ДОЛЖНЫ ретраиться
            "should_retry": {
                "outbox_a": {"id": outbox_a, "user_id": user_a_id, "order_id": order_a, "username": "user_a_stuck", "uuid": "uuid-stuck-user-a"},
                "outbox_b": {"id": outbox_b, "user_id": user_b_id, "order_id": order_b, "username": "user_b_stuck", "uuid": "uuid-stuck-user-b"},
            },
            
            # Записи которые НЕ должны ретраиться
            "should_not_retry": {
                "outbox_c": {"id": outbox_c, "user_id": user_c_id, "order_id": order_c, "username": "user_c_fresh", "reason": "too fresh (< 1 hour)"},
                "outbox_d": {"id": outbox_d, "user_id": user_d_id, "order_id": order_d, "username": "user_d_already_retried", "reason": "already retried"},
                "outbox_e": {"id": outbox_e, "user_id": user_e_id, "order_id": order_e, "username": "user_e_no_nodes", "reason": "no nodes (inactive sub)"},
            },
        }


@pytest.fixture
async def sub_api_seed(db_pool, arq_test_seed):
    """
    Создаёт тестовые данные для проверки GET /sub/{b64_id} эндпоинта.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, план).
    Создаёт ОТДЕЛЬНЫХ пользователей с tg_id 600001-600005 для изоляции.
    
    Критические SQL фильтры в get_sub_links():
    - us.is_active = true (только активные подписки)
    - u.is_deleted = false (только неудалённые пользователи)
    - us.traffic_used_day_mb < us.traffic_limit_day (в пределах лимита)
    - us.expire_date > now() (не истёкшие)
    - np.user_visible = true (только видимые ноды)
    """
    async with db_pool.acquire() as conn:
        # Получаем plan_id из arq_test_seed
        plan_id = arq_test_seed['plan_id']
        vnode_id_10 = arq_test_seed['vnode_id_10']
        vnode_id_11 = arq_test_seed['vnode_id_11']
        
        # Обновляем proto_template чтобы добавить реальный sub_prepare_script
        await conn.execute("""
            UPDATE proto_templates
            SET sub_prepare_script = $1,
                sub_required_libs = NULL
            WHERE id = (
                SELECT pt.id FROM proto_templates pt
                JOIN protocols p ON p.tmp_id = pt.id
                WHERE p.id = (
                    SELECT proto_id FROM nodes_protocols WHERE id = $2
                )
            )
        """, '''
def prepare_sub(user_uuid, config_link):
    """Простой скрипт для тестов"""
    return f"vless://{user_uuid}@test.server.com:443?{config_link}#TestLocation"
''', vnode_id_10)
        
        # Добавляем config_link для нод
        await conn.execute("""
            UPDATE nodes_protocols
            SET config_link = $1
            WHERE id = $2
        """, "encryption=none&type=tcp&security=tls", vnode_id_10)
        
        await conn.execute("""
            UPDATE nodes_protocols
            SET config_link = $1
            WHERE id = $2
        """, "encryption=none&type=ws&path=/api", vnode_id_11)
        
        # ========== СОЗДАЁМ ПОЛЬЗОВАТЕЛЕЙ ДЛЯ ПРОВЕРКИ SQL ФИЛЬТРОВ ==========
        
        # User A: Активная подписка (ДОЛЖЕН получить ссылки)
        user_a_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 600001, "user_a_active")
        
        pay_order_a = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_a_id, arq_test_seed['offer_id'])
        
        order_a = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id, 
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit, 
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 500, false)
            RETURNING id
        """, user_a_id, plan_id, pay_order_a, "uuid-sub-user-a", "b64-sub-active-a-valid-16chars")
        
        # User B: Превышен лимит трафика (НЕ должен получить ссылки)
        user_b_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 600002, "user_b_limit_exceeded")
        
        pay_order_b = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_b_id, arq_test_seed['offer_id'])
        
        order_b = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 15000, false)
            RETURNING id
        """, user_b_id, plan_id, pay_order_b, "uuid-sub-user-b", "b64-sub-limit-b-valid-16chars")
        
        # User C: Подписка истекла (НЕ должен получить ссылки)
        user_c_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 600003, "user_c_expired")
        
        pay_order_c = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_c_id, arq_test_seed['offer_id'])
        
        order_c = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() - interval '5 days', $4, $5, false, false, 10240, NULL, 0, 300, false)
            RETURNING id
        """, user_c_id, plan_id, pay_order_c, "uuid-sub-user-c", "b64-sub-expired-c-valid-16chars")
        
        # User D: Подписка неактивна (НЕ должен получить ссылки)
        user_d_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 600004, "user_d_inactive")
        
        pay_order_d = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_d_id, arq_test_seed['offer_id'])
        
        order_d = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, false, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 200, false)
            RETURNING id
        """, user_d_id, plan_id, pay_order_d, "uuid-sub-user-d", "b64-sub-inactive-d-valid-16chars")
        
        # User E: Пользователь удалён (НЕ должен получить ссылки)
        user_e_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, true)
            RETURNING id
        """, 600005, "user_e_deleted")
        
        pay_order_e = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_e_id, arq_test_seed['offer_id'])
        
        order_e = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 100, false)
            RETURNING id
        """, user_e_id, plan_id, pay_order_e, "uuid-sub-user-e", "b64-sub-deleted-e-valid-16chars")
        
        return {
            # Инфраструктура из arq_test_seed
            "plan_id": plan_id,
            "vnode_id_10": vnode_id_10,
            "vnode_id_11": vnode_id_11,
            
            # Пользователь с активной подпиской
            "active_user": {
                "user_id": user_a_id,
                "uuid": "uuid-sub-user-a",
                "b64_id": "b64-sub-active-a-valid-16chars",
                "order_id": order_a,
                "traffic_mb": 500,
            },
            
            # Пользователи которые НЕ должны получить ссылки
            "invalid_users": {
                "limit_exceeded": {"user_id": user_b_id, "b64_id": "b64-sub-limit-b-valid-16chars", "reason": "traffic limit exceeded"},
                "expired": {"user_id": user_c_id, "b64_id": "b64-sub-expired-c-valid-16chars", "reason": "subscription expired"},
                "inactive": {"user_id": user_d_id, "b64_id": "b64-sub-inactive-d-valid-16chars", "reason": "subscription inactive"},
                "deleted": {"user_id": user_e_id, "b64_id": "b64-sub-deleted-e-valid-16chars", "reason": "user deleted"},
            },
        }


@pytest.fixture(autouse=True)
async def flush_redis():
    """
    Очищает Redis перед каждым тестом.
    """
    from  web.arq_worker.config import redis_settings
    redis = Redis(**redis_settings)
    await redis.flushdb()
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest.fixture
async def metrics_collector_seed(db_pool, arq_test_seed, real_parser_scripts):
    """
    Создаёт тестовые данные для проверки collect_traffic_metrics и SQL фильтров.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, план).
    Создаёт ОТДЕЛЬНЫХ пользователей с tg_id 200001-200007 для изоляции.
    
    Критические проверки:
    - Блокируются ТОЛЬКО пользователи с: превышение лимита + активная подписка + не удалён + не ограничен
    - Все остальные комбинации НЕ блокируются
    """
    async with db_pool.acquire() as conn:
        # 0. Сброс изменяемых полей для изоляции между тестами
        await conn.execute("""
            UPDATE user_subs 
            SET traffic_used_day_mb = CASE 
                WHEN id IN (
                    SELECT us.id FROM user_subs us
                    JOIN users u ON u.id = us.user_id
                    WHERE u.tg_id = 200001
                ) THEN 500
                WHEN id IN (
                    SELECT us.id FROM user_subs us
                    JOIN users u ON u.id = us.user_id
                    WHERE u.tg_id = 200002
                ) THEN 800
                ELSE 500
            END
            WHERE user_id IN (
                SELECT id FROM users WHERE tg_id BETWEEN 200001 AND 200007
            );
            
            UPDATE user_subs SET is_limited = false WHERE user_id IN (
                SELECT id FROM users WHERE tg_id BETWEEN 200001 AND 200007
            );
            DELETE FROM sub_nodes_outbox WHERE user_sub_id IN (
                SELECT id FROM user_subs WHERE user_id IN (
                    SELECT id FROM users WHERE tg_id BETWEEN 200001 AND 200007
                )
            );
        """)
        
        # 1. Добавляем metrics_parser_code в существующий proto_template из arq_test_seed
        parser = list(real_parser_scripts.values())[0]
        await conn.execute("""
            UPDATE proto_templates 
            SET metrics_parser_code = $1,
                metrics_command = 'xray api statsquery',
                api_metrics_script = 'python metrics.py'
            WHERE id = (
                SELECT pt.id FROM proto_templates pt
                JOIN protocols p ON p.tmp_id = pt.id
                WHERE p.id = $2
            )
        """, parser['metrics_parser_code'], arq_test_seed['vnode_id_10'])
        
        # 2. Добавляем metrics_port в существующую виртуальную ноду
        await conn.execute("""
            UPDATE nodes_protocols
            SET metrics_port = 9090
            WHERE id = $1
        """, arq_test_seed['vnode_id_10'])
        
        # 3. Создаём НОВЫЙ план подписки с лимитом 1000 MB для metrics тестов
        metrics_plan_id = await conn.fetchval("""
            INSERT INTO sub_plans (title, description, is_active, position)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, "Metrics Traffic Test Plan", "Plan for traffic limit testing", True, 98)
        
        # Создаём оффер для metrics плана
        metrics_offer_id = await conn.fetchval("""
            INSERT INTO sub_plan_offers (
                sub_plan_id, ttl_days, cost,
                traffic_limit_day_mb, traffic_limit_mb,
                infinite_traffic, infinite_expire, is_active, position
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, metrics_plan_id, 30, 500, 1000, None, False, False, True, 1)
        
        # 4. Связываем metrics план с существующей виртуальной нодой
        await conn.execute("""
            INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
            VALUES ($1, $2)
        """, arq_test_seed['vnode_id_10'], metrics_plan_id)
        
        # 5. Очищаем outbox от записей arq_test_seed для изоляции тестов
        await conn.execute("DELETE FROM sub_nodes_outbox")
        
        # ========== СОЗДАЁМ ОТДЕЛЬНЫХ ПОЛЬЗОВАТЕЛЕЙ (tg_id 200001-200007) ==========
        
        # User A: ДОЛЖЕН блокироваться (превысил лимит, активная подписка, не удалён, не ограничен)
        user_a_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 200001, "user_a_should_block")
        
        pay_order_a = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_a_id, metrics_offer_id)
        
        order_a = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date, 
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day, 
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, true, false, now() + interval '30 days', $4, $5, false, false, 1000, NULL, 0, 500)
            RETURNING id
        """, user_a_id, metrics_plan_id, pay_order_a, "uuid-metrics-user-a", "b64-metrics-a")
        
        # User B: ДОЛЖЕН блокироваться (превысил лимит, активная подписка, не удалён, не ограничен)
        user_b_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 200002, "user_b_should_block")
        
        pay_order_b = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_b_id, metrics_offer_id)
        
        order_b = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day,
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, true, false, now() + interval '30 days', $4, $5, false, false, 1000, NULL, 0, 800)
            RETURNING id
        """, user_b_id, metrics_plan_id, pay_order_b, "uuid-metrics-user-b", "b64-metrics-b")
        
        # User C: НЕ должен блокироваться (превысил лимит, но подписка неактивна)
        user_c_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 200003, "user_c_inactive_sub")
        
        pay_order_c = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_c_id, metrics_offer_id)
        
        order_c = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day,
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, false, false, now() - interval '5 days', $4, $5, false, false, 1000, NULL, 0, 500)
            RETURNING id
        """, user_c_id, metrics_plan_id, pay_order_c, "uuid-metrics-user-c", "b64-metrics-c")
        
        # User D: НЕ должен блокироваться (превысил лимит, но пользователь удалён)
        user_d_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, true)
            RETURNING id
        """, 200004, "user_d_deleted")
        
        pay_order_d = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_d_id, metrics_offer_id)
        
        order_d = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day,
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, true, false, now() + interval '30 days', $4, $5, false, false, 1000, NULL, 0, 500)
            RETURNING id
        """, user_d_id, metrics_plan_id, pay_order_d, "uuid-metrics-user-d", "b64-metrics-d")
        
        # User E: НЕ должен блокироваться (превысил лимит, но уже ограничен)
        user_e_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 200005, "user_e_already_limited")
        
        pay_order_e = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_e_id, metrics_offer_id)
        
        order_e = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day,
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, true, true, now() + interval '30 days', $4, $5, false, false, 1000, NULL, 0, 500)
            RETURNING id
        """, user_e_id, metrics_plan_id, pay_order_e, "uuid-metrics-user-e", "b64-metrics-e")
        
        # User F: НЕ должен блокироваться (НЕ превысил лимит)
        user_f_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 200006, "user_f_within_limit")
        
        pay_order_f = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_f_id, metrics_offer_id)
        
        order_f = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day,
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, true, false, now() + interval '30 days', $4, $5, false, false, 1000, NULL, 0, 500)
            RETURNING id
        """, user_f_id, metrics_plan_id, pay_order_f, "uuid-metrics-user-f", "b64-metrics-f")
        
        # User G: НЕ должен блокироваться (превысил лимит, но подписка истекла и выключена кроной sub_revocator)
        user_g_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 200007, "user_g_expired_sub")
        
        pay_order_g = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_g_id, metrics_offer_id)
        
        order_g = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, is_limited, expire_date,
                                   uuid, b64_id, infinite_traffic, infinite_expire, traffic_limit_day,
                                   used_mb_limit, used_mb, traffic_used_day_mb)
            VALUES ($1, $2, $3, false, false, now() - interval '1 days', $4, $5, false, false, 1000, NULL, 0, 500)
            RETURNING id
        """, user_g_id, metrics_plan_id, pay_order_g, "uuid-metrics-user-g", "b64-metrics-g")
        
        return {
            # Переиспользуем инфраструктуру из arq_test_seed
            "plan_id": metrics_plan_id,
            "node_id": arq_test_seed['node_id_active'],
            "vnode_id": arq_test_seed['vnode_id_10'],
            "proto_id": arq_test_seed.get('proto_id'),  # Может не быть в старой версии
            
            # Пользователи которые ДОЛЖНЫ блокироваться
            "should_block": {
                "user_a": {"user_id": user_a_id, "order_id": order_a, "username": "user_a_should_block", "initial_traffic": 500},
                "user_b": {"user_id": user_b_id, "order_id": order_b, "username": "user_b_should_block", "initial_traffic": 800},
            },
            
            # Пользователи которые НЕ должны блокироваться
            "should_not_block": {
                "user_c": {"user_id": user_c_id, "order_id": order_c, "username": "user_c_inactive_sub", "reason": "inactive subscription"},
                "user_d": {"user_id": user_d_id, "order_id": order_d, "username": "user_d_deleted", "reason": "user deleted"},
                "user_e": {"user_id": user_e_id, "order_id": order_e, "username": "user_e_already_limited", "reason": "already limited"},
                "user_f": {"user_id": user_f_id, "order_id": order_f, "username": "user_f_within_limit", "reason": "within limit"},
                "user_g": {"user_id": user_g_id, "order_id": order_g, "username": "user_g_expired_sub", "reason": "expired subscription"},
            },
        }


@pytest.fixture
async def revoke_seed(db_pool, arq_test_seed):
    """
    Создаёт тестовые данные для проверки revoke_sub_plan_by_expire и SQL фильтров.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, план).
    Создаёт ОТДЕЛЬНЫХ пользователей с tg_id 300001-300005 для изоляции.
    
    Критические SQL фильтры:
    - is_active = true (только активные подписки)
    - expire_date < now() (только истёкшие)
    - u.is_deleted = false (только неудалённые пользователи)
    - np.user_visible = true (только видимые ноды)
    - n.is_active = true (только активные физические ноды)
    """
    async with db_pool.acquire() as conn:
        # Очищаем outbox от записей arq_test_seed для изоляции
        await conn.execute("DELETE FROM sub_nodes_outbox")
        
        # Получаем plan_id из arq_test_seed
        plan_id = arq_test_seed['plan_id']
        
        # ========== СОЗДАЁМ ПОЛЬЗОВАТЕЛЕЙ ДЛЯ ПРОВЕРКИ SQL ФИЛЬТРОВ ==========
        
        # User A: ДОЛЖЕН удаляться (is_active=true, expire_date < now(), is_deleted=false)
        user_a_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 300001, "user_a_should_revoke")
        
        pay_order_a = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_a_id, arq_test_seed['offer_id'])
        
        order_a = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() - interval '1 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_a_id, plan_id, pay_order_a, "uuid-revoke-user-a", "b64-revoke-a")
        
        # User B: ДОЛЖЕН удаляться (is_active=true, expire_date < now(), is_deleted=false)
        user_b_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 300002, "user_b_should_revoke")
        
        pay_order_b = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_b_id, arq_test_seed['offer_id'])
        
        order_b = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() - interval '5 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_b_id, plan_id, pay_order_b, "uuid-revoke-user-b", "b64-revoke-b")
        
        # User C: НЕ должен удаляться (is_active=false - уже выключена)
        user_c_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 300003, "user_c_already_inactive")
        
        pay_order_c = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 3, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_c_id, arq_test_seed['offer_id'])
        
        order_c = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, false, now() - interval '10 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_c_id, plan_id, pay_order_c, "uuid-revoke-user-c", "b64-revoke-c")
        
        # User D: НЕ должен удаляться (expire_date > now() - ещё активна)
        user_d_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 300004, "user_d_not_expired")
        
        pay_order_d = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_d_id, arq_test_seed['offer_id'])
        
        order_d = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_d_id, plan_id, pay_order_d, "uuid-revoke-user-d", "b64-revoke-d")
        
        # User E: НЕ должен удаляться (is_deleted=true - пользователь удалён)
        user_e_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, true)
            RETURNING id
        """, 300005, "user_e_deleted")
        
        pay_order_e = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_e_id, arq_test_seed['offer_id'])
        
        order_e = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() - interval '2 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user_e_id, plan_id, pay_order_e, "uuid-revoke-user-e", "b64-revoke-e")
        
        return {
            # Инфраструктура из arq_test_seed
            "plan_id": plan_id,
            "node_id_active": arq_test_seed['node_id_active'],
            "vnode_id_10": arq_test_seed['vnode_id_10'],
            "vnode_id_11": arq_test_seed['vnode_id_11'],
            
            # Пользователи которые ДОЛЖНЫ удаляться
            "should_revoke": {
                "user_a": {"user_id": user_a_id, "order_id": order_a, "username": "user_a_should_revoke", "uuid": "uuid-revoke-user-a"},
                "user_b": {"user_id": user_b_id, "order_id": order_b, "username": "user_b_should_revoke", "uuid": "uuid-revoke-user-b"},
            },
            
            # Пользователи которые НЕ должны удаляться
            "should_not_revoke": {
                "user_c": {"user_id": user_c_id, "order_id": order_c, "username": "user_c_already_inactive", "reason": "already inactive"},
                "user_d": {"user_id": user_d_id, "order_id": order_d, "username": "user_d_not_expired", "reason": "not expired yet"},
                "user_e": {"user_id": user_e_id, "order_id": order_e, "username": "user_e_deleted", "reason": "user deleted"},
            },
        }


@pytest.fixture
async def redis_pool():
    """Реальный Redis pool для тестов платёжки"""
    from web.sub.config_dir.config import redis_settings
    
    redis = Redis(**redis_settings)
    yield redis
    
    # Очищаем все ключи с префиксом payment после теста
    keys = await redis.keys('payment:*')
    if keys:
        await redis.delete(*keys)
    
    await redis.aclose()


@pytest.fixture
async def payment_seed(db_pool, db_seed, arq_test_seed):
    """
    Создаёт тестовые данные для проверки платёжных эндпоинтов Robokassa.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, план, оффер).
    Создаёт ОТДЕЛЬНОГО пользователя с tg_id 700001 для изоляции.
    
    Возвращает:
    - user_id: ID пользователя
    - plan_id: ID тарифного плана
    - offer_id: ID оффера для плана
    - uuid: UUID пользователя
    - tg_username: Telegram username пользователя
    - vnode_id_10, vnode_id_11: ID активных виртуальных нод
    """
    async with db_pool.acquire() as conn:
        # Получаем plan_id и offer_id из arq_test_seed
        plan_id = arq_test_seed['plan_id']
        offer_id = arq_test_seed['offer_id']
        vnode_id_10 = arq_test_seed['vnode_id_10']
        vnode_id_11 = arq_test_seed['vnode_id_11']
        
        # Создаём отдельного пользователя для платёжных тестов
        user_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 700001, "payment_test_user")
        
        return {
            # Инфраструктура из arq_test_seed
            "plan_id": plan_id,
            "offer_id": offer_id,
            "vnode_id_10": vnode_id_10,
            "vnode_id_11": vnode_id_11,
            
            # Пользователь для платёжных тестов
            "user_id": user_id,
            "tg_username": "payment_test_user",
        }


@pytest.fixture
async def infinite_flags_test_seed(db_pool, arq_test_seed):
    """
    Создаёт тестовые подписки с разными комбинациями infinite_traffic и infinite_expire.
    
    Включает 4 сценария:
    1. infinite_traffic=true, infinite_expire=false - истёк срок (должна деактивироваться по дате)
    2. infinite_traffic=false, infinite_expire=true - превышен лимит (должна деактивироваться по трафику)
    3. infinite_traffic=true, infinite_expire=true - полностью безлимитная (НЕ деактивируется)
    4. infinite_traffic=false, infinite_expire=false - с лимитами, истёк срок (деактивируется)
    """
    async with db_pool.acquire() as conn:
        plan_id = arq_test_seed['plan_id']
        offer_id = arq_test_seed['offer_id']
        
        # === Сценарий 1: Безлимитный трафик, но истёк срок ===
        user_inf_traffic_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400001, "user_inf_traffic_expired")
        
        pay_order_inf_traffic = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_inf_traffic_id, offer_id)
        
        sub_inf_traffic = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() - interval '1 day', $4, $5, true, false, 5120, 10240, 5000, 1000, false)
            RETURNING id
        """, user_inf_traffic_id, plan_id, pay_order_inf_traffic, 
            "uuid-inf-traffic-expired", "b64-inf-traffic-exp")
        
        # === Сценарий 2: Бессрочная, но превышен лимит трафика ===
        user_inf_expire_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400002, "user_inf_expire_overlimit")
        
        pay_order_inf_expire = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_inf_expire_id, offer_id)
        
        sub_inf_expire = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, true, 5120, 10240, 15000, 8000, false)
            RETURNING id
        """, user_inf_expire_id, plan_id, pay_order_inf_expire, 
            "uuid-inf-expire-overlimit", "b64-inf-exp-overlim")
        
        # === Сценарий 3: Полностью безлимитная (НЕ должна деактивироваться) ===
        user_fully_unlimited_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400003, "user_fully_unlimited")
        
        pay_order_unlimited = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_fully_unlimited_id, offer_id)
        
        sub_fully_unlimited = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() - interval '10 days', $4, $5, true, true, 5120, 10240, 99999, 99999, false)
            RETURNING id
        """, user_fully_unlimited_id, plan_id, pay_order_unlimited, 
            "uuid-fully-unlimited", "b64-full-unlim")
        
        # === Сценарий 4: С лимитами, истёк срок (должна деактивироваться) ===
        user_limited_expired_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 400004, "user_limited_expired")
        
        pay_order_limited = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status, 
                infinite_expire, infinite_traffic, 
                traffic_limit_mb, traffic_limit_day_mb, 
                ttl_days, cost
            )
            SELECT $1, 2, 
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers 
            WHERE id = $2
            RETURNING id
        """, user_limited_expired_id, offer_id)
        
        sub_limited_expired = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() - interval '5 days', $4, $5, false, false, 5120, 10240, 5000, 2000, false)
            RETURNING id
        """, user_limited_expired_id, plan_id, pay_order_limited, 
            "uuid-limited-expired", "b64-lim-expired")
        
        return {
            **arq_test_seed,
            # Сценарий 1: Безлимитный трафик, истёк срок
            "user_inf_traffic_id": user_inf_traffic_id,
            "sub_inf_traffic_id": sub_inf_traffic,
            "uuid_inf_traffic": "uuid-inf-traffic-expired",
            # Сценарий 2: Бессрочная, превышен лимит
            "user_inf_expire_id": user_inf_expire_id,
            "sub_inf_expire_id": sub_inf_expire,
            "uuid_inf_expire": "uuid-inf-expire-overlimit",
            # Сценарий 3: Полностью безлимитная
            "user_fully_unlimited_id": user_fully_unlimited_id,
            "sub_fully_unlimited_id": sub_fully_unlimited,
            "uuid_fully_unlimited": "uuid-fully-unlimited",
            # Сценарий 4: С лимитами, истёк срок
            "user_limited_expired_id": user_limited_expired_id,
            "sub_limited_expired_id": sub_limited_expired,
            "uuid_limited_expired": "uuid-limited-expired",
        }


@pytest.fixture
async def tg_routing_seed(db_pool, db_seed, arq_test_seed):
    """
    Создаёт тестовые данные для проверки TG routing эндпоинтов.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из arq_test_seed (ноды, протоколы, планы, офферы).
    Создаёт 2 ОТДЕЛЬНЫХ пользователя для изоляции:
    - user_with_subs: пользователь с активными подписками
    - user_no_subs: пользователь без подписок
    
    Возвращает:
    - user_with_subs: dict с tg_id, user_id, tg_username, sub_count
    - user_no_subs: dict с tg_id, user_id, tg_username
    - plan_id, offer_id: для проверки структуры данных
    """
    async with db_pool.acquire() as conn:
        # Получаем plan_id и offer_id из arq_test_seed
        plan_id = arq_test_seed['plan_id']
        offer_id = arq_test_seed['offer_id']
        
        # === User 1: Пользователь с подписками ===
        user1_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 800001, "tg_user_with_subs")
        
        # Создаём платёж для User 1
        pay_order1 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user1_id, offer_id)
        
        # Создаём подписку для User 1
        user1_sub_id = await conn.fetchval("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id
        """, user1_id, plan_id, pay_order1, "uuid-tg-user-1", "b64-tg-user-1")
        
        # === User 2: Пользователь без подписок ===
        user2_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 800002, "tg_user_no_subs")
        
        return {
            # Пользователь с подписками
            "user_with_subs": {
                "user_id": user1_id,
                "tg_id": 800001,
                "tg_username": "tg_user_with_subs",
                "sub_count": 1,
                "sub_id": user1_sub_id,
            },
            
            # Пользователь без подписок
            "user_no_subs": {
                "user_id": user2_id,
                "tg_id": 800002,
                "tg_username": "tg_user_no_subs",
            },
            
            # Инфраструктура из arq_test_seed
            "plan_id": plan_id,
            "offer_id": offer_id,
        }



@pytest.fixture
async def pointed_bulk_seed(db_pool, db_seed):
    """
    Создаёт данные для тестирования pointed_bulk_action:
    - Пользователи с разными состояниями (активные, удалённые)
    - Виртуальные ноды (активные, неактивные, невидимые)
    - Outbox записи для ADD/DELETE операций
    """
    async with db_pool.acquire() as conn:
        # 1. Создаём план подписки
        plan_id = await conn.fetchval("""
            INSERT INTO sub_plans (title, description, is_active, position)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, "Pointed Bulk Test Plan", "Plan for testing pointed bulk", True, 1)
        
        # Создаём оффер для плана
        offer_id = await conn.fetchval("""
            INSERT INTO sub_plan_offers (
                sub_plan_id, ttl_days, cost,
                traffic_limit_day_mb, traffic_limit_mb,
                infinite_traffic, infinite_expire, is_active, position
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, plan_id, 30, 500, 10240, None, False, False, True, 1)
        
        # 2. Создаём физические ноды
        node_id_active = await conn.fetchval("""
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "192.168.1.100", "10.0.0.100", 8100, "pointed-node-active", "Pointed Active Node", True)
        
        node_id_inactive = await conn.fetchval("""
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "192.168.1.101", "10.0.0.101", 8101, "pointed-node-inactive", "Pointed Inactive Node", False)
        
        # 3. Используем существующий шаблон протокола из seed_data
        tmp_id = await conn.fetchval("""
            SELECT id 
            FROM proto_templates 
            WHERE is_accepted = true 
            ORDER BY id 
            LIMIT 1
        """)
        
        if not tmp_id:
            raise RuntimeError(
                "Не найдено активных шаблонов в proto_templates! "
                "Запустите: python -m web.db.seed_data"
            )
        
        # 4. Используем существующий протокол из seed_data (связанный с tmp_id)
        proto_id = await conn.fetchval("""
            SELECT id 
            FROM protocols 
            WHERE tmp_id = $1 
            ORDER BY id 
            LIMIT 1
        """, tmp_id)
        
        if not proto_id:
            raise RuntimeError(
                f"Не найдено протокола для tmp_id={tmp_id} в protocols! "
                f"Запустите: python -m web.db.seed_data"
            )
        
        # 5. Создаём виртуальные ноды
        # 5.1. Активная виртуальная нода 10
        vnode_id_10 = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "Pointed VNode 10", "vnode10.pointed.com", 9090, "/etc/pointed10.json", True)
        
        # 5.2. Активная виртуальная нода 11
        vnode_id_11 = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "Pointed VNode 11", "vnode11.pointed.com", 9091, "/etc/pointed11.json", True)
        
        # 5.3. Невидимая виртуальная нода (user_visible=false)
        vnode_id_invisible = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "Pointed VNode Invisible", "vnode-invis.pointed.com", 9092, "/etc/pointed-invis.json", False)
        
        # 5.4. Виртуальная нода на неактивной физической ноде
        vnode_id_on_inactive = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_inactive, proto_id, "Pointed VNode On Inactive", "vnode-inactive.pointed.com", 9093, "/etc/pointed-inactive.json", True)
        
        # 6. Связываем подписки с виртуальными нодами
        await conn.execute("""
            INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
            VALUES ($1, $2), ($3, $2), ($4, $2), ($5, $2)
        """, vnode_id_10, plan_id, vnode_id_11, vnode_id_invisible, vnode_id_on_inactive)
        
        # ========== ПОЛЬЗОВАТЕЛИ ==========
        
        # User 3: Живой пользователь для ADD на vnode_10
        user3_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100003, "user3_add_vnode10")
        
        pay_order3 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user3_id, offer_id)
        
        user3_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user3_id, plan_id, pay_order3, "uuid-pointed-user3", "b64-user3-add")
        
        user3_order_active = user3_row['id']
        user3_uuid = user3_row['uuid']
        
        # Создаём outbox запись для ADD на vnode_10
        outbox_user3_add_vnode10 = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 1, $3)
            RETURNING id
        """, user3_uuid, user3_order_active, vnode_id_10)
        
        # User 4: Живой пользователь для DELETE на vnode_10
        user4_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100004, "user4_delete_vnode10")
        
        pay_order4 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user4_id, offer_id)
        
        user4_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user4_id, plan_id, pay_order4, "uuid-pointed-user4", "b64-user4-delete")
        
        user4_order_active = user4_row['id']
        user4_uuid = user4_row['uuid']
        
        # Создаём outbox запись для DELETE на vnode_10
        outbox_user4_delete_vnode10 = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 2, $3)
            RETURNING id
        """, user4_uuid, user4_order_active, vnode_id_10)
        
        # User 5: Живой пользователь для ADD на vnode_11
        user5_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100005, "user5_add_vnode11")
        
        pay_order5 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user5_id, offer_id)
        
        user5_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user5_id, plan_id, pay_order5, "uuid-pointed-user5", "b64-user5-add")
        
        user5_order_active = user5_row['id']
        user5_uuid = user5_row['uuid']
        
        # Создаём outbox запись для ADD на vnode_11
        outbox_user5_add_vnode11 = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 1, $3)
            RETURNING id
        """, user5_uuid, user5_order_active, vnode_id_11)
        
        # User 6: Живой пользователь для DELETE на vnode_11
        user6_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100006, "user6_delete_vnode11")
        
        pay_order6 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user6_id, offer_id)
        
        user6_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user6_id, plan_id, pay_order6, "uuid-pointed-user6", "b64-user6-delete")
        
        user6_order_active = user6_row['id']
        user6_uuid = user6_row['uuid']
        
        # Создаём outbox запись для DELETE на vnode_11
        outbox_user6_delete_vnode11 = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 2, $3)
            RETURNING id
        """, user6_uuid, user6_order_active, vnode_id_11)
        
        # ========== ТЕСТЫ ФИЛЬТРАЦИИ ==========
        
        # User 8: Живой пользователь на НЕАКТИВНОЙ ноде (должен фильтроваться)
        user8_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100008, "user8_inactive_node")
        
        pay_order8 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user8_id, offer_id)
        
        user8_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user8_id, plan_id, pay_order8, "uuid-pointed-user8", "b64-user8-inactive")
        
        user8_order = user8_row['id']
        user8_uuid = user8_row['uuid']
        
        outbox_user8_inactive_node = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 1, $3)
            RETURNING id
        """, user8_uuid, user8_order, vnode_id_on_inactive)
        
        # User 9: Живой пользователь на НЕВИДИМОЙ ноде (должен фильтроваться)
        user9_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 100009, "user9_invisible_node")
        
        pay_order9 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user9_id, offer_id)
        
        user9_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user9_id, plan_id, pay_order9, "uuid-pointed-user9", "b64-user9-invisible")
        
        user9_order = user9_row['id']
        user9_uuid = user9_row['uuid']
        
        outbox_user9_invisible_node = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 1, $3)
            RETURNING id
        """, user9_uuid, user9_order, vnode_id_invisible)
        
        # User 10: УДАЛЁННЫЙ пользователь (is_deleted=true, должен фильтроваться)
        user10_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, true)
            RETURNING id
        """, 100010, "user10_deleted")
        
        pay_order10 = await conn.fetchval("""
            INSERT INTO pay_orders (
                user_id, status,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            )
            SELECT $1, 2,
                infinite_expire, infinite_traffic,
                traffic_limit_mb, traffic_limit_day_mb,
                ttl_days, cost
            FROM sub_plan_offers
            WHERE id = $2
            RETURNING id
        """, user10_id, offer_id)
        
        user10_row = await conn.fetchrow("""
            INSERT INTO user_subs (
                user_id, sub_plan_id, order_id, is_active, expire_date,
                uuid, b64_id, infinite_traffic, infinite_expire,
                traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
            )
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
            RETURNING id, uuid
        """, user10_id, plan_id, pay_order10, "uuid-pointed-user10", "b64-user10-deleted")
        
        user10_order = user10_row['id']
        user10_uuid = user10_row['uuid']
        
        outbox_user10_deleted = await conn.fetchval("""
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            VALUES ($1, $2, 2, $3)
            RETURNING id
        """, user10_uuid, user10_order, vnode_id_10)
        
        return {
            # План и оффер
            "plan_id": plan_id,
            "offer_id": offer_id,
            
            # Виртуальные ноды
            "vnode_id_10": vnode_id_10,
            "vnode_id_11": vnode_id_11,
            "vnode_id_invisible": vnode_id_invisible,
            "vnode_id_on_inactive": vnode_id_on_inactive,
            
            # User 3 (ADD на vnode_10)
            "user3_uuid": user3_uuid,
            "user3_order_active": user3_order_active,
            "outbox_user3_add_vnode10": outbox_user3_add_vnode10,
            
            # User 4 (DELETE на vnode_10)
            "user4_uuid": user4_uuid,
            "user4_order_active": user4_order_active,
            "outbox_user4_delete_vnode10": outbox_user4_delete_vnode10,
            
            # User 5 (ADD на vnode_11)
            "user5_uuid": user5_uuid,
            "user5_order_active": user5_order_active,
            "outbox_user5_add_vnode11": outbox_user5_add_vnode11,
            
            # User 6 (DELETE на vnode_11)
            "user6_uuid": user6_uuid,
            "user6_order_active": user6_order_active,
            "outbox_user6_delete_vnode11": outbox_user6_delete_vnode11,
            
            # User 8 (неактивная нода)
            "outbox_user8_inactive_node": outbox_user8_inactive_node,
            
            # User 9 (невидимая нода)
            "outbox_user9_invisible_node": outbox_user9_invisible_node,
            
            # User 10 (удалённый пользователь)
            "outbox_user10_deleted": outbox_user10_deleted,
        }
