import os

"ВАЖНО: Устанавливаем переменную окружения ДО любых импортов из web/"
os.environ['ENV_LOCAL_TEST_FILE'] = 'web/sub/.env.sub.test'

import asyncpg
import pytest
from arq import create_pool as create_arq_pool
from aiohttp import ClientSession, ClientResponseError
from unittest.mock import AsyncMock, MagicMock
from redis.asyncio import Redis

from web.sub.config_dir import config as cfg

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
        # 1. Очищаем все таблицы
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

        await conn.execute("""
            INSERT INTO node_statuses (id, name)
            OVERRIDING SYSTEM VALUE
            VALUES (1, 'active'), (2, 'inactive')
        """)
    
    return {"db_cleaned": True}


# ========== ARQ Fixtures ==========

@pytest.fixture(scope="function")
async def arq_pool():
    """Реальный ARQ pool для тестирования очереди"""
    from web.sub.config_dir.config import get_arq_redis_settings, get_arq_worker_settings
    
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
    
    def raise_for_status(self):
        """Имитация raise_for_status из aiohttp"""
        if self.status >= 400:
            from aiohttp import RequestInfo
            from yarl import URL
            
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
        self.delete_calls = []
        self.get_calls = []

    def post(self, url: str, *args, **kwargs):
        """POST request spy"""
        self.post_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def delete(self, url: str, *args, **kwargs):
        """DELETE request spy"""
        self.delete_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def get(self, url: str, *args, **kwargs):
        """GET request spy"""
        self.get_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            from aiohttp import ClientError
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
    """Создаёт тестовые шаблоны протоколов"""
    async with db_pool.acquire() as conn:
        tmp_id = await conn.fetchval(
            """
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted, 
                reload_core_command, sub_prepare_script,
                proto_python_lib, api_add_user_script, api_delete_user_script,
                flatten_json_users_key, flatten_user_identifier_key,
                add_script_custom_params, delete_script_custom_params,
                required_user_data_obj, constant_user_data_obj
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING id
            """,
            "TestProtocol Template",
            "https://example.com/proto_template",
            1,
            True,
            "systemctl reload test-proto",
            "#!/bin/bash\necho 'test'",
            "vless",
            "python /opt/add_user.py",
            "python /opt/delete_user.py",
            "inbounds.0.settings.clients",
            "email",
            '{}',
            '{}',
            '{"id": "{USER_UUID}", "email": "{USER_TG_USERNAME}"}',  # required_user_data_obj
            '{"level": 0, "alterId": 0}'  # constant_user_data_obj
        )
        
        return {"tmp_id": tmp_id}


@pytest.fixture
async def sub_plan_seed(db_pool):
    """Создаёт тестовые планы подписок"""
    async with db_pool.acquire() as conn:
        plan_id_1 = await conn.fetchval(
            """
            INSERT INTO sub_plans (title, description, ttl_days, cost, traffic_limit_day, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "Basic Plan",
            "Basic subscription plan for testing",
            30,
            500,
            10240,
            True
        )
        
        return {"plan_id_1": plan_id_1}


@pytest.fixture
async def user_seed(db_pool):
    """Создаёт тестовых пользователей"""
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, false)
            RETURNING id
            """,
            123456,
            "test_user",
            "uuid-test-user-0001",
            "test_b64_token"
        )
        
        return {
            "user_id": user_id,
            "uuid": "uuid-test-user-0001",
            "tg_username": "test_user"
        }


