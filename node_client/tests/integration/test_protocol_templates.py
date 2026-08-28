"""
Интеграционные тесты для валидации шаблонов протоколов из БД

Проверяет что все шаблоны (xray, singbox, и др.):
- Имеют валидную структуру (extractors, constant_user_data_obj)
- Скрипты выполняются без ошибок
- Поддерживают bulk операции (add/delete)
- Корректно обрабатывают custom_params

Тестируются ВСЕ активные шаблоны из БД через параметризацию.

Запуск:
    pytest node_client/tests/integration/test_protocol_templates.py --protocol=* -v
    pytest node_client/tests/integration/test_protocol_templates.py --protocol=xray -v
    pytest node_client/tests/integration/test_protocol_templates.py --protocol=singbox -v
    pytest node_client/tests/integration/test_protocol_templates.py --protocol=xray --mode=real -v
"""
import asyncio
from unittest.mock import patch
import pytest

from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor


# ========== Helper функции ==========

def get_core_type(template_title: str) -> str:
    """
    Извлекает тип ядра из названия шаблона (первое слово до дефиса)
    
    Examples:
        "xray-vless-reality" -> "xray"
        "singbox-vmess-ws" -> "singbox"
    
    Args:
        template_title: Название шаблона из БД
    
    Returns:
        str: Тип ядра (lowercase)
    """
    return template_title.split('-')[0].lower()


def create_test_user_for_template(template: dict, index: int = 0) -> dict:
    """
    Создаёт тестового пользователя на основе required + constant полей шаблона
    
    Объединяет:
    1. required_user_data_obj - системные поля с плейсхолдерами (user_uuid, user_sub_id)
    2. constant_user_data_obj - протокол-специфичные поля (flow, level, и др.)
    3. constant_node_data_obj - node_* поля (эвристически извлекаются из API скрипта)
    
    Заменяет плейсхолдеры {USER_UUID} и {USER_SUB_ID} на реальные значения.
    
    **ВАЖНО**: user_uuid генерируется как настоящий UUID4 (RFC 4122),
    так как некоторые скрипты (например, shadowsocks) парсят его через uuid.UUID().
    
    Args:
        template: Шаблон из БД
        index: Индекс пользователя для уникальности
    
    Returns:
        dict: Суперобъект пользователя готовый для HotReloadExecutor
    
    Example:
        >>> template = {
        ...     'title': 'xray-shadowsocks-tcp',
        ...     'required_user_data_obj': {
        ...         'user_uuid': '{USER_UUID}',
        ...         'user_sub_id': '{USER_SUB_ID}'
        ...     },
        ...     'constant_user_data_obj': {},
        ...     'api_bulk_add_user_script': "password = u['node_method']"
        ... }
        >>> user = create_test_user_for_template(template, index=1)
        >>> assert 'user_uuid' in user
        >>> assert 'node_method' in user  # Автоматически добавлено!
    """
    import uuid as uuid_lib
    from node_client.tests.utils.test_helpers import generate_mock_node_data
    
    # Получаем оба объекта
    required_data = template.get('required_user_data_obj', {}).copy()
    const_data = template.get('constant_user_data_obj', {}).copy()
    
    # Генерируем настоящий UUID4 (RFC 4122 compliant)
    user_uuid = str(uuid_lib.uuid4())
    user_sub_id = f"test_sub_{template['title'][:20]}_{index}"
    
    # Заменяем плейсхолдеры в required_data
    result = {}
    for key, value in required_data.items():
        if value == "{USER_UUID}":
            result[key] = user_uuid
        elif value == "{USER_SUB_ID}":
            result[key] = user_sub_id
        else:
            result[key] = value
    
    # Добавляем constant_data
    result.update(const_data)
    
    # Эвристически извлекаем node_* поля из API скрипта
    api_script = template.get('api_bulk_add_user_script', '')
    if api_script:
        node_data = generate_mock_node_data(api_script)
        # Добавляем только те поля которых ещё нет
        for key, value in node_data.items():
            if key not in result:
                result[key] = value
    
    return result


# ========== Mock классы для библиотек ==========

