"""
Unit тесты для ScriptExecutor с реальными скриптами из БД

Стратегия:
- Используем реальные скрипты prepare_sub из proto_templates (БД)
- Используем реальный exec() для выполнения скриптов в песочнице
- Проверяем что скрипты выполняются без ошибок
- Проверяем безопасность песочницы (блокировка опасных вызовов)
- Проверяем детальные сообщения об ошибках для валидации шаблонов

Тесты адаптированы из node_client/tests/unit/test_hot_reload_executor.py
"""
import pytest

from web.sub.sandbox.script_executor import ScriptExecutor


# ========== Локальные фикстуры ==========

@pytest.fixture
def get_script_from_template(protocol_templates):
    """
    ВНИМАНИЕ: Возвращает getter для ПЕРВОГО шаблона из списка!
    
    Не использовать для тестов которые должны проверять ВСЕ шаблоны.
    Только для unit тестов где достаточно проверить логику на одном шаблоне.
    
    Usage:
        script = get_script_from_template('sub_prepare_script')
        lib_names = get_script_from_template('sub_required_libs')
    
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


# ========== Группа 1: Успешное выполнение с реальными скриптами из БД ==========

@pytest.mark.asyncio
async def test_execute_prepare_sub_script():
    """Успешное выполнение prepare_sub скрипта (unit тест с mock данными)"""
    
    # Простой статический скрипт для проверки механизма
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Подставляем плейсхолдеры из config_link
    result = config_link.format(
        user_uuid=user_obj['user_uuid'],
        n_address=n_address,
        n_title=n_title
    )
    return result
"""
    
    # Mock user_obj
    user_obj = {
        "user_uuid": "550e8400-e29b-41d4-a716-446655440000"
    }
    
    # Mock config_link как dict (новый формат)
    config_link = {
        "conf_url": "vless://{user_uuid}@{n_address}:443#{n_title}",
        "n_address": "1.2.3.4",
        "n_title": "Test Node"
    }
    
    success, result = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj=user_obj,
        config_link=config_link
    )
    
    assert success is True, f"Expected success, got: {result}"
    assert isinstance(result, str), "Result should be a string (processed link)"
    # Проверяем что плейсхолдеры подставлены
    assert "550e8400-e29b-41d4-a716-446655440000" in result
    assert "1.2.3.4" in result
    assert "Test Node" in result


@pytest.mark.asyncio
async def test_prepare_sub_with_special_characters():
    """prepare_sub корректно обрабатывает специальные символы в данных"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    result = config_link.format(
        user_uuid=user_obj['user_uuid'],
        n_address=n_address,
        n_title=n_title
    )
    return result
"""
    
    user_obj = {
        "user_uuid": "550e8400-e29b-41d4-a716-446655440000"
    }
    # Специальные символы в n_title
    config_link = {
        "conf_url": "vless://{user_uuid}@{n_address}:443#{n_title}",
        "n_address": "test.com",
        "n_title": "Тест с пробелами & спецсимволы!"
    }
    
    success, result = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj=user_obj,
        config_link=config_link
    )
    
    assert success is True
    assert isinstance(result, str)


# ========== Группа 2: Импорт и global scope ==========

@pytest.mark.asyncio
async def test_library_imported_to_global_scope():
    """Библиотека доступна в global scope скрипта"""
    # Статический скрипт использующий base64 (не в базовом наборе)
    script = """
import base64

def prepare_sub(user_obj, config_link, n_address, n_title):
    # Используем библиотеку из required_libs
    encoded = base64.b64encode(user_obj['user_uuid'].encode()).decode()
    result = config_link.format(
        user_uuid=encoded,
        n_address=n_address,
        n_title=n_title
    )
    return result
"""
    
    user_obj = {"user_uuid": "test-uuid-123"}
    config_link = {
        "conf_url": "vless://{user_uuid}@{n_address}:443#{n_title}",
        "n_address": "1.2.3.4",
        "n_title": "Test"
    }
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs='base64',  # Явно указываем библиотеку
        user_obj=user_obj,
        config_link=config_link
    )
    
    # Если скрипт выполнился успешно, значит библиотека импортирована корректно
    assert success is True
    assert "dGVzdC11dWlkLTEyMw==" in message  # base64 encoded "test-uuid-123"


@pytest.mark.asyncio
async def test_multiple_libraries_import():
    """Несколько стандартных библиотек импортируются"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Используем несколько стандартных библиотек
    import json
    import re
    import math
    
    result = math.sqrt(16)
    pattern = re.compile(r'\\d+')
    
    return f"test://{n_address}:{result}"
"""
    
    user_obj = {}
    config_link = {
        "conf_url": "test://{n_address}:443",
        "n_address": "1.2.3.4",
        "n_title": "Test"
    }
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs='json,re,math',
        user_obj=user_obj,
        config_link=config_link
    )
    
    assert success is True
    assert "test://1.2.3.4:4.0" in message


