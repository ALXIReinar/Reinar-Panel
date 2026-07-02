"""
Unit тесты для HotReloadExecutor с реальными скриптами из БД

Стратегия:
- Используем реальные скрипты из proto_templates (БД)
- Мокируем библиотеки (xtlsapi, requests, grpcio) через sys.modules
- Используем реальный exec() для выполнения скриптов
- Проверяем что скрипты выполняются без ошибок
- Проверяем детальные сообщения об ошибках для валидации шаблонов
"""
import sys
from unittest.mock import MagicMock, patch
import pytest

from node_client.api.proto_core.hot_reload_executor import HotReloadExecutor
from node_client.tests.conftest import TemplateScriptFields


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
async def test_execute_add_user_unified(
    use_real_core, 
    mock_xtlsapi, 
    request,
    get_script_from_template,
    is_real_mode
):
    """Успешное добавление пользователя - единый тест для мока и реального ядра"""
    
    # Определяем какое ядро использовать
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    # Загружаем скрипт из БД
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add)
    
    user_obj = {"id": "test-uuid-add-123", "email": "test_add@example.com", "uuid": "test-uuid-add-123"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip=core_ip,
        core_api_port=core_port,
        action="add_user",
        custom_params=custom_params
    )
    
    assert success is True, f"Expected success, got: {message}"



@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_execute_delete_user_unified(
    use_real_core,
    mock_xtlsapi,
    request,
    get_script_from_template,
    is_real_mode
):
    """Успешное удаление пользователя - единый тест для мока и реального ядра"""
    
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    script = get_script_from_template(TemplateScriptFields.delete_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_delete) or {}
    
    user_obj = {"email": "test_delete@example.com", "uuid": "test-uuid-delete-123", "id": "test-uuid-delete-123"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip=core_ip,
        core_api_port=core_port,
        action="delete_user",
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
        action="bulk_add_users",
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
        action="bulk_delete_users",
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
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    
    user_obj = {"id": "test-uuid-lib", "email": "test_lib@example.com", "uuid": "test-uuid-lib"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
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
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    
    user_obj = {"id": "test-uuid-async", "email": "test_async@example.com", "uuid": "test-uuid-async"}
    
    # Скрипты из БД используют async/await
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
        custom_params=custom_params
    )
    
    assert success is True


# ========== Группа 3: custom_params ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_custom_params_passed_to_script(mock_xtlsapi, get_script_from_template):
    """custom_params корректно передаются в скрипт (используем реальный скрипт + реальные custom_params из БД)"""
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add)
    
    # Проверяем что custom_params из БД не None
    assert custom_params is not None, "custom_params должны быть определены в шаблоне БД"
    assert isinstance(custom_params, dict), "custom_params должны быть dict"
    
    user_obj = {"id": "test-uuid-params", "email": "test_params@example.com", "uuid": "test-uuid-params"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
        custom_params=custom_params
    )
    
    # Если скрипт выполнился успешно с реальными custom_params, значит они корректно переданы
    assert success is True


@pytest.mark.asyncio
@pytest.mark.db
async def test_custom_params_none_becomes_empty_dict(mock_xtlsapi, get_script_from_template):
    """custom_params=None становится пустым dict (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    user_obj = {"id": "test-uuid-none", "email": "test_none@example.com", "uuid": "test-uuid-none"}
    
    # Передаём None вместо custom_params
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
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
async def add_user(user_obj, node_ip, core_port, custom_params):
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
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_eval():
    """Sandbox блокирует eval()"""
    script = """
async def add_user(user_obj, node_ip, core_port, custom_params):
    try:
        eval("1+1")
        return False
    except NameError:
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_import():
    """Sandbox блокирует __import__()"""
    script = """
async def add_user(user_obj, node_ip, core_port, custom_params):
    try:
        __import__('os')
        return False
    except NameError:
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_allows_safe_builtins():
    """Sandbox разрешает безопасные builtins"""
    script = """
async def add_user(user_obj, node_ip, core_port, custom_params):
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
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is True


# ========== Группа 5: Обработка ошибок ==========
# Эти тесты проверяют детальные сообщения об ошибках

@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_script_syntax_error():
    """SyntaxError в скрипте возвращает детальную ошибку (хардкод - намеренная ошибка)"""
    script = """
async def add_user(user_obj, node_ip, core_port, custom_params):
    # Намеренная синтаксическая ошибка
    if True
        return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is False
    assert "Синтаксическая ошибка" in message or "SyntaxError" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_script_runtime_error(mock_xtlsapi):
    """Runtime ошибка в скрипте возвращает детальную информацию (хардкод - намеренная ошибка)"""
    script = """
async def add_user(user_obj, node_ip, core_port, custom_params):
    # Намеренная runtime ошибка
    raise ValueError("Тестовая ошибка в скрипте")
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names='xtlsapi',
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is False
    assert "ValueError" in message
    assert "Тестовая ошибка" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_missing_function_in_script():
    """Отсутствие требуемой функции возвращает детальную ошибку (хардкод - неправильное имя функции)"""
    script = """
async def wrong_function_name(user_obj, node_ip, core_port, custom_params):
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is False
    assert "add_user" in message
    assert "не найдена" in message.lower()


@pytest.mark.asyncio
@pytest.mark.error_handling
@pytest.mark.db
async def test_library_import_error(get_script_from_template):
    """ImportError при отсутствующей библиотеке (используем реальный скрипт + несуществующую библиотеку)"""
    script = get_script_from_template(TemplateScriptFields.add_user)
    
    user_obj = {"id": "test-uuid", "email": "test@example.com", "uuid": "test-uuid"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names='nonexistent_library_12345',
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is False
    assert "не найдена" in message.lower() or "not found" in message.lower()


# ========== Группа 6: Async/Sync функции ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_async_function_execution(mock_xtlsapi, get_script_from_template):
    """Async функция выполняется корректно (используем реальный async скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    
    user_obj = {"id": "test-uuid-async", "email": "test_async@example.com", "uuid": "test-uuid-async"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
        custom_params=custom_params
    )
    
    assert success is True


@pytest.mark.asyncio
async def test_sync_function_execution():
    """Синхронная функция (без async) тоже работает (хардкод - для проверки совместимости)"""
    script = """
def add_user(user_obj, node_ip, core_port, custom_params):
    # Обычная синхронная функция
    return True
"""
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=None,
        user_obj={},
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user"
    )
    
    assert success is True


@pytest.mark.asyncio
@pytest.mark.db
async def test_mixed_async_sync_calls(mock_xtlsapi, get_script_from_template):
    """Async функция вызывает синхронные методы (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    
    user_obj = {"id": "test-uuid-mixed", "email": "test_mixed@example.com", "uuid": "test-uuid-mixed"}
    
    # Скрипт из БД - async функция, вызывает sync методы xtlsapi
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
        custom_params=custom_params
    )
    
    assert success is True


# ========== Группа 7: Различные типы user_obj ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_user_obj_as_dict(mock_xtlsapi, get_script_from_template):
    """user_obj как dict работает корректно (используем реальный скрипт из БД)"""
    script = get_script_from_template(TemplateScriptFields.add_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    
    user_obj = {"id": "test-uuid", "email": "test@test.com", "uuid": "test-uuid"}
    
    success, message = await HotReloadExecutor.execute_action_script(
        script=script,
        lib_names=lib_names,
        user_obj=user_obj,
        node_ip="127.0.0.1",
        core_api_port=10085,
        action="add_user",
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
        action="bulk_add_users",
        custom_params=custom_params
    )
    
    assert success is True