class MockUniversalCoreClient:
    """
    Универсальный мок для любого VPN ядра (xray, singbox, shadowsocks, и др.)
    
    Имитирует API для добавления/удаления пользователей и получения метрик.
    Хранит "добавленных" пользователей в памяти для проверки в тестах.
    """
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.calls = []
        self.users = {}  # Хранилище "добавленных" пользователей
    
    def add_client(self, **kwargs):
        """Имитация добавления клиента в ядро"""
        # Поддерживаем разные идентификаторы
        user_id = kwargs.get('id') or kwargs.get('uuid') or kwargs.get('email') or kwargs.get('name')
        if user_id:
            self.users[user_id] = kwargs
        self.calls.append(('add_client', kwargs))
        return True
    
    def remove_client(self, **kwargs):
        """Имитация удаления клиента из ядра"""
        user_id = kwargs.get('id') or kwargs.get('uuid') or kwargs.get('email') or kwargs.get('name')
        if user_id and user_id in self.users:
            del self.users[user_id]
        self.calls.append(('remove_client', kwargs))
        return True
    
    def stats_query(self, **kwargs):
        """Имитация получения статистики"""
        self.calls.append(('stats_query', kwargs))
        # Возвращаем фейковую статистику
        return "user>>>test@email>>>uplink: 1024\nuser>>>test@email>>>downlink: 2048"


class MockUniversalCoreModule:
    """Универсальный мок-модуль для любой библиотеки управления ядром"""
    
    XrayClient = MockUniversalCoreClient  # Для xray
    Client = MockUniversalCoreClient      # Для других ядер
    
    class exceptions:
        """Стандартные исключения"""
        EmailAlreadyExists = type('EmailAlreadyExists', (Exception,), {})
        EmailNotFound = type('EmailNotFound', (Exception,), {})
        ClientAlreadyExists = type('ClientAlreadyExists', (Exception,), {})
        ClientNotFound = type('ClientNotFound', (Exception,), {})


# ========== Фикстуры ==========

@pytest.fixture
def mock_universal_core(is_mock_mode):
    """
    Подменяет библиотеки управления ядрами (xtlsapi, singbox-client, и др.) в sys.modules
    
    ВАЖНО: Мок применяется ТОЛЬКО в mock режиме (--mode=mock или по умолчанию).
    В real режиме (--mode=real) библиотеки должны быть установлены реально.
    """
    if not is_mock_mode:
        # Real режим - не подменяем, используем настоящие библиотеки
        yield None
        return
    
    # Mock режим - подменяем библиотеки
    mock_module = MockUniversalCoreModule()
    
    # Подменяем разные возможные названия библиотек
    mock_dict = {
        'xtlsapi': mock_module,
        'singbox_client': mock_module,
        'shadowsocks_client': mock_module,
    }
    
    with patch.dict('sys.modules', mock_dict):
        yield mock_module


# ========== Группа 1: Валидация структуры шаблона ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_template_has_extractors(protocol_templates_with_extractors):
    """
    Проверка: каждый шаблон имеет хотя бы один extractor
    
    Extractor трансформирует суперобъект в объект для конфига ядра.
    Обязательные поля extractor:
    - flatten_array_cursor: путь к массиву пользователей в конфиге
    - extractor_script: Python код для трансформации
    """
    for template in protocol_templates_with_extractors:
        extractors = template.get('extractors', [])
        
        assert len(extractors) > 0, (
            f"Template '{template['title']}' должен иметь хотя бы один extractor. "
            f"Проверьте таблицу templates_users_extractors."
        )
        
        for i, extractor in enumerate(extractors):
            assert extractor.get('flatten_array_cursor') is not None, (
                f"Template '{template['title']}', extractor #{i}: "
                f"flatten_array_cursor не должен быть NULL"
            )
            assert extractor.get('extractor_script') is not None, (
                f"Template '{template['title']}', extractor #{i}: "
                f"extractor_script не должен быть NULL"
            )


@pytest.mark.asyncio
@pytest.mark.db
async def test_template_required_user_data_obj_valid(protocol_templates_with_extractors):
    """
    Проверка: required_user_data_obj содержит обязательные системные поля
    
    Обязательные поля (должны быть в КАЖДОМ шаблоне):
    - user_uuid: "{USER_UUID}" - системный UUID пользователя
    - user_sub_id: "{USER_SUB_ID}" - ID подписки пользователя
    """
    for template in protocol_templates_with_extractors:
        required_data = template.get('required_user_data_obj', {})
        
        assert 'user_uuid' in required_data, (
            f"Template '{template['title']}': "
            f"required_user_data_obj должен содержать поле 'user_uuid'"
        )
        assert 'user_sub_id' in required_data, (
            f"Template '{template['title']}': "
            f"required_user_data_obj должен содержать поле 'user_sub_id'"
        )
        
        # Проверяем что значения - плейсхолдеры
        assert required_data['user_uuid'] == "{USER_UUID}", (
            f"Template '{template['title']}': "
            f"user_uuid должен быть '{{USER_UUID}}', получено: {required_data['user_uuid']}"
        )
        assert required_data['user_sub_id'] == "{USER_SUB_ID}", (
            f"Template '{template['title']}': "
            f"user_sub_id должен быть '{{USER_SUB_ID}}', получено: {required_data['user_sub_id']}"
        )


