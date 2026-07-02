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
os.environ['ENV_LOCAL_TEST_FILE'] = 'node_client/.env.node.test'

from asyncpg import create_pool, Pool, Connection
import httpx
import orjson
import pytest
from fastapi import FastAPI
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from node_client.api import main_router
from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer

# Импорты утилит
from node_client.tests.utils.db_helpers import load_template_by_protocol, get_all_active_templates
from node_client.tests.utils.fake_core import create_mock_subprocess


# ========== Dataclasses ==========

@dataclass
class TemplateScriptFields:
    """
    Поля скриптов из proto_templates
    
    Используется для унифицированного доступа к полям шаблона в тестах.
    Аналогично ExecHistoryStatuses в web модуле.
    """
    add_user: str = 'api_add_user_script'
    delete_user: str = 'api_delete_user_script'
    bulk_add_users: str = 'api_bulk_add_user_script'
    bulk_delete_users: str = 'api_bulk_delete_user_script'
    get_metrics: str = 'api_metrics_script'
    metrics_parser: str = 'metrics_parser_code'
    lib_names: str = 'proto_python_lib'
    custom_params_add: str = 'add_script_custom_params'
    custom_params_delete: str = 'delete_script_custom_params'
    custom_params_bulk_add: str = 'bulk_add_script_custom_params'
    custom_params_bulk_delete: str = 'bulk_delete_script_custom_params'


# ========== Pytest Configuration ==========

def pytest_addoption(parser):
    """Кастомные аргументы для pytest"""
    parser.addoption(
        "--protocol",
        action="store",
        default="xray",
        help="Протокол для тестирования: xray, hysteria2, shadowsocks (deprecated, используйте --vpn-core)"
    )
    parser.addoption(
        "--vpn-core",
        action="store",
        default=None,
        help="VPN ядра для тестирования (через запятую): xray,hysteria2,shadowsocks. Пример: --vpn-core=xray,hysteria2"
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
    2. --vpn-core=xray,hysteria2 → запускаем тесты только для указанных ядер
    """
    test_mode = config.getoption("--mode")
    vpn_cores_arg = config.getoption("--vpn-core")
    
    # Парсим список ядер
    if vpn_cores_arg:
        enabled_cores = [core.strip().lower() for core in vpn_cores_arg.split(',')]
    else:
        # Если --vpn-core не указан, используем --protocol (обратная совместимость)
        protocol = config.getoption("--protocol")
        enabled_cores = [protocol.lower()] if protocol else []
    
    # 1. Пропускаем real_core тесты в mock режиме
    if test_mode == "mock":
        skip_real = pytest.mark.skip(reason="Пропускаем real_core тесты в mock режиме (используйте --mode=real)")
        for item in items:
            if "real_core" in item.keywords:
                item.add_marker(skip_real)
    
    # 2. Фильтруем тесты по VPN ядрам
    if enabled_cores:
        for item in items:
            # Проверяем есть ли у теста маркер vpn_core с параметром
            vpn_core_markers = [m for m in item.iter_markers(name="vpn_core")]
            
            if vpn_core_markers:
                # Извлекаем имя ядра из параметризации теста
                test_core = None
                
                # Проверяем callspec (для параметризованных тестов)
                if hasattr(item, 'callspec'):
                    # Ищем параметр который содержит имя протокола
                    for param_name, param_value in item.callspec.params.items():
                        if param_name in ['template', 'protocol_name', 'core_name']:
                            # Извлекаем имя протокола из template dict или напрямую
                            if isinstance(param_value, dict):
                                test_core = param_value.get('title', '').lower()
                            else:
                                test_core = str(param_value).lower()
                            break
                
                # Если нашли ядро и оно не в enabled_cores → пропускаем
                if test_core:
                    # Проверяем частичное совпадение (xray в vless_tcp_sni_based)
                    core_matches = any(enabled_core in test_core for enabled_core in enabled_cores)
                    
                    if not core_matches:
                        skip_msg = f"Пропускаем тест для '{test_core}' (запрошены: {', '.join(enabled_cores)})"
                        item.add_marker(pytest.mark.skip(reason=skip_msg))


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
    """Получаем имя протокола из CLI аргумента --protocol"""
    return request.config.getoption("--protocol")


@pytest.fixture(scope="session")
def test_mode(request):
    """Режим тестирования: mock или real"""
    return request.config.getoption("--mode")


@pytest.fixture(scope="session")
def enabled_vpn_cores(request):
    """
    Список VPN ядер для тестирования
    
    Returns:
        list[str]: Список имён ядер ['xray', 'hysteria2']
    """
    vpn_cores_arg = request.config.getoption("--vpn-core")
    
    if vpn_cores_arg:
        return [core.strip().lower() for core in vpn_cores_arg.split(',')]
    
    # Fallback на --protocol для обратной совместимости
    protocol = request.config.getoption("--protocol")
    return [protocol.lower()] if protocol else []


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
async def cached_protocol_template(db_pool, enabled_vpn_cores):
    """
    Загружается один раз из БД, затем переиспользуется во всех тестах.
    Pytest автоматически кэширует результат благодаря scope="session".
    
    Returns:
        dict: Полный шаблон со всеми скриптами и метаданными
        
    Raises:
        pytest.skip: Если шаблон не найден в БД
    """
    protocol_name = enabled_vpn_cores[0] if enabled_vpn_cores else "xray"
    template = await load_template_by_protocol(db_pool, protocol_name)

    if not template:
        # Пробуем показать доступные шаблоны для помощи пользователю
        available = await get_all_active_templates(db_pool)
        available_names = [t['title'] for t in available]
        pytest.skip(
            f"Шаблон для протокола '{protocol_name}' не найден в БД. "
            f"Доступные шаблоны: {available_names}. "
            f"Используйте --vpn-core={available_names[0].split()[0].lower() if available_names else 'hysteria2'}"
        )
    
    return template


@pytest.fixture
async def protocol_template(cached_protocol_template):
    """
    Возвращает кэшированный шаблон протокола
    
    Обёртка для обратной совместимости с существующими тестами.
    Все тесты используют один кэшированный шаблон.
    
    Returns:
        dict: Полный шаблон со всеми скриптами и метаданными
    """
    return cached_protocol_template



@pytest.fixture
def get_script_from_template(cached_protocol_template):
    """
    Возвращает функцию для получения скрипта/поля из шаблона по имени
    
    Использует TemplateScriptFields для унифицированного доступа к полям.
    
    Returns:
        callable: Функция _get(field_name: str) -> str
        
    Example:
        script = get_script_from_template(TemplateScriptFields.add_user)
        lib_names = get_script_from_template(TemplateScriptFields.lib_names)
        
    Raises:
        pytest.skip: Если поле не найдено в шаблоне
    """
    def _get(field_name: str):
        value = cached_protocol_template.get(field_name)
        if value is None:
            pytest.skip(
                f"Поле '{field_name}' не найдено в шаблоне '{cached_protocol_template.get('title', 'unknown')}'"
            )
        return value
    
    return _get


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
    
    with patch('node_client.api.proto_core.hot_reload_executor.HotReloadExecutor.execute_action_script', mock):
        yield mock


@pytest.fixture
def mock_hot_reload_failure():
    """
    Мок HotReloadExecutor с провалом скрипта
    
    Возвращает (False, "error message")
    """
    mock = AsyncMock(return_value=(False, "Hot-reload провалился"))
    
    with patch('node_client.api.proto_core.hot_reload_executor.HotReloadExecutor.execute_action_script', mock):
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
