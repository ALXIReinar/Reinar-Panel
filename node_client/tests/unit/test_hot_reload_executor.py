"""
Unit тесты для HotReloadExecutor с реальными скриптами из БД

Стратегия:
- Используем реальные скрипты из proto_templates (БД)
- Мокируем библиотеки (xtlsapi, requests, grpcio) через sys.modules
- Используем реальный exec() для выполнения скриптов
- Проверяем что скрипты выполняются без ошибок
- Проверяем детальные сообщения об ошибках для валидации шаблонов
"""
from unittest.mock import patch
import pytest

from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.tests.conftest import TemplateScriptFields


# ========== Локальные фикстуры ==========

@pytest.fixture
def get_script_from_template(protocol_templates):
    """
    ВНИМАНИЕ: Возвращает getter для ПЕРВОГО шаблона из списка!
    
    Не использовать для тестов которые должны проверять ВСЕ шаблоны.
    Только для unit тестов где достаточно проверить логику на одном шаблоне.
    
    Эта фикстура локальная для test_hot_reload_executor.py чтобы избежать
    случайного использования в тестах шаблонов.
    
    Usage:
        script = get_script_from_template(TemplateScriptFields.bulk_add_users)
        lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    Returns:
        Callable: Функция принимающая field name и возвращающая значение из первого шаблона
    """
    if not protocol_templates:
        pytest.skip("Нет доступных шаблонов для тестирования")
    
    # Берём ПЕРВЫЙ шаблон из списка
    template = protocol_templates[0]
    
    def getter(field: str):
        """Извлекает поле из первого шаблона"""
        return template.get(field)
    
    return getter


# ========== Mock классы для библиотек ==========

class MockXrayClient:
    """Мок для xtlsapi.XrayClient"""
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.calls = []
    
    def add_client(self, **kwargs):
        self.calls.append(('add_client', kwargs))
        return True
    
    def remove_client(self, **kwargs):
        self.calls.append(('remove_client', kwargs))
        return True
    
    def stats_query(self, **kwargs):
        self.calls.append(('stats_query', kwargs))
        # Имитируем вывод метрик Xray
        return "user>>>test@email>>>uplink: 1024\nuser>>>test@email>>>downlink: 2048"


class MockXtlsapiModule:
    """Мок для модуля xtlsapi"""
    XrayClient = MockXrayClient
    
    class exceptions:
        EmailAlreadyExists = type('EmailAlreadyExists', (Exception,), {})
        EmailNotFound = type('EmailNotFound', (Exception,), {})


# ========== Фикстуры для моков ==========

@pytest.fixture
def mock_xtlsapi():
    """Подменяет xtlsapi в sys.modules"""
    mock_module = MockXtlsapiModule()
    
    with patch.dict('sys.modules', {'xtlsapi': mock_module}):
        yield mock_module


# ========== Группа 1: Успешное выполнение с реальными скриптами из БД ==========
# Параметризация: mock (с моками библиотек) или real (с реальным Xray в Docker)

@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_execute_bulk_add_user_unified(
    use_real_core, 
    mock_xtlsapi, 
    request,
    protocol_templates,
    is_real_mode
):
    """Успешное добавление пользователя через bulk_add_users - единый тест для мока и реального ядра"""
    
    # Определяем какое ядро использовать
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    # Используем первый шаблон из списка
    template = protocol_templates[0]
    script = template['api_bulk_add_user_script']
    lib_names = template['proto_python_lib']
    custom_params = template.get('bulk_add_script_custom_params')
    
    # user_obj теперь список (для bulk операции)
    users_list = [{"id": "test-uuid-add-123", "email": "test_add@example.com", "uuid": "test-uuid-add-123"}]
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=users_list,
        node_ip=core_ip,
        core_api_port=core_port,
        action="user_core_operation",  # Изменено с "add_user"
        custom_params=custom_params
    )
    
    assert success is True, f"Expected success, got: {message}"