@pytest.mark.asyncio
@pytest.mark.db
async def test_template_constant_user_data_obj_valid(protocol_templates_with_extractors):
    """
    Проверка: constant_user_data_obj содержит протокол-специфичные поля
    
    constant_user_data_obj хранит константные поля для протокола (flow, level, и др.).
    Это опциональное поле - может быть пустым для некоторых протоколов.
    
    Проверяем что:
    - Если поле присутствует, все значения - базовые типы (str, int, bool, None)
    """
    for template in protocol_templates_with_extractors:
        const_data = template.get('constant_user_data_obj', {})
        
        # constant_user_data_obj может быть пустым - это нормально
        if not const_data:
            continue
        
        # Проверяем что все значения - базовые типы
        for key, value in const_data.items():
            assert isinstance(value, (str, int, bool, type(None))), (
                f"Template '{template['title']}': "
                f"Поле '{key}' в constant_user_data_obj имеет недопустимый тип {type(value)}. "
                f"Разрешены только: str, int, bool, None"
            )


@pytest.mark.asyncio
@pytest.mark.db
async def test_template_has_required_scripts(protocol_templates_with_extractors):
    """
    Проверка: API скрипты присутствуют когда они нужны
    
    Обязательные скрипты (если протокол поддерживает API управление):
    - api_bulk_add_user_script: добавление пользователей
    - api_bulk_delete_user_script: удаление пользователей
    
    ВАЖНО: Некоторые протоколы (hysteria, amneziawg, и др.) управляются только
    через конфиг-файлы и не имеют API скриптов - это нормально.
    
    Этот тест просто подсчитывает шаблоны с/без API скриптов для статистики.
    """
    with_scripts = []
    without_scripts = []
    
    for template in protocol_templates_with_extractors:
        has_add = template.get('api_bulk_add_user_script') is not None
        has_delete = template.get('api_bulk_delete_user_script') is not None
        
        if has_add and has_delete:
            with_scripts.append(template['title'])
        else:
            without_scripts.append(template['title'])
    
    # Информационный вывод
    print(f"\nШаблонов с API скриптами: {len(with_scripts)}")
    print(f"Шаблонов без API скриптов: {len(without_scripts)}")
    
    # Не считаем отсутствие API скриптов ошибкой
    assert len(protocol_templates_with_extractors) > 0, "Шаблоны должны быть загружены из БД"


@pytest.mark.asyncio
@pytest.mark.db
async def test_template_custom_params_optional(protocol_templates_with_extractors):
    """
    Проверка: custom_params - опциональное поле (может быть None или dict)
    
    Если custom_params присутствует, он должен быть dict.
    """
    for template in protocol_templates_with_extractors:
        bulk_add_params = template.get('bulk_add_script_custom_params')
        bulk_delete_params = template.get('bulk_delete_script_custom_params')
        
        # Может быть None - это нормально
        if bulk_add_params is not None:
            assert isinstance(bulk_add_params, dict), (
                f"Template '{template['title']}': "
                f"bulk_add_script_custom_params должен быть dict, получено: {type(bulk_add_params)}"
            )
        
        if bulk_delete_params is not None:
            assert isinstance(bulk_delete_params, dict), (
                f"Template '{template['title']}': "
                f"bulk_delete_script_custom_params должен быть dict, получено: {type(bulk_delete_params)}"
            )


# ========== Группа 2: Выполнение скриптов ==========