@pytest.fixture
async def virtual_node_seed(db_pool, physical_node_seed, proto_template_seed):
    """Создаёт тестовые виртуальные ноды (nodes_protocols)"""
    async with db_pool.acquire() as conn:
        proto_id = await conn.fetchval(
            """
            INSERT INTO protocols (tmp_id, name)
            VALUES ($1, $2)
            RETURNING id
            """,
            proto_template_seed["tmp_id"],
            "Test Protocol"
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
        # 1. Создаём план подписки
        plan_id = await conn.fetchval("""
            INSERT INTO sub_plans (title, description, ttl_days, cost, traffic_limit_day, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "ARQ Test Plan", "Plan for testing", 30, 500, 10240, True)
        
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
        
        # 3. Создаём шаблон протокола
        tmp_id = await conn.fetchval("""
            INSERT INTO proto_templates (
                title, url_tmp, status, is_accepted, 
                reload_core_command, sub_prepare_script,
                proto_python_lib, api_add_user_script, api_delete_user_script,
                api_bulk_add_user_script, api_bulk_delete_user_script,
                flatten_json_users_key, flatten_user_identifier_key,
                add_script_custom_params, delete_script_custom_params,
                bulk_add_script_custom_params, bulk_delete_script_custom_params,
                required_user_data_obj, constant_user_data_obj
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            RETURNING id
        """, "ARQ Test Template", "https://test.com", 1, True,
            "systemctl reload test", "#!/bin/bash", "vless",
            "python add.py", "python del.py",
            "python bulk_add.py", "python bulk_del.py",
            "clients", "email", '{}', '{}', '{}', '{}',
            '{"id": "{USER_UUID}", "email": "{USER_TG_USERNAME}"}',
            '{"level": 0}'
        )
        
        # 4. Создаём протокол
        proto_id = await conn.fetchval("""
            INSERT INTO protocols (tmp_id, name)
            VALUES ($1, $2)
            RETURNING id
        """, tmp_id, "ARQ Test Protocol")
        
        # 5. Создаём виртуальные ноды
        # 5.1. Активная виртуальная нода на активной физической ноде (user_visible=true)
        vnode_id_10 = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "VNode 10 Active", "vnode10.test.com", 9090, "/etc/config.json", True)
        
        # 5.2. Вторая активная виртуальная нода на активной физической ноде
        vnode_id_11 = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "VNode 11 Active", "vnode11.test.com", 9091, "/etc/config.json", True)
        
        # 5.3. Невидимая виртуальная нода на активной физической ноде (user_visible=false)
        vnode_id_invisible = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_active, proto_id, "VNode Invisible", "vnode-invisible.test.com", 9092, "/etc/config.json", False)
        
        # 5.4. Активная виртуальная нода на неактивной физической ноде
        vnode_id_on_inactive = await conn.fetchval("""
            INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, node_id_inactive, proto_id, "VNode On Inactive Node", "vnode-inactive.test.com", 9093, "/etc/config.json", True)
        
        # 6. Связываем подписку ТОЛЬКО с активными видимыми виртуальными нодами
        await conn.execute("""
            INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
            VALUES ($1, $2), ($3, $2), ($4, $2), ($5, $2)
        """, vnode_id_10, plan_id, vnode_id_11, vnode_id_invisible, vnode_id_on_inactive)
        
        # ========== ПОЛЬЗОВАТЕЛИ И ПОДПИСКИ ==========
        
        # User 1: Soft-deleted с неактивными подписками
        user1_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, true)
            RETURNING id
        """, 100001, "deleted_user", "uuid-deleted-user", "b64-deleted")
        
        user1_order1 = await conn.fetchval("""
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
            VALUES ($1, $2, false, 3, now() - interval '10 days')
            RETURNING id
        """, user1_id, plan_id)
        
        user1_order2 = await conn.fetchval("""
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
            VALUES ($1, $2, false, 3, now() - interval '5 days')
            RETURNING id
        """, user1_id, plan_id)
        
        # User 2: Живой без активной подписки (3 неактивных)
        user2_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, false)
            RETURNING id
        """, 100002, "inactive_subs_user", "uuid-inactive-user", "b64-inactive")
        
        user2_orders = []
        for i in range(3):
            order_id = await conn.fetchval("""
                INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
                VALUES ($1, $2, false, 3, now() - interval '1 days' * $3)
                RETURNING id
            """, user2_id, plan_id, (i + 1) * 10)
            user2_orders.append(order_id)
        
        # User 3: Живой с 2 неактивными + 1 активной подпиской (для ADD операции)
        user3_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, false)
            RETURNING id
        """, 100003, "active_add_user", "uuid-active-add-user", "b64-active-add")
        
        user3_order1 = await conn.fetchval("""
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
            VALUES ($1, $2, false, 3, now() - interval '20 days')
            RETURNING id
        """, user3_id, plan_id)
        
        user3_order2 = await conn.fetchval("""
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
            VALUES ($1, $2, false, 3, now() - interval '15 days')
            RETURNING id
        """, user3_id, plan_id)
        
        user3_order_active = await conn.fetchval("""
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
            VALUES ($1, $2, true, 2, now() + interval '30 days')
            RETURNING id
        """, user3_id, plan_id)
        
        # User 4: Живой с 1 активной подпиской (для DELETE операции)
        user4_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
            VALUES ($1, $2, $3, $4, false)
            RETURNING id
        """, 100004, "active_delete_user", "uuid-active-delete-user", "b64-active-delete")
        
        user4_order_active = await conn.fetchval("""
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
            VALUES ($1, $2, true, 2, now() + interval '30 days')
            RETURNING id
        """, user4_id, plan_id)
        
        # ========== OUTBOX ЗАПИСИ ==========
        
        # Для User 3: ADD операции на обе активные ноды
        await conn.execute("""
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            VALUES ($1, $2, $3, 1, $4), ($1, $2, $3, 1, $5)
        """, "uuid-active-add-user", "active_add_user", user3_order_active, vnode_id_10, vnode_id_11)
        
        # Для User 4: DELETE операции на обе активные ноды
        await conn.execute("""
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            VALUES ($1, $2, $3, 2, $4), ($1, $2, $3, 2, $5)
        """, "uuid-active-delete-user", "active_delete_user", user4_order_active, vnode_id_10, vnode_id_11)
        
        return {
            # План подписки
            "plan_id": plan_id,
            
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
                "uuid": "uuid-deleted-user",
                "tg_username": "deleted_user",
                "orders": [user1_order1, user1_order2]
            },
            
            # User 2: Живой без активных подписок
            "user2_inactive_subs": {
                "user_id": user2_id,
                "uuid": "uuid-inactive-user",
                "tg_username": "inactive_subs_user",
                "orders": user2_orders
            },
            
            # User 3: Живой с активной подпиской для ADD
            "user3_active_for_add": {
                "user_id": user3_id,
                "uuid": "uuid-active-add-user",
                "tg_username": "active_add_user",
                "order_inactive_1": user3_order1,
                "order_inactive_2": user3_order2,
                "order_active": user3_order_active
            },
            
            # User 4: Живой с активной подпиской для DELETE
            "user4_active_for_delete": {
                "user_id": user4_id,
                "uuid": "uuid-active-delete-user",
                "tg_username": "active_delete_user",
                "order_active": user4_order_active
            },
        }


@pytest.fixture(autouse=True)
async def flush_redis():
    """
    Очищает Redis перед каждым тестом.
    """
    from web.sub.config_dir.config import redis_settings
    redis = Redis(**redis_settings)
    await redis.flushdb()
    try:
        yield redis
    finally:
        await redis.aclose()
