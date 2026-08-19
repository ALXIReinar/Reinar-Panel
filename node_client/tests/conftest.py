"""
Конфигурация pytest для тестирования нод-клиента
"""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch
import time

# ВАЖНО: Устанавливаем переменную окружения ДО любых импортов
os.environ['ENV_LOCAL_TEST_FILE'] = os.getenv('ENV_LOCAL_TEST_FILE') or 'node_client/.env.node.test'

from asyncpg import create_pool, Connection
import httpx
import orjson
import pytest
from fastapi import FastAPI
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from node_client.api import main_router
from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer

# Импорты утилит
from node_client.tests.utils.db_helpers import (
    load_templates_by_protocol,  # Новая функция
    load_templates_with_extractors,  # Для тестов шаблонов
    get_all_active_templates
)
from node_client.tests.utils.fake_core import create_mock_subprocess


# ========== Dataclasses ==========

@dataclass
class TemplateScriptFields:
    """
    Поля скриптов из proto_templates
    
    Используется для унифицированного доступа к полям шаблона в тестах.
    Аналогично ExecHistoryStatuses в web модуле.
    """
    bulk_add_users: str = 'api_bulk_add_user_script'
    bulk_delete_users: str = 'api_bulk_delete_user_script'
    get_metrics: str = 'api_metrics_script'
    metrics_parser: str = 'metrics_parser_code'
    lib_names: str = 'proto_python_lib'
    custom_params_bulk_add: str = 'bulk_add_script_custom_params'
    custom_params_bulk_delete: str = 'bulk_delete_script_custom_params'


# ========== Pytest Configuration ==========

def pytest_addoption(parser):
    """Кастомные аргументы для pytest"""
    parser.addoption(
        "--protocol",
        action="store",
        default="xray",
        help=(
            "Фильтр для загрузки шаблонов протоколов из БД. "
            "Поддерживает: "
            "1) Все шаблоны: --protocol=* (загрузит ВСЕ 24 шаблона) "
            "2) Фильтр по ядру: --protocol=xray (20 шаблонов с 'xray') "
            "3) Фильтр по протоколу: --protocol=vless (5 шаблонов с 'vless') "
            "4) Точное имя: --protocol=xray-vless-reality-tcp (1 шаблон) "
            "5) Множественные фильтры: --protocol=xray,shadowsocks (OR условие)"
        )
    )
    parser.addoption(
        "--mode",
        action="store",
        default="mock",
        help="Режим тестирования: mock (моки библиотек) или real (реальные Docker контейнеры с ядрами)"
    )


def pytest_configure(config):
    """Регистрация кастомных маркеров"""
    config.addinivalue_line(
        "markers", "real_core: тесты требующие реального VPN ядра (пропускаются в mock режиме)"
    )
    config.addinivalue_line(
        "markers", "slow: медленные тесты (батчинг, таймауты, асинхронность)"
    )
    config.addinivalue_line(
        "markers", "db: тесты требующие доступа к БД"
    )
    config.addinivalue_line(
        "markers", "vpn_core: параметризованные тесты для конкретных VPN ядер"
    )
    config.addinivalue_line(
        "markers", "security: тесты проверяющие sandbox безопасности"
    )
    config.addinivalue_line(
        "markers", "error_handling: тесты проверяющие обработку ошибок"
    )


def pytest_collection_modifyitems(config, items):
    """
    Фильтрация тестов на основе CLI аргументов
    
    Логика:
    1. --mode=mock → пропускаем тесты с маркером real_core
    2. --protocol используется для фильтрации шаблонов при загрузке (в фикстурах)
    """
    test_mode = config.getoption("--mode")
    
    # 1. Пропускаем real_core тесты в mock режиме
    if test_mode == "mock":
        skip_real = pytest.mark.skip(reason="Пропускаем real_core тесты в mock режиме (используйте --mode=real)")
        for item in items:
            if "real_core" in item.keywords:
                item.add_marker(skip_real)


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database():
    os.environ['PYTHONUTF8'] = '1'
    pg_db = os.getenv('PG_DB')
    assert isinstance(pg_db, str), "PG_DB is not set"
    assert pg_db.startswith("test_"), f"Refusing to run tests against non-test database: {pg_db}"