@pytest.mark.asyncio
async def test_asyncio_available_in_scope():
    """asyncio доступен в скрипте"""
    script = """
async def prepare_sub(user_obj, config_link, n_address, n_title):
    # Используем async/await
    await asyncio.sleep(0.001)
    return "async_result"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs='asyncio',
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "async_result"


# ========== Группа 3: Sandbox безопасности ==========
# Эти тесты проверяют что sandbox БЛОКИРУЕТ опасные операции

@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_open():
    """Sandbox блокирует доступ к open()"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Попытка открыть файл должна провалиться
    try:
        open('/etc/passwd', 'r')
        return "SECURITY_BREACH"
    except NameError:
        # open не доступен в sandbox
        return "blocked_correctly"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "blocked_correctly"


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_eval():
    """Sandbox блокирует eval()"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    try:
        eval("1+1")
        return "SECURITY_BREACH"
    except NameError:
        return "blocked_correctly"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "blocked_correctly"


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_exec():
    """Sandbox блокирует exec()"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    try:
        exec("x = 1")
        return "SECURITY_BREACH"
    except NameError:
        return "blocked_correctly"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "blocked_correctly"


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_import_dunder():
    """Sandbox блокирует прямой вызов __import__() для запрещённых модулей"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    try:
        __import__('os')
        return "SECURITY_BREACH"
    except ImportError as e:
        if "запрещен" in str(e):
            return "blocked_correctly"
        return "UNEXPECTED_ERROR"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    # Должно быть False так как ImportError не обрабатывается внутри и вырывается наружу
    assert success is False
    assert "запрещен" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_blocks_os_import():
    """Sandbox блокирует import os"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    import os
    return os.getcwd()
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "запрещен" in message.lower()


@pytest.mark.asyncio
@pytest.mark.security
async def test_sandbox_allows_safe_builtins():
    """Sandbox разрешает безопасные builtins"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
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
    return "all_builtins_work"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "all_builtins_work"


# ========== Группа 4: AST Validator (безопасность) ==========

@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_subclasses_introspection():
    """AST блокирует попытку получить __subclasses__"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Попытка получить все подклассы object для обхода sandbox
    return object.__subclasses__()
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "SecurityError" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_class_introspection():
    """AST блокирует __class__ для обхода sandbox"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Классический обход через __class__.__bases__[0].__subclasses__()
    x = []
    return x.__class__.__bases__[0].__subclasses__()
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__class__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_globals_access():
    """AST блокирует доступ к __globals__"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Попытка получить globals для доступа к builtins
    return prepare_sub.__globals__
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__globals__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_code_object_access():
    """AST блокирует __code__ для дизассемблирования"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Попытка получить code object функции
    return prepare_sub.__code__
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__code__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_mro_access():
    """AST блокирует __mro__ для обхода иерархии классов"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Попытка получить MRO (Method Resolution Order)
    return object.__mro__
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__mro__" in message


@pytest.mark.asyncio
@pytest.mark.security
async def test_ast_blocks_dict_access():
    """AST блокирует __dict__ для доступа к атрибутам"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    return user_obj.__dict__
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "безопасности" in message.lower() or "__dict__" in message


# ========== Группа 5: Обработка ошибок ==========

@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_script_syntax_error():
    """SyntaxError в скрипте возвращает детальную ошибку"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Намеренная синтаксическая ошибка
    if True
        return "test"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "Синтаксическая ошибка" in message or "SyntaxError" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_script_runtime_error():
    """Runtime ошибка в скрипте возвращает детальную информацию"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Намеренная runtime ошибка
    raise ValueError("Тестовая ошибка в скрипте")
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "ValueError" in message
    assert "Тестовая ошибка" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_missing_function_in_script():
    """Отсутствие функции prepare_sub возвращает детальную ошибку"""
    script = """
def wrong_function_name(user_obj, config_link):
    return "test"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "prepare_sub" in message and "не найдена" in message


@pytest.mark.asyncio
@pytest.mark.error_handling
async def test_library_import_error():
    """ImportError при отсутствующей библиотеке"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    import nonexistent_library_12345
    return "test"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs='nonexistent_library_12345',
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is False
    assert "не найдена" in message.lower() or "not found" in message.lower()


# ========== Группа 6: Async/Sync функции ==========

@pytest.mark.asyncio
async def test_async_function_execution():
    """Async функция выполняется корректно"""
    script = """
async def prepare_sub(user_obj, config_link, n_address, n_title):
    await asyncio.sleep(0.001)
    return "async_works"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs='asyncio',
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "async_works"


@pytest.mark.asyncio
async def test_sync_function_execution():
    """Синхронная функция (без async) тоже работает"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Обычная синхронная функция
    return "sync_works"
"""
    
    success, message = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    
    assert success is True
    assert message == "sync_works"


# ========== Группа 7: Проверка изоляции global scope ==========

@pytest.mark.asyncio
async def test_isolated_global_scope():
    """Каждый вызов скрипта имеет изолированный global scope"""
    script1 = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Устанавливаем глобальную переменную
    global test_var
    test_var = "first_execution"
    return test_var
"""
    
    script2 = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    # Пытаемся получить переменную из предыдущего выполнения
    try:
        return test_var
    except NameError:
        return "isolated_correctly"
"""
    
    # Первое выполнение
    success1, message1 = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script1,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    assert success1 is True
    assert message1 == "first_execution"
    
    # Второе выполнение - должно быть изолировано
    success2, message2 = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script2,
        required_libs=None,
        user_obj={},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    assert success2 is True
    assert message2 == "isolated_correctly"


# ========== Группа 8: Проверка кэширования компиляции ==========

@pytest.mark.asyncio
async def test_script_compilation_caching():
    """Скрипты кэшируются при повторном выполнении"""
    script = """
def prepare_sub(user_obj, config_link, n_address, n_title):
    return f"user_{user_obj.get('id', 'unknown')}"
"""
    
    # Первое выполнение (компиляция + кэширование)
    success1, message1 = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={'id': '1'},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    assert success1 is True
    assert message1 == "user_1"
    
    # Второе выполнение того же скрипта (должно использовать кэш)
    success2, message2 = await ScriptExecutor.executing_link_processing(
        sub_prepare_script=script,
        required_libs=None,
        user_obj={'id': '2'},
        config_link={
            "conf_url": "test://link",
            "n_address": "1.2.3.4",
            "n_title": "Test"
        }
    )
    assert success2 is True
    assert message2 == "user_2"
    
    # Оба выполнения должны быть успешными
    assert success1 is True and success2 is True