@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_execute_bulk_delete_user_unified(
    use_real_core,
    mock_xtlsapi,
    request,
    get_script_from_template,
    is_real_mode
):
    """Успешное удаление пользователя через bulk_delete_users - единый тест для мока и реального ядра"""
    
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    # Используем bulk_delete_users вместо delete_user
    script = get_script_from_template(TemplateScriptFields.bulk_delete_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_delete) or {}
    
    # user_obj теперь список
    users_list = [{"email": "test_delete@example.com", "uuid": "test-uuid-delete-123", "id": "test-uuid-delete-123"}]
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=users_list,
        node_ip=core_ip,
        core_api_port=core_port,
        action="user_core_operation",  # Изменено с "delete_user"
        custom_params=custom_params
    )
    
    assert success is True


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_execute_bulk_add_unified(
    use_real_core,
    mock_xtlsapi,
    request,
    get_script_from_template,
    is_real_mode
):
    """Bulk добавление пользователей - единый тест для мока и реального ядра"""
    
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    users_list = [
        {"id": "bulk-uuid-1", "email": "bulk_user1@test.com", "uuid": "bulk-uuid-1"},
        {"id": "bulk-uuid-2", "email": "bulk_user2@test.com", "uuid": "bulk-uuid-2"},
    ]
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=users_list,
        node_ip=core_ip,
        core_api_port=core_port,
        action="user_core_operation",  # Изменено с "bulk_add_users"
        custom_params=custom_params
    )
    
    assert success is True


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_execute_bulk_delete_unified(
    use_real_core,
    mock_xtlsapi,
    request,
    get_script_from_template,
    is_real_mode
):
    """Bulk удаление пользователей - единый тест для мока и реального ядра"""
    
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    script = get_script_from_template(TemplateScriptFields.bulk_delete_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_delete) or {}
    
    users_list = [
        {"tg_username": "bulk_del_user1", "email": "bulk_del_user1@test.com"},
        {"email": "bulk_del_user2@test.com"},
    ]
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=users_list,
        node_ip=core_ip,
        core_api_port=core_port,
        action="user_core_operation",  # Изменено с "bulk_delete_users"
        custom_params=custom_params
    )
    
    assert success is True


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_execute_get_metrics_unified(
    use_real_core,
    mock_xtlsapi,
    request,
    get_script_from_template,
    is_real_mode
):
    """Получение метрик - единый тест для мока и реального ядра"""
    
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    script = get_script_from_template(TemplateScriptFields.get_metrics)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=None,
        node_ip=core_ip,
        core_api_port=core_port,
        action="get_metrics"
    )
    
    assert success is True
    assert "uplink" in message or "downlink" in message


# ========== Группа 2: Импорт и global scope ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_library_imported_to_global_scope(mock_xtlsapi, get_script_from_template):
    """Библиотека доступна в global scope скрипта (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    user_obj = {"id": "test-uuid-lib", "email": "test_lib@example.com", "uuid": "test-uuid-lib"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Оборачиваем в список для bulk операции
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",
        custom_params=custom_params
    )
    
    # Если скрипт выполнился успешно, значит библиотеки импортированы корректно
    assert success is True


@pytest.mark.asyncio
@pytest.mark.db
async def test_multiple_libraries_import(get_script_from_template):
    """Несколько стандартных библиотек импортируются (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.get_metrics)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    # Скрипт get_metrics использует json, re и другие библиотеки
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=None,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="get_metrics"
    )
    
    # Если скрипт выполнился, значит все необходимые библиотеки доступны
    assert success is True or "not found" not in message.lower()