# ========== Database Fixtures ==========

@pytest.fixture(scope="session")
async def db_pool():
    async def init(conn: Connection):
        await conn.set_type_codec(
            'jsonb',
            encoder=lambda v: orjson.dumps(v).decode('utf-8'),
            decoder=orjson.loads,
            schema='pg_catalog',
        )
        await conn.set_type_codec(
            'json',
            encoder=lambda v: orjson.dumps(v).decode('utf-8'),
            decoder=orjson.loads,
            schema='pg_catalog',
        )

    pool = await create_pool(
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        database=os.getenv("PG_DB"),
        host=os.getenv("PG_HOST"),
        port=int(os.getenv("PG_PORT")),
        init=init,
    )

    yield pool
    await pool.close()


@pytest.fixture(scope="session")
def protocol_name(request):
    """
    Получаем фильтр протокола/ядра из CLI аргумента --protocol
    
    Поддерживает:
    - Одиночный фильтр: --protocol=xray
    - Множественные фильтры: --protocol=xray,shadowsocks
    - Точное совпадение: --protocol=xray-vless-reality-tcp
    
    Returns:
        str: Строка с фильтром(ами), разделёнными запятой
    """
    return request.config.getoption("--protocol")


@pytest.fixture(scope="session")
def test_mode(request):
    """Режим тестирования: mock или real"""
    return request.config.getoption("--mode")


@pytest.fixture
def is_real_mode(test_mode):
    """Проверка что запущен real режим (с реальными ядрами)"""
    return test_mode == "real"


@pytest.fixture
def is_mock_mode(test_mode):
    """Проверка что запущен mock режим"""
    return test_mode == "mock"


# ========== Real Core Fixtures (Docker testcontainers) ==========

@pytest.fixture(scope="function")
def xray_core_container(is_real_mode):
    """
    Поднимает реальный Xray контейнер для E2E тестов
    
    Используется только при --mode=real
    
    Returns:
        tuple[str, int]: (host_ip, api_port) для подключения к Xray API
        
    Raises:
        pytest.skip: Если запущен в mock режиме
    """
    if not is_real_mode:
        pytest.skip("Real core tests require --mode=real")
    
    # Путь к тестовому конфигу Xray
    config_path = Path(__file__).parent / "utils" / "vless-tcp-server-metrics.json"
    
    if not config_path.exists():
        pytest.skip(f"Xray config not found: {config_path}")
    
    # Создаём контейнер с Xray
    container = DockerContainer("teddysun/xray:latest")
    container.with_exposed_ports(10085, 443)  # API port, VLESS port
    container.with_volume_mapping(str(config_path), "/etc/xray/config.json", mode="ro")
    container.with_command("xray run -c /etc/xray/config.json")
    
    # Запускаем контейнер
    container.start()
    
    try:
        # Ждём когда Xray запустится (ищем логи о старте)
        wait_for_logs(container, "started", timeout=10)
        time.sleep(1)  # Дополнительная пауза для инициализации API
        
        # Получаем проброшенный порт API
        api_port = container.get_exposed_port(10085)
        host_ip = container.get_container_host_ip()
        
        yield (host_ip, int(api_port))
        
    finally:
        # Останавливаем контейнер
        container.stop()