@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_template_bulk_add_execution(
    protocol_templates_with_extractors,
    use_real_core,
    request,
    is_real_mode,
    mock_universal_core
):
    """
    Проверка: bulk_add скрипт выполняется без ошибок для каждого шаблона
    
    Mock режим: используются моки библиотек
    Real режим: используются реальные Docker контейнеры с ядрами
    
    ВАЖНО: Проверяются только шаблоны с is_accepted = true И с API скриптами.
    Шаблоны без api_bulk_add_user_script пропускаются (skip).
    """
    for template in protocol_templates_with_extractors:
        # Пропускаем шаблоны без API скриптов
        if not template.get('api_bulk_add_user_script'):
            continue
        
        core_type = get_core_type(template['title'])
        
        if use_real_core:
            if not is_real_mode:
                pytest.skip("Real core tests require --mode=real")
            
            # Получаем реальный контейнер по типу ядра
            if core_type == "xray":
                try:
                    core_ip, core_port = request.getfixturevalue("xray_core_container")
                except Exception as e:
                    pytest.skip(f"Xray container not available: {e}")
            elif core_type == "singbox":
                pytest.skip(f"Sing-box container not implemented yet")
            else:
                pytest.skip(f"No container for core type: {core_type}")
        else:
            # Mock режим
            core_ip, core_port = "127.0.0.1", 10085
        
        # Загружаем скрипт и параметры
        script = template['api_bulk_add_user_script']
        lib_names = template['proto_python_lib']
        custom_params = template.get('bulk_add_script_custom_params') or {}
        
        # Создаём 3 тестовых пользователя
        users_list = [
            create_test_user_for_template(template, index=i)
            for i in range(3)
        ]
        
        # Выполняем скрипт
        success, message = await HotReloadExecutor.execute_action_script(
            script=script,
            lib_names=lib_names,
            user_obj=users_list,
            node_ip=core_ip,
            core_api_port=core_port,
            action="user_core_operation",
            custom_params=custom_params
        )
        
        assert success is True, (
            f"Template '{template['title']}' bulk_add failed:\n"
            f"Message: {message}\n"
            f"Core: {core_type} ({'real' if use_real_core else 'mock'})"
        )


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_template_bulk_delete_execution(
    protocol_templates_with_extractors,
    use_real_core,
    request,
    is_real_mode,
    mock_universal_core
):
    """
    Проверка: bulk_delete скрипт выполняется без ошибок для каждого шаблона
    
    Mock режим: используются моки библиотек
    Real режим: используются реальные Docker контейнеры с ядрами
    
    ВАЖНО: Проверяются только шаблоны с is_accepted = true И с API скриптами.
    Шаблоны без api_bulk_delete_user_script пропускаются (skip).
    """
    for template in protocol_templates_with_extractors:
        # Пропускаем шаблоны без API скриптов
        if not template.get('api_bulk_delete_user_script'):
            continue
        
        core_type = get_core_type(template['title'])
        
        if use_real_core:
            if not is_real_mode:
                pytest.skip("Real core tests require --mode=real")
            
            # Получаем реальный контейнер по типу ядра
            if core_type == "xray":
                try:
                    core_ip, core_port = request.getfixturevalue("xray_core_container")
                except Exception as e:
                    pytest.skip(f"Xray container not available: {e}")
            elif core_type == "singbox":
                pytest.skip(f"Sing-box container not implemented yet")
            else:
                pytest.skip(f"No container for core type: {core_type}")
        else:
            # Mock режим
            core_ip, core_port = "127.0.0.1", 10085
        
        # Загружаем скрипт и параметры
        script = template['api_bulk_delete_user_script']
        lib_names = template['proto_python_lib']
        custom_params = template.get('bulk_delete_script_custom_params') or {}
        
        # Создаём 2 тестовых пользователя для удаления
        users_list = [
            create_test_user_for_template(template, index=i)
            for i in range(2)
        ]
        
        # Выполняем скрипт
        success, message = await HotReloadExecutor.execute_action_script(
            script=script,
            lib_names=lib_names,
            user_obj=users_list,
            node_ip=core_ip,
            core_api_port=core_port,
            action="user_core_operation",
            custom_params=custom_params
        )
        
        assert success is True, (
            f"Template '{template['title']}' bulk_delete failed:\n"
            f"Message: {message}\n"
            f"Core: {core_type} ({'real' if use_real_core else 'mock'})"
        )


# ========== Группа 3: Метрики (сбор и парсинг) ==========