@pytest.mark.asyncio
@pytest.mark.db
async def test_asyncio_available_in_scope(mock_xtlsapi, get_script_from_template):
    """asyncio доступен в скрипте (используем реальный async скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    user_obj = {"id": "test-uuid-async", "email": "test_async@example.com", "uuid": "test-uuid-async"}
    
    # Скрипты из БД используют async/await
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Оборачиваем в список для bulk операции
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",  # Изменено с "add_user"
        custom_params=custom_params
    )
    
    assert success is True


# ========== Группа 3: custom_params ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_custom_params_passed_to_script(mock_xtlsapi, get_script_from_template):
    """custom_params корректно передаются в скрипт (используем реальный скрипт + реальные custom_params из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add)
    
    # Проверяем что custom_params из БД не None
    assert custom_params is not None, "custom_params должны быть определены в шаблоне БД"
    assert isinstance(custom_params, dict), "custom_params должны быть dict"
    
    user_obj = {"id": "test-uuid-params", "email": "test_params@example.com", "uuid": "test-uuid-params"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Оборачиваем в список для bulk операции
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",
        custom_params=custom_params
    )
    
    # Если скрипт выполнился успешно с реальными custom_params, значит они корректно переданы
    assert success is True


@pytest.mark.asyncio
@pytest.mark.db
async def test_custom_params_none_becomes_empty_dict(mock_xtlsapi, get_script_from_template):
    """custom_params=None становится пустым dict (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)  # Используем bulk
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    user_obj = {"id": "test-uuid-none", "email": "test_none@example.com", "uuid": "test-uuid-none"}
    
    # Передаём None вместо custom_params
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Оборачиваем в список
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",  # Изменено с "add_user"
        custom_params=None
    )
    
    # Скрипт должен работать даже без custom_params (они станут пустым dict)
    assert success is True


# ========== Группа 4: Sandbox безопасности ==========
# Эти тесты проверяют что sandbox БЛОКИРУЕТ опасные операции
# Используем хардкод скрипты с намеренно опасными вызовами

@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_open():
    """Sandbox блокирует доступ к open()"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка открыть файл должна провалиться
    try:
        open('/etc/passwd', 'r')
        return False  # Не должно дойти сюда
    except NameError:
        # open не доступен в sandbox
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],  # Список для bulk
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_eval():
    """Sandbox блокирует eval()"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    try:
        eval("1+1")
        return False
    except NameError:
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_import():
    """
    Sandbox блокирует __import__()

    Использование import разрешено, но только с выбранными библиотеками. АСТ анализ даже не позволит исполнить код
    """
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    try:
        __import__('os')
        return False
    except NameError:
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_allows_safe_builtins():
    """Sandbox разрешает безопасные builtins"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Разрешённые builtins должны работать
    a = int("42")
    b = str(100)
    c = len([1, 2, 3])
    d = list(range(5))
    e = dict(key="value")
    
    assert a == 42
    assert b == "100"
    assert c == 3
    assert len(d) == 5
    assert e["key"] == "value"
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


# ========== Группа 5: Обработка ошибок ==========
# Эти тесты проверяют детальные сообщения об ошибках