@pytest.fixture(scope="session")
async def protocol_templates(db_pool, protocol_name):
    """
    Загружает ВСЕ шаблоны по фильтру --protocol.
    
    Примеры использования в тестах:
    
    # Тест для всех шаблонов
    async def test_all_templates_have_scripts(protocol_templates):
        for template in protocol_templates:
            assert template['api_bulk_add_user_script'], f"{template['title']} missing bulk_add script"
            assert template['api_bulk_delete_user_script'], f"{template['title']} missing bulk_delete script"
    
    # Тест с одним шаблоном (первым)
    async def test_something(protocol_template):  # единственное число!
        assert protocol_template['title']
    
    Примеры запуска:
    - pytest --protocol=xray → загрузит все шаблоны xray
    - pytest --protocol=vless → загрузит все vless шаблоны на любом ядре
    - pytest --protocol=xray-vless → загрузит все xray-vless шаблоны
    
    Returns:
        list[dict]: Список шаблонов со всеми скриптами и метаданными
        
    Raises:
        pytest.skip: Если шаблоны не найдены в БД
    """
    templates = await load_templates_by_protocol(db_pool, protocol_name)

    if not templates:
        # Пробуем показать доступные шаблоны для помощи пользователю
        available = await get_all_active_templates(db_pool)
        available_names = [t['title'] for t in available]
        pytest.skip(
            f"Шаблоны по фильтру '{protocol_name}' не найдены в БД. "
            f"Доступные шаблоны: {available_names}. "
            f"Попробуйте: --protocol={available_names[0] if available_names else 'xray'}"
        )
    
    return templates


@pytest.fixture(scope="session")
async def protocol_templates_with_extractors(db_pool, protocol_name):
    """
    Загружает ВСЕ шаблоны по фильтру --protocol вместе с их extractors.
    
    Расширенная версия protocol_templates, которая также загружает
    связанные extractors из таблицы templates_users_extractors.
    
    Используется в integration тестах для проверки:
    - Наличия и валидности extractors
    - Структуры constant_user_data_obj
    - Выполнения скриптов с реальными данными
    
    Примеры запуска:
    - pytest tests/integration/test_protocol_templates.py --protocol=xray
    - pytest tests/integration/test_protocol_templates.py --protocol=*
    
    Returns:
        list[dict]: Список шаблонов с полем 'extractors' (список extractors)
        
    Raises:
        pytest.skip: Если шаблоны не найдены в БД
    """
    templates = await load_templates_with_extractors(db_pool, protocol_name)

    if not templates:
        # Пробуем показать доступные шаблоны для помощи пользователю
        available = await get_all_active_templates(db_pool)
        available_names = [t['title'] for t in available]
        pytest.skip(
            f"Шаблоны по фильтру '{protocol_name}' не найдены в БД. "
            f"Доступные шаблоны: {available_names}. "
            f"Попробуйте: --protocol={available_names[0] if available_names else 'xray'}"
        )
    
    return templates


# ========== File System Fixtures ==========

@pytest.fixture(scope="session")
def base_config_path():
    """Путь к базовому конфигу vless-tcp-server-metrics.json"""
    return Path(__file__).parent / "utils" / "vless-tcp-server-metrics.json"


@pytest.fixture(scope="session")
def test_configs_dir(tmp_path_factory):
    """
    Временная директория для конфиг-файлов на весь session
    
    Создаётся один раз, удаляется после всех тестов
    """
    temp_dir = tmp_path_factory.mktemp("test_configs")
    yield temp_dir
    # Cleanup происходит автоматически через tmp_path_factory


@pytest.fixture(scope="session")
def working_config_path(test_configs_dir, base_config_path):
    """
    Рабочая копия конфиг-файла для тестов (создаётся один раз на session)
    
    Копируем базовый конфиг в временную директорию.
    Все тесты работают с этой копией.
    """
    working_path = test_configs_dir / "working_config.json"
    shutil.copy(base_config_path, working_path)
    return working_path


@pytest.fixture
def temp_config_path(tmp_path):
    """
    Временный конфиг для одного теста (function scope)
    
    Используется когда тесту нужен изолированный конфиг
    """
    config_path = tmp_path / "test_config.json"
    return config_path


# ========== ConfigWriteBuffer Fixtures ==========

@pytest.fixture
async def fast_buffer(tmp_path):
    """
    ConfigWriteBuffer с быстрым timeout для тестов
    
    timeout=1 сек вместо дефолтных 10 для ускорения тестов
    max_batch=5 для проверки батчинга
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=1.0)
    yield buffer
    await buffer.stop()


@pytest.fixture
async def mock_core_buffer(tmp_path):
    """
    ConfigWriteBuffer с очень быстрым timeout для unit тестов
    
    timeout=0.5 сек для быстрых тестов
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.5)
    yield buffer
    await buffer.stop()


# ========== Mock Fixtures ==========