# Примеры данных для тестирования парсеров метрик
SAMPLE_XRAY_METRICS = {
    # Xray CLI возвращает JSON с трафиком нескольких пользователей
    'with_traffic': {
        "stat": [
            {"name": "user>>>1>>>traffic>>>uplink", "value": 1048576},      # 1 MB
            {"name": "user>>>1>>>traffic>>>downlink", "value": 2097152},    # 2 MB
            {"name": "user>>>2>>>traffic>>>uplink", "value": 524288},       # 0.5 MB
            {"name": "user>>>2>>>traffic>>>downlink", "value": 1572864},    # 1.5 MB
            {"name": "user>>>3>>>traffic>>>uplink", "value": 3145728}       # 3 MB
        ]
    },
    
    # Xray CLI возвращает пустой JSON (ядро только запустилось, трафика нет)
    'empty': {
        "stat": []
    },
    
    # Xray CLI возвращает JSON со странными записями (troubles)
    # Только записи без "user>>>" префикса (системные метрики, например)
    'with_troubles': {
        "stat": [
            {"name": "user>>>1>>>traffic>>>uplink", "value": 1048576},
            {"name": "inbound>>>proxy>>>traffic>>>uplink", "value": 999999},  # trouble: нет user>>>
            {"name": "outbound>>>direct>>>traffic>>>downlink", "value": 123},  # trouble: нет user>>>
            {"name": "user>>>2>>>traffic>>>downlink", "value": 2097152}
        ]
    }
}