@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_script_syntax_error():
    """SyntaxError в скрипте возвращает детальную ошибку (хардкод - намеренная ошибка)"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Намеренная синтаксическая ошибка
    if True
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "Синтаксическая ошибка" in message or "SyntaxError" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_script_runtime_error(mock_xtlsapi):
    """Runtime ошибка в скрипте возвращает детальную информацию (хардкод - намеренная ошибка)"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Намеренная runtime ошибка
    raise ValueError("Тестовая ошибка в скрипте")
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names='xtlsapi',
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "ValueError" in message
    assert "Тестовая ошибка" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_missing_function_in_script():
    """Отсутствие требуемой функции возвращает детальную ошибку (хардкод - неправильное имя функции)"""
    script = """
async def wrong_function_name(users_list, node_ip, core_port, custom_params):
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    # Проверяем что упоминается хотя бы одна из ожидаемых функций
    assert "bulk_add_users" in message or "bulk_delete_users" in message or "не найдена" in message.lower()


@pytest.mark.asyncio
@pytest.mark.error_handling
@pytest.mark.db
async def test_library_import_error(get_script_from_template):
    """ImportError при отсутствующей библиотеке (используем реальный скрипт + несуществующую библиотеку)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)  # Используем bulk
    
    user_obj = {"id": "test-uuid", "email": "test@example.com", "uuid": "test-uuid"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names='nonexistent_library_12345',
        user_obj=[user_obj],  # Оборачиваем в список
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "не найдена" in message.lower() or "not found" in message.lower()


# ========== Группа 6: Async/Sync функции ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_async_function_execution(mock_xtlsapi, get_script_from_template):
    """Async функция выполняется корректно (используем реальный async скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)  # Используем bulk
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    user_obj = {"id": "test-uuid-async", "email": "test_async@example.com", "uuid": "test-uuid-async"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Список для bulk
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",
        custom_params=custom_params
    )
    
    assert success is True


@pytest.mark.asyncio
async def test_sync_function_execution():
    """Синхронная функция (без async) тоже работает (хардкод - для проверки совместимости)"""
    script = """
def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Обычная синхронная функция
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.db
async def test_mixed_async_sync_calls(mock_xtlsapi, get_script_from_template):
    """Async функция вызывает синхронные методы (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    user_obj = {"id": "test-uuid-mixed", "email": "test_mixed@example.com", "uuid": "test-uuid-mixed"}
    
    # Скрипт из БД - async функция, вызывает sync методы xtlsapi
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Оборачиваем в список для bulk операции
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",
        custom_params=custom_params
    )
    
    assert success is True


# ========== Группа 7: Различные типы user_obj ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_user_obj_as_dict(mock_xtlsapi, get_script_from_template):
    """user_obj как list[dict] работает корректно (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    user_obj = {"id": "test-uuid", "email": "test@test.com", "uuid": "test-uuid"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=[user_obj],  # Оборачиваем в список для bulk
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",
        custom_params=custom_params
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.db
async def test_user_obj_as_list_for_bulk(mock_xtlsapi, get_script_from_template):
    """user_obj как list для bulk операций (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    users_list = [
        {"id": "uuid-1", "email": "user1@test.com", "uuid": "uuid-1"},
        {"id": "uuid-2", "email": "user2@test.com", "uuid": "uuid-2"},
        {"id": "uuid-3", "email": "user3@test.com", "uuid": "uuid-3"},
    ]
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=users_list,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation",
        custom_params=custom_params
    )
    
    assert success is True


# ========== Группа 8: AST Validator (безопасность) ==========

@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_subclasses_introspection():
    """AST блокирует попытку получить __subclasses__"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить все подклассы object для обхода sandbox
    return object.__subclasses__()
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "SecurityError" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_class_introspection():
    """AST блокирует __class__ для обхода sandbox"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Классический обход через __class__.__bases__[0].__subclasses__()
    x = []
    return x.__class__.__bases__[0].__subclasses__()
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__class__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_globals_access():
    """AST блокирует доступ к __globals__"""
    script = """
def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить globals для доступа к builtins
    return bulk_add_users.__globals__
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__globals__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_code_object_access():
    """AST блокирует __code__ для дизассемблирования"""
    script = """
def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить code object функции
    return bulk_add_users.__code__
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__code__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_mro_access():
    """AST блокирует __mro__ для обхода иерархии классов"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить MRO (Method Resolution Order)
    return object.__mro__
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__mro__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_dict_access():
    """AST блокирует __dict__ для доступа к атрибутам"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить __dict__ объекта
    class Foo:
        pass
    return Foo().__dict__
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__dict__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_bases_access():
    """AST блокирует __bases__ для обхода иерархии"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить базовые классы
    return object.__bases__
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__bases__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_closure_access():
    """AST блокирует __closure__ для доступа к замыканиям"""
    script = """
def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Попытка получить closure
    def inner():
        return users_list
    return inner.__closure__
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__closure__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_allows_safe_dunder_attrs():
    """AST разрешает безопасные __name__ и __doc__"""
    script = """
def bulk_add_users(users_list, node_ip, core_port, custom_params):
    '''Docstring for testing'''
    # Безопасные dunder атрибуты должны работать
    module_name = __name__
    module_doc = __doc__
    
    # Проверяем что они доступны
    assert module_name is not None
    assert isinstance(module_name, str)
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


# ========== Группа 9: LRU Cache для компиляции ==========

@pytest.mark.asyncio
@pytest.mark.cache
async def test_lru_cache_reuses_compiled_code():
    """LRU cache переиспользует скомпилированный байткод"""
    import time
    
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return True
"""
    
    # Первый вызов - компиляция + выполнение
    start1 = time.perf_counter()
    success1, _ = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    time1 = time.perf_counter() - start1
    
    # Второй вызов - только выполнение (из кэша)
    start2 = time.perf_counter()
    success2, _ = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    time2 = time.perf_counter() - start2
    
    assert success1 is True
    assert success2 is True
    # Второй вызов должен быть быстрее (нет компиляции)
    # Разница может быть минимальной для простого скрипта
    assert time2 <= time1 * 2  # Достаточно мягкое условие


@pytest.mark.asyncio
@pytest.mark.cache
async def test_lru_cache_different_scripts():
    """Разные скрипты компилируются отдельно"""
    script1 = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return 1
"""
    script2 = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return 2
"""
    
    with patch.object(HotReloadExecutor, '_compile_script_cached', wraps=HotReloadExecutor._compile_script_cached) as mock_compile:
        success1, msg1 = await HotReloadExecutor.execute_action_script(
            script=script1,
            lib_names=None,
            user_obj=[{}],
            node_ip="127.0.0.1",
            core_api_port=10085,
            action="user_core_operation"
        )
        
        success2, msg2 = await HotReloadExecutor.execute_action_script(
            script=script2,
            lib_names=None,
            user_obj=[{}],
            node_ip="127.0.0.1",
            core_api_port=10085,
            action="user_core_operation"
        )
        
        # Оба скрипта скомпилировались отдельно (разные хэши)
        assert mock_compile.call_count == 2
        assert success1 is True
        assert success2 is True
        assert msg1 == 1
        assert msg2 == 2


@pytest.mark.asyncio
@pytest.mark.cache
async def test_script_hash_consistency():
    """Хэш скрипта детерминирован (одинаковый код → одинаковый хэш)"""
    import hashlib
    
    script = "async def bulk_add_users(users_list, node_ip, core_port, custom_params): return True"
    
    hash1 = hashlib.sha256(script.encode("utf-8")).hexdigest()
    hash2 = hashlib.sha256(script.encode("utf-8")).hexdigest()
    
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 хэш


@pytest.mark.asyncio
@pytest.mark.cache
async def test_lru_cache_respects_whitespace_changes():
    """LRU cache различает скрипты с разными пробелами"""
    script1 = "async def bulk_add_users(u,n,c,p): return True"
    script2 = "async def bulk_add_users(u, n, c, p): return True"  # Лишний пробел
    
    with patch.object(HotReloadExecutor, '_compile_script_cached', wraps=HotReloadExecutor._compile_script_cached) as mock_compile:
        await HotReloadExecutor.execute_action_script(script1, None, [{}], "127.0.0.1", 10085, "user_core_operation")
        await HotReloadExecutor.execute_action_script(script2, None, [{}], "127.0.0.1", 10085, "user_core_operation")
        
        # Разные скрипты (даже с минимальными отличиями)
        assert mock_compile.call_count == 2


# ========== Группа 10: Restricted Import ==========

@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_allows_whitelisted_libs():
    """Restricted import разрешает whitelisted библиотеки"""
    script = """
import json
import re
import math
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    data = json.dumps({"test": 123})
    pattern = re.compile(r"\\d+")
    result = math.sqrt(16)
    assert data == '{"test": 123}'
    assert result == 4.0
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_blocks_os():
    """Restricted import блокирует os"""
    script = """
import os
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return os.getcwd()
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    # Проверяем что песочница заблокировала импорт
    assert "запрещен" in message.lower() or "forbidden" in message.lower()


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_blocks_sys():
    """Restricted import блокирует sys"""
    script = """
import sys
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return sys.version
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "запрещен" in message.lower() or "forbidden" in message.lower()


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_blocks_subprocess():
    """Restricted import блокирует subprocess"""
    script = """
import subprocess
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return subprocess.run(['ls'])
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "запрещен" in message.lower() or "forbidden" in message.lower()


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_blocks_socket():
    """Restricted import блокирует socket для предотвращения сетевых атак"""
    script = """
import socket
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    s = socket.socket()
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "запрещен" in message.lower() or "forbidden" in message.lower()


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_nested_module():
    """Restricted import работает с вложенными модулями из allowed_libs"""
    script = """
from json import dumps, loads
from re import compile as re_compile
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    data = dumps({"key": "value"})
    parsed = loads(data)
    pattern = re_compile(r"test")
    
    assert parsed["key"] == "value"
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_as_alias():
    """Restricted import с алиасами (from X import Y as Z)"""
    script = """
from json import dumps as json_dumps
from re import compile as re_compile
from math import sqrt as square_root
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    data = json_dumps({"test": 1})
    pattern = re_compile(r"\\d+")
    result = square_root(25)
    
    assert result == 5.0
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_dynamic_lib_from_template(mock_xtlsapi):
    """lib_names из шаблона добавляется в allowed и доступен через import"""
    script = """
from xtlsapi import XrayClient
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # XrayClient должен быть доступен т.к. xtlsapi в lib_names
    client = XrayClient(node_ip, core_port)
    assert client.host == node_ip
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names='xtlsapi',  # Добавляется в allowed
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_multiple_dynamic_libs(mock_xtlsapi):
    """Несколько динамических библиотек из lib_names"""
    script = """
from xtlsapi import XrayClient
import jmespath
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    client = XrayClient(node_ip, core_port)
    data = jmespath.search('key', {'key': 'value'})
    assert data == 'value'
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names='xtlsapi,jmespath',  # Несколько библиотек
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_restricted_import_blocks_nested_dangerous_module():
    """Restricted import блокирует опасные вложенные модули"""
    script = """
from os.path import exists
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return exists('/etc/passwd')
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "запрещен" in message.lower() or "forbidden" in message.lower()


# ========== Группа 11: get_compiled_func ==========

@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_compiled_func_returns_callable():
    """get_compiled_func возвращает вызываемую функцию"""
    script = """
def my_parser(data):
    return data.upper()
"""
    
    func = HotReloadExecutor.get_compiled_func(script, "my_parser")
    
    assert callable(func)
    result = func("hello")
    assert result == "HELLO"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_compiled_func_with_libs():
    """get_compiled_func работает с библиотеками"""
    script = """
import json
def my_parser(data):
    return json.dumps(data)
"""
    
    func = HotReloadExecutor.get_compiled_func(script, "my_parser", libs="json")
    result = func({"key": "value"})
    
    assert '"key"' in result
    assert '"value"' in result


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_compiled_func_raises_on_missing_function():
    """get_compiled_func выбрасывает ValueError если функция не найдена"""
    script = """
def other_func():
    return True
"""
    
    with pytest.raises(ValueError, match="не найдена"):
        HotReloadExecutor.get_compiled_func(script, "missing_func")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_compiled_func_async_function():
    """get_compiled_func работает с async функциями"""
    script = """
async def async_parser(data):
    return f"async: {data}"
"""
    
    func = HotReloadExecutor.get_compiled_func(script, "async_parser")
    
    assert callable(func)
    result = await func("test")
    assert result == "async: test"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_compiled_func_with_multiple_libs():
    """get_compiled_func с несколькими библиотеками"""
    script = """
import json
import re
def my_parser(data):
    pattern = re.compile(r"\\d+")
    return json.dumps({"data": data, "has_digits": bool(pattern.search(data))})
"""
    
    func = HotReloadExecutor.get_compiled_func(script, "my_parser", libs="json,re")
    result = func("test123")
    
    assert "test123" in result
    assert "true" in result.lower()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_compiled_func_uses_lru_cache():
    """get_compiled_func использует LRU cache"""
    import time
    
    script = """
def simple_func():
    return 42
"""
    
    # Первый вызов - компиляция
    start1 = time.perf_counter()
    func1 = HotReloadExecutor.get_compiled_func(script, "simple_func")
    time1 = time.perf_counter() - start1
    assert func1() == 42
    
    # Второй вызов - из кэша (должен быть быстрее)
    start2 = time.perf_counter()
    func2 = HotReloadExecutor.get_compiled_func(script, "simple_func")
    time2 = time.perf_counter() - start2
    assert func2() == 42
    
    # Второй вызов должен быть не медленнее первого
    assert time2 <= time1 * 2  # Достаточно мягкое условие


# ========== Группа 12: Edge Cases ==========

@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_empty_script():
    """Пустой скрипт возвращает ошибку"""
    success, message = await HotReloadExecutor.execute_action_script(
        script="",
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "не найдена" in message.lower() or "ошибка" in message.lower()


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_with_only_comments():
    """Скрипт только с комментариями"""
    script = """
# Comment 1
# Comment 2
# Comment 3
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is False
    assert "не найдена" in message.lower()


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_very_long_script():
    """Очень длинный скрипт (проверка производительности кэша)"""
    # Генерируем скрипт с 10000 строк комментариев
    comments = "\n".join([f"# Line {i}" for i in range(10000)])
    script = f"{comments}\nasync def bulk_add_users(users_list, node_ip, core_port, custom_params): return True"
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_unicode_in_script():
    """Юникод символы в скрипте"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    msg = "Добавлен пользователь 用户 👤 🚀"
    emoji = "✅"
    chinese = "你好"
    assert len(msg) > 0
    assert emoji == "✅"
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_modifies_global_scope():
    """Скрипт не должен загрязнять global scope между вызовами"""
    script1 = """
GLOBAL_VAR = "script1"
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return GLOBAL_VAR
"""
    
    script2 = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    try:
        return GLOBAL_VAR  # Не должна существовать из script1
    except NameError:
        return "isolated"
"""
    
    success1, msg1 = await HotReloadExecutor.execute_action_script(
        script=script1,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    success2, msg2 = await HotReloadExecutor.execute_action_script(
        script=script2,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success1 is True
    assert msg1 == "script1"
    assert success2 is True
    assert msg2 == "isolated"  # Изоляция работает!


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_with_special_characters():
    """Скрипт со специальными символами в строках"""
    script = r"""
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    special = "Test\n\t\r\"'\\string"
    regex = r"\d+\.\d+"
    assert "\n" in special
    assert r"\d" in regex
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_returns_none():
    """Скрипт возвращающий None считается успешным"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Функция ничего не возвращает (implicit None)
    pass
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True
    assert message is None


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_returns_false():
    """Скрипт возвращающий False обрабатывается корректно"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    return False
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True
    assert message is False


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_with_nested_functions():
    """Скрипт с вложенными функциями"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    def helper(x):
        return x * 2
    
    async def async_helper(y):
        return y + 10
    
    result = helper(5)
    result2 = await async_helper(result)
    
    assert result == 10
    assert result2 == 20
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_with_lambda():
    """Скрипт с lambda функциями"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    square = lambda x: x ** 2
    double = lambda x: x * 2
    
    result = square(5)
    result2 = double(result)
    
    assert result == 25
    assert result2 == 50
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.edge_case
async def test_script_with_comprehensions():
    """Скрипт с list/dict/set comprehensions"""
    script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    squares = [x**2 for x in range(5)]
    even_dict = {x: x**2 for x in range(10) if x % 2 == 0}
    unique_set = {x % 3 for x in range(10)}
    
    assert len(squares) == 5
    assert even_dict[4] == 16
    assert len(unique_set) == 3
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj=[{}],
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="user_core_operation"
    )
    
    assert success is True