@pytest.fixture
def mock_subprocess():
    """
    Мок subprocess.run для execute_api
    
    По умолчанию возвращает успешный результат.
    Можно переопределить в конкретном тесте.
    
    Example:
        def test_execute(mock_subprocess):
            mock_subprocess.return_value.stdout = "custom output"
            # ...
    """
    mock = create_mock_subprocess(returncode=0, stdout="Success", stderr="")
    
    with patch('subprocess.run', mock):
        yield mock


@pytest.fixture
def mock_subprocess_timeout():
    """
    Мок subprocess.run который выбрасывает TimeoutExpired
    
    Используется для тестирования таймаутов команд
    """
    mock = create_mock_subprocess(raise_timeout=True)
    
    with patch('subprocess.run', mock):
        yield mock


@pytest.fixture
def mock_hot_reload_success():
    """
    Мок HotReloadExecutor с успешным выполнением скрипта
    
    Возвращает (True, "success message")
    """
    mock = AsyncMock(return_value=(True, "Hot-reload успешно выполнен"))
    
    with patch('node_client.api.sandbox.hot_reload_executor.HotReloadExecutor.execute_action_script', mock):
        yield mock


@pytest.fixture
def mock_hot_reload_failure():
    """
    Мок HotReloadExecutor с провалом скрипта
    
    Возвращает (False, "error message")
    """
    mock = AsyncMock(return_value=(False, "Hot-reload провалился"))
    
    with patch('node_client.api.sandbox.hot_reload_executor.HotReloadExecutor.execute_action_script', mock):
        yield mock


# ========== FastAPI Client Fixtures ==========

@pytest.fixture
async def client(mock_core_buffer):
    """
    FastAPI TestClient без middleware для тестирования API
    
    Middleware (OnlyAdminAccessMiddleware) отключен для тестов,
    чтобы не проверять IP на каждый запрос.
    
    Returns:
        httpx.AsyncClient: Клиент для отправки запросов к API
    """
    app = FastAPI()
    app.include_router(main_router)
    
    # Добавляем core_buffer в state приложения
    app.state.core_buffer = mock_core_buffer
    
    # Middleware НЕ добавляем для тестов (OnlyAdminAccessMiddleware)
    # Это позволяет тестировать API без проверки IP
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app  # Сохраняем ссылку для доступа к app.state
        yield ac


@pytest.fixture
async def client_with_real_buffer(fast_buffer):
    """
    FastAPI TestClient с реальным ConfigWriteBuffer
    
    Используется для интеграционных тестов где нужна
    реальная логика батчинга и таймаутов.
    """
    app = FastAPI()
    app.include_router(main_router)
    app.state.core_buffer = fast_buffer
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        yield ac


# ========== E2E Test Fixtures ==========

@pytest.fixture
async def e2e_buffer(tmp_path):
    """
    ConfigWriteBuffer для E2E тестов с очень быстрым timeout
    
    timeout=0.3 сек для быстрого срабатывания воркера в тестах
    """
    buffer = ConfigWriteBuffer(max_batch=5, timeout=0.3)
    yield buffer
    await buffer.stop()


@pytest.fixture
async def e2e_client(e2e_buffer):
    """
    FastAPI TestClient для E2E тестов с реальным буфером
    
    Используется для полномасштабных E2E тестов пайплайна:
    HTTP → Hot-reload → WBC → Disk → Reload
    """
    app = FastAPI()
    app.include_router(main_router)
    app.state.core_buffer = e2e_buffer
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        yield ac


@pytest.fixture
def e2e_config_path(tmp_path, base_config_path):
    """
    Временный конфиг для E2E теста (изолированный для каждого теста)
    
    Копирует базовый конфиг в уникальную временную директорию
    """
    import shutil
    e2e_config = tmp_path / "e2e_config.json"
    shutil.copy(base_config_path, e2e_config)
    return e2e_config


# ========== Utility Fixtures ==========

@pytest.fixture(autouse=True)
def reset_env_vars():
    """
    Автоматическая фикстура для сброса переменных окружения между тестами
    
    Гарантирует что изменения env не влияют на другие тесты
    """
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)