@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.parametrize("use_real_core", [False], ids=["mock"])
async def test_template_metrics_parsing(
    protocol_templates_with_extractors,
    use_real_core,
    request,
    is_real_mode
):
    """
    Проверка: metrics_parser_code корректно парсит метрики от ядра
    
    Mock режим: используются заготовленные примеры JSON (разные сценарии)
    
    ВАЖНО: Real режим отключён до доработки (protobuf конвертация, Docker настройка)
    
    Проверяемые сценарии (mock):
    1. JSON с трафиком → корректный парсинг в формат users_traffics
    2. Пустой JSON → пустой список пользователей (не ошибка!)
    3. JSON с troubles → проблемные записи в отдельный список
    
    Проверяемые характеристики парсера:
    - Возвращает tuple (users_traffics, troubles)
    - Формат users_traffics: [{'user_sub_id': int, 'total_mb_used': int}, ...]
    - Суммирует uplink + downlink для одного user_sub_id
    - Конвертирует bytes → MB
    - Корректно обрабатывает пустые данные
    
    ВАЖНО: Проверяются только шаблоны с is_accepted = true
    """
    for template in protocol_templates_with_extractors:
        core_type = get_core_type(template['title'])
        
        # Пропускаем не-xray шаблоны (пока фокус только на xray)
        if core_type != "xray":
            continue
        
        parser_code = template.get('metrics_parser_code')
        assert parser_code, f"Template '{template['title']}': metrics_parser_code не может быть пустым"
        
        # Подготавливаем окружение для exec парсера
        import json
        import re
        from collections import defaultdict
        
        # Компилируем парсер
        global_scope = {
            'json': json,
            're': re,
            'defaultdict': defaultdict,
            'int': int,
            'str': str,
            'isinstance': isinstance,
            'len': len
        }
        local_scope = {}
        
        try:
            exec(parser_code, global_scope, local_scope)
        except Exception as e:
            pytest.fail(
                f"Template '{template['title']}': "
                f"Не удалось скомпилировать metrics_parser_code: {e}"
            )
        
        # Извлекаем функцию parse_metrics
        parse_func = local_scope.get('parse_metrics')
        assert callable(parse_func), (
            f"Template '{template['title']}': "
            f"metrics_parser_code должен определять функцию parse_metrics()"
        )
        
        if use_real_core:
            # Real режим: собираем реальные метрики
            if not is_real_mode:
                pytest.skip("Real core tests require --mode=real")
            
            # Получаем реальный контейнер
            if core_type == "xray":
                try:
                    core_ip, core_port = request.getfixturevalue("xray_core_container")
                except Exception as e:
                    pytest.skip(f"Xray container not available: {e}")
            else:
                pytest.skip(f"No container for core type: {core_type}")
            
            # Собираем метрики через скрипт
            metrics_script = template.get('api_metrics_script')
            lib_names = template.get('metrics_parser_libs')
            
            if not metrics_script:
                pytest.skip(f"Template '{template['title']}' has no metrics_script")
            
            success, raw_metrics = await HotReloadExecutor.execute_action_script(
                script=metrics_script,
                lib_names=lib_names,
                node_ip=core_ip,
                core_api_port=core_port,
                action='get_metrics',
                custom_params={}
            )
            
            assert success is True, (
                f"Template '{template['title']}': "
                f"Не удалось собрать метрики через api_metrics_script.\n"
                f"Message: {raw_metrics}\n"
                f"Core: {core_ip}:{core_port}"
            )
            
            # Парсим реальные метрики
            try:
                users_traffics, troubles = parse_func(raw_metrics)
            except Exception as e:
                pytest.fail(
                    f"Template '{template['title']}': "
                    f"Парсер упал на реальных данных: {e}\n"
                    f"Raw metrics: {raw_metrics}"
                )
            
            # Проверяем формат (данные могут быть пустыми - это нормально)
            assert isinstance(users_traffics, list), (
                f"Template '{template['title']}': "
                f"parse() должен возвращать список users_traffics"
            )
            assert isinstance(troubles, list), (
                f"Template '{template['title']}': "
                f"parse() должен возвращать список troubles"
            )
            
        else:
            # Mock режим: тестируем на примерах
            
            # Подготавливаем mock vpn_users и local_state
            mock_vpn_users = {
                'user-uuid-1': {'user_sub_id': 1},
                'user-uuid-2': {'user_sub_id': 2},
                'user-uuid-3': {'user_sub_id': 3},
            }
            mock_local_state = {}
            
            # Тест 1: JSON с трафиком
            users_traffics, troubles = parse_func(
                SAMPLE_XRAY_METRICS['with_traffic'],
                mock_vpn_users,
                mock_local_state
            )
            
            assert isinstance(users_traffics, list), (
                f"Template '{template['title']}': "
                f"parse() должен возвращать список users_traffics"
            )
            assert isinstance(troubles, list), (
                f"Template '{template['title']}': "
                f"parse() должен возвращать список troubles"
            )
            
            # Проверяем что распарсили 3 пользователей
            assert len(users_traffics) == 3, (
                f"Template '{template['title']}': "
                f"Ожидалось 3 пользователя, получено {len(users_traffics)}"
            )
            
            # Проверяем формат каждой записи
            for traffic_record in users_traffics:
                assert 'user_sub_id' in traffic_record, (
                    f"Template '{template['title']}': "
                    f"Запись должна содержать 'user_sub_id'"
                )
                assert 'total_mb_used' in traffic_record, (
                    f"Template '{template['title']}': "
                    f"Запись должна содержать 'total_mb_used'"
                )
                assert isinstance(traffic_record['user_sub_id'], int), (
                    f"Template '{template['title']}': "
                    f"'user_sub_id' должен быть int"
                )
                assert isinstance(traffic_record['total_mb_used'], int), (
                    f"Template '{template['title']}': "
                    f"'total_mb_used' должен быть int (MB)"
                )
            
            # Проверяем суммирование uplink + downlink
            user1_traffic = next((u for u in users_traffics if u['user_sub_id'] == 1), None)
            assert user1_traffic is not None, "Пользователь 1 должен быть в результатах"
            assert user1_traffic['total_mb_used'] == 3, (
                f"Template '{template['title']}': "
                f"Пользователь 1: ожидалось 3 MB (1+2), получено {user1_traffic['total_mb_used']}"
            )
            
            # Тест 2: Пустой JSON (нет трафика)
            users_traffics_empty, troubles_empty = parse_func(
                SAMPLE_XRAY_METRICS['empty'],
                mock_vpn_users,
                mock_local_state
            )
            
            assert isinstance(users_traffics_empty, list), "Парсер должен возвращать список"
            assert len(users_traffics_empty) == 0, (
                f"Template '{template['title']}': "
                f"Для пустого JSON должен возвращаться пустой список"
            )
            
            # Тест 3: JSON с troubles
            users_traffics_troubles, troubles_list = parse_func(
                SAMPLE_XRAY_METRICS['with_troubles'],
                mock_vpn_users,
                mock_local_state
            )
            
            assert isinstance(troubles_list, list), "troubles должен быть списком"
            assert len(troubles_list) > 0, (
                f"Template '{template['title']}': "
                f"Проблемные записи должны попадать в troubles"
            )
            assert len(users_traffics_troubles) == 2, (
                f"Template '{template['title']}': "
                f"Должно быть распарсено 2 валидных пользователя (остальные в troubles)"
            )


