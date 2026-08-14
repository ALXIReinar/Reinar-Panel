import os

"ВАЖНО: Устанавливаем переменную окружения ДО любых импортов из web/"
os.environ['ENV_LOCAL_TEST_FILE'] = 'web/sub/.env.sub.test'

import asyncpg
import pytest
from aiohttp import ClientResponseError
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
async def sub_infrastructure_seed(db_pool, db_seed):
    """
    Создаёт базовую инфраструктуру для тестов саб-сервиса:
    - 3 тарифных плана с офферами
    - Физические ноды (активные + неактивные)
    - Виртуальные ноды с протоколами
    
    НЕ создаёт пользователей - каждая фикстура создаёт своих для изоляции.
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

        return {
            # Планы подписок
            "plan_id": plan_id,
            "offer_id": offer_id,
            "plan_id_2": plan_id_2,
            "offer_id_2": offer_id_2,
            "plan_id_3": plan_id_3,
            "offer_id_3": offer_id_3,

            # Физические ноды
            "node_id_active": node_id_active,
            "node_id_inactive": node_id_inactive,

            # Протокол и шаблон
            "tmp_id": tmp_id,
            "proto_id": proto_id,

            # Виртуальные ноды
            "vnode_id_10": vnode_id_10,  # Активная, видимая
            "vnode_id_11": vnode_id_11,  # Активная, видимая
            "vnode_id_invisible": vnode_id_invisible,  # Невидимая
            "vnode_id_on_inactive": vnode_id_on_inactive,  # На неактивной физ. ноде
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
            raise RuntimeError(
                "Не найдено парсеров метрик в proto_templates! "
                "Запустите: python -m web.db.seed_data"
            )
        
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
async def sub_api_seed(db_pool, sub_infrastructure_seed):
    """
    Создаёт тестовые данные для проверки GET /sub/{b64_id} эндпоинта.

    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из sub_infrastructure_seed (ноды, протоколы, план).
    Создаёт ОТДЕЛЬНЫХ пользователей с tg_id 600001-600005 для изоляции.

    Критические SQL фильтры в get_sub_links():
    - us.is_active = true (только активные подписки)
    - u.is_deleted = false (только неудалённые пользователи)
    - us.traffic_used_day_mb < us.traffic_limit_day (в пределах лимита)
    - us.expire_date > now() (не истёкшие)
    - np.user_visible = true (только видимые ноды)
    """
    async with db_pool.acquire() as conn:
        # Получаем plan_id из sub_infrastructure_seed
        plan_id = sub_infrastructure_seed['plan_id']
        vnode_id_10 = sub_infrastructure_seed['vnode_id_10']
        vnode_id_11 = sub_infrastructure_seed['vnode_id_11']

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
        """, user_a_id, sub_infrastructure_seed['offer_id'])

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
        """, user_b_id, sub_infrastructure_seed['offer_id'])

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
        """, user_c_id, sub_infrastructure_seed['offer_id'])

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
        """, user_d_id, sub_infrastructure_seed['offer_id'])

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
        """, user_e_id, sub_infrastructure_seed['offer_id'])

        order_e = await conn.fetchval("""
            INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date, uuid, b64_id,
                                   infinite_traffic, infinite_expire, traffic_limit_day, used_mb_limit,
                                   used_mb, traffic_used_day_mb, is_limited)
            VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 100, false)
            RETURNING id
        """, user_e_id, plan_id, pay_order_e, "uuid-sub-user-e", "b64-sub-deleted-e-valid-16chars")

        return {
            # Инфраструктура из sub_infrastructure_seed
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
    from web.sub.config_dir.config import redis_settings
    redis = Redis(**redis_settings)
    await redis.flushdb()
    try:
        yield redis
    finally:
        await redis.aclose()




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
async def payment_seed(db_pool, db_seed, sub_infrastructure_seed):
    """
    Создаёт тестовые данные для проверки платёжных эндпоинтов Robokassa.

    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из sub_infrastructure_seed (ноды, протоколы, план, оффер).
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
        # Получаем plan_id и offer_id из sub_infrastructure_seed
        plan_id = sub_infrastructure_seed['plan_id']
        offer_id = sub_infrastructure_seed['offer_id']
        vnode_id_10 = sub_infrastructure_seed['vnode_id_10']
        vnode_id_11 = sub_infrastructure_seed['vnode_id_11']

        # Создаём отдельного пользователя для платёжных тестов
        user_id = await conn.fetchval("""
            INSERT INTO users (tg_id, tg_username, is_deleted)
            VALUES ($1, $2, false)
            RETURNING id
        """, 700001, "payment_test_user")

        return {
            # Инфраструктура из sub_infrastructure_seed
            "plan_id": plan_id,
            "offer_id": offer_id,
            "vnode_id_10": vnode_id_10,
            "vnode_id_11": vnode_id_11,

            # Пользователь для платёжных тестов
            "user_id": user_id,
            "tg_username": "payment_test_user",
        }


@pytest.fixture
async def tg_routing_seed(db_pool, db_seed, sub_infrastructure_seed):
    """
    Создаёт тестовые данные для проверки TG routing эндпоинтов.
    
    ПЕРЕИСПОЛЬЗУЕТ инфраструктуру из sub_infrastructure_seed (ноды, протоколы, планы, офферы).
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
        plan_id = sub_infrastructure_seed['plan_id']
        offer_id = sub_infrastructure_seed['offer_id']
        
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
            
            # Инфраструктура из sub_infrastructure_seed
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