@pytest.mark.skip(reason="Real режим отключён: требуется доработка protobuf конвертации и Docker настройки")
@pytest.mark.real_core
@pytest.mark.parametrize("use_real_core", [True], ids=["real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_template_metrics_collection_execution(
    protocol_templates_with_extractors,
    use_real_core,
    request,
    is_real_mode,
    mock_universal_core
):
    """
    Проверка: скрипт api_metrics_script выполняется без ошибок на реальном ядре
    
    ⚠️ ОТКЛЮЧЕНО: требуется доработка
    - Конвертация protobuf → dict/JSON в скрипте метрик
    - Обновление парсеров для работы с protobuf
    - Правильная настройка Docker контейнеров
    
    ВАЖНО: Этот тест проверяет только успешность выполнения скрипта сбора метрик,
    не содержимое. Метрики могут быть пустыми (нет трафика) - это нормально.
    
    Сценарий:
    1. Поднимается реальное VPN ядро (xray_core_container)
    2. Вызывается api_metrics_script через HotReloadExecutor
    3. Проверяется что скрипт выполнился успешно (success=True)
    4. Проверяется что вернулся ответ (может быть пустым JSON)
    5. Проверяется что парсер не падает на реальных данных
    
    Real режим: только с --mode=real (пропускается в mock режиме)
    
    ВАЖНО: Проверяются только шаблоны с is_accepted = true
    """
    if not is_real_mode:
        pytest.skip("Real core tests require --mode=real")
    
    for template in protocol_templates_with_extractors:
        core_type = get_core_type(template['title'])
        
        # Пропускаем не-xray шаблоны (пока фокус только на xray)
        if core_type != "xray":
            continue
        
        # Получаем реальный контейнер
        try:
            core_ip, core_port = request.getfixturevalue("xray_core_container")
        except Exception as e:
            pytest.skip(f"Xray container not available: {e}")
        
        # Проверяем наличие скрипта метрик
        metrics_script = template.get('api_metrics_script')
        if not metrics_script:
            pytest.fail(
                f"Template '{template['title']}': "
                f"api_metrics_script не может быть пустым для is_accepted=true шаблонов"
            )
        
        lib_names = template.get('proto_python_lib')
        
        # Выполняем скрипт сбора метрик
        success, raw_metrics = await HotReloadExecutor.execute_action_script(
            script=metrics_script,
            lib_names=lib_names,
            node_ip=core_ip,
            core_api_port=core_port,
            action='get_metrics',
            custom_params={}
        )
        
        # Проверяем успешность выполнения
        assert success is True, (
            f"Template '{template['title']}': "
            f"Скрипт api_metrics_script должен выполняться без ошибок. "
            f"Raw metrics: {raw_metrics}"
        )
        
        # Проверяем что получили ответ (может быть пустым - это OK)
        assert raw_metrics is not None, (
            f"Template '{template['title']}': "
            f"api_metrics_script должен возвращать ответ (может быть пустой JSON)"
        )
        
        # Проверяем что парсер не падает на реальных данных
        parser_code = template.get('metrics_parser_code')
        assert parser_code, (
            f"Template '{template['title']}': "
            f"metrics_parser_code не может быть пустым"
        )
        
        # Компилируем и выполняем парсер
        import json
        import re
        from collections import defaultdict
        
        global_scope = {
            'json': json,
            're': re,
            'defaultdict': defaultdict,
            'int': int,
            'str': str,
            'isinstance': isinstance,
            'len': len
        }
        local_scope = {}
        
        try:
            exec(parser_code, global_scope, local_scope)
            parse_func = local_scope.get('parse')
            assert callable(parse_func), "metrics_parser_code должен определять функцию parse()"
            
            # Парсим реальные метрики
            users_traffics, troubles = parse_func(raw_metrics)
            
            # Проверяем формат результата (данные могут быть пустыми)
            assert isinstance(users_traffics, list), (
                f"Template '{template['title']}': "
                f"parse() должен возвращать список users_traffics"
            )
            assert isinstance(troubles, list), (
                f"Template '{template['title']}': "
                f"parse() должен возвращать список troubles"
            )
            
        except Exception as e:
            pytest.fail(
                f"Template '{template['title']}': "
                f"Парсер упал на реальных данных: {e}\n"
                f"Raw metrics: {raw_metrics}"
            )
