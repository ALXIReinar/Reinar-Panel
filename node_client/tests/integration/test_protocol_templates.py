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

import asyncio  # noqa: F401, I001
import json
from unittest.mock import patch
import pytest

from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.tests.conftest import get_core_container


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
    import uuid as uuid_lib  # noqa: I001
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


# Все вызовы add_client/remove_client моков за тест: клиент создаётся внутри скрипта шаблона, ссылки на него у теста нет
CORE_CALLS: list[tuple[str, dict]] = []


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
        CORE_CALLS.append(('add_client', kwargs))
        return True

    def remove_client(self, **kwargs):
        """Имитация удаления клиента из ядра"""
        user_id = kwargs.get('id') or kwargs.get('uuid') or kwargs.get('email') or kwargs.get('name')
        if user_id and user_id in self.users:
            del self.users[user_id]
        self.calls.append(('remove_client', kwargs))
        CORE_CALLS.append(('remove_client', kwargs))
        return True

    def stats_query(self, **kwargs):
        """Имитация получения статистики"""
        self.calls.append(('stats_query', kwargs))
        # Возвращаем фейковую статистику
        return "user>>>test@email>>>uplink: 1024\nuser>>>test@email>>>downlink: 2048"


class MockUniversalCoreModule:
    """Универсальный мок-модуль для любой библиотеки управления ядром"""

    XrayClient = MockUniversalCoreClient  # Для xray
    Client = MockUniversalCoreClient  # Для других ядер

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
    CORE_CALLS.clear()
    with patch.dict('sys.modules', mock_dict):
        yield mock_module


def wrong_core_calls(method: str, users_list: list[dict]) -> list[str]:
    """
    Проверяет, что скрипт шаблона передал ядру данные пользователей, а не None.

    Скрипт получает пользователей в формате состояния (user_uuid, user_sub_id, константы), а не в формате ядра
    после экстрактора (id, password, email). Ошибка ключа не роняет скрипт: он ловит исключение ядра и пропускает
    пользователя — поэтому одного success=True мало.

    Returns:
        list[str]: описания неверных вызовов; пустой список — всё верно
    """
    sub_ids = {u['user_sub_id'] for u in users_list}
    calls = [kwargs for name, kwargs in CORE_CALLS if name == method]
    problems = (
        [] if len(calls) == len(users_list) else [f"{method}: вызовов {len(calls)}, пользователей {len(users_list)}"]
    )
    for kwargs in calls:
        if kwargs.get('email') not in sub_ids:
            problems.append(f"{method}: email={kwargs.get('email')!r} — не user_sub_id пользователя")
    if method == 'add_client':
        # Идентификатор — сам user_uuid или выведенный из него ключ (shadowsocks-2022): непустой и у каждого свой
        ids = [kwargs.get('user_id_or_password') for kwargs in calls]
        if not all(ids) or len(set(ids)) != len(ids):
            problems.append(f"{method}: user_id_or_password пустой или общий у разных пользователей: {ids!r}")
    return problems


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
                f"Template '{template['title']}', extractor #{i}: flatten_array_cursor не должен быть NULL"
            )
            assert extractor.get('extractor_script') is not None, (
                f"Template '{template['title']}', extractor #{i}: extractor_script не должен быть NULL"
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
            f"Template '{template['title']}': required_user_data_obj должен содержать поле 'user_uuid'"
        )
        assert 'user_sub_id' in required_data, (
            f"Template '{template['title']}': required_user_data_obj должен содержать поле 'user_sub_id'"
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
    protocol_templates_with_extractors, use_real_core, request, is_real_mode, mock_universal_core
):
    """
    Проверка: bulk_add скрипт выполняется без ошибок для каждого шаблона

    Mock режим: используются моки библиотек
    Real режим: используются реальные Docker контейнеры с ядрами

    ВАЖНО: Проверяются только шаблоны с is_accepted = true И с API скриптами.
    Шаблоны без api_bulk_add_user_script пропускаются (skip).
    В mock режиме дополнительно проверяется, что ядру переданы user_uuid и user_sub_id пользователей.
    """
    bad_templates: list[str] = []
    for template in protocol_templates_with_extractors:
        # Пропускаем шаблоны без API скриптов
        if not template.get('api_bulk_add_user_script'):
            continue
        core_type = get_core_type(template['title'])
        if use_real_core:
            if not is_real_mode:
                pytest.skip("Real core tests require --mode=real")
            # Получаем контейнер через универсальную функцию
            core_ip, core_port = get_core_container(template['title'], is_real_mode)
            if not core_ip or not core_port:
                continue
        else:
            # Mock режим
            core_ip, core_port = "127.0.0.1", 10085
        # Загружаем скрипт и параметры
        script = template['api_bulk_add_user_script']
        lib_names = template['proto_python_lib']
        custom_params = template.get('bulk_add_script_custom_params') or {}
        # Создаём 3 тестовых пользователя
        users_list = [create_test_user_for_template(template, index=i) for i in range(3)]
        CORE_CALLS.clear()
        # Выполняем скрипт
        success, message = await HotReloadExecutor.execute_action_script(
            script=script,
            lib_names=lib_names,
            user_obj=users_list,
            node_ip=core_ip,
            core_api_port=core_port,
            action="user_core_operation",
            custom_params=custom_params,
        )
        assert success is True, (
            f"Template '{template['title']}' bulk_add failed:\n"
            f"Message: {message}\n"
            f"Core: {core_type} ({'real' if use_real_core else 'mock'})"
        )
        if not use_real_core:
            for problem in wrong_core_calls('add_client', users_list):
                bad_templates.append(f"{template['title']}: {problem}")
    assert not bad_templates, "Скрипты добавления передают ядру не те ключи:\n" + "\n".join(bad_templates)


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_template_bulk_delete_execution(
    protocol_templates_with_extractors, use_real_core, request, is_real_mode, mock_universal_core
):
    """
    Проверка: bulk_delete скрипт выполняется без ошибок для каждого шаблона

    Mock режим: используются моки библиотек
    Real режим: используются реальные Docker контейнеры с ядрами

    ВАЖНО: Проверяются только шаблоны с is_accepted = true И с API скриптами.
    Шаблоны без api_bulk_delete_user_script пропускаются (skip).
    В mock режиме дополнительно проверяется, что ядру передан user_sub_id пользователей (email в xray).
    """
    bad_templates: list[str] = []
    for template in protocol_templates_with_extractors:
        # Пропускаем шаблоны без API скриптов
        if not template.get('api_bulk_delete_user_script'):
            continue
        core_type = get_core_type(template['title'])
        if use_real_core:
            if not is_real_mode:
                pytest.skip("Real core tests require --mode=real")
            # Получаем контейнер через универсальную функцию
            core_ip, core_port = get_core_container(template['title'], is_real_mode)
            if not core_ip or not core_port:
                continue
        else:
            # Mock режим
            core_ip, core_port = "127.0.0.1", 10085
        # Загружаем скрипт и параметры
        script = template['api_bulk_delete_user_script']
        lib_names = template['proto_python_lib']
        custom_params = template.get('bulk_delete_script_custom_params') or {}
        # Создаём 2 тестовых пользователя для удаления
        users_list = [create_test_user_for_template(template, index=i) for i in range(2)]
        CORE_CALLS.clear()
        # Выполняем скрипт
        success, message = await HotReloadExecutor.execute_action_script(
            script=script,
            lib_names=lib_names,
            user_obj=users_list,
            node_ip=core_ip,
            core_api_port=core_port,
            action="user_core_operation",
            custom_params=custom_params,
        )
        assert success is True, (
            f"Template '{template['title']}' bulk_delete failed:\n"
            f"Message: {message}\n"
            f"Core: {core_type} ({'real' if use_real_core else 'mock'})"
        )
        if not use_real_core:
            for problem in wrong_core_calls('remove_client', users_list):
                bad_templates.append(f"{template['title']}: {problem}")
    assert not bad_templates, "Скрипты удаления передают ядру не те ключи:\n" + "\n".join(bad_templates)


# ========== Группа 3: Метрики (сбор и парсинг) ==========

# Примеры данных для тестирования парсеров метрик
# Каждое ядро имеет свой формат метрик

# === XRAY / SINGBOX ===
# Xray/Singbox используют единый JSON формат через gRPC API
SAMPLE_XRAY_METRICS = {
    # Xray CLI возвращает JSON с трафиком нескольких пользователей
    'with_traffic': {
        "stat": [
            {"name": "user>>>1>>>traffic>>>uplink", "value": 1048576},  # 1 MB
            {"name": "user>>>1>>>traffic>>>downlink", "value": 2097152},  # 2 MB
            {"name": "user>>>2>>>traffic>>>uplink", "value": 524288},  # 0.5 MB
            {"name": "user>>>2>>>traffic>>>downlink", "value": 1572864},  # 1.5 MB
            {"name": "user>>>3>>>traffic>>>uplink", "value": 3145728},  # 3 MB
        ]
    },
    # Xray CLI возвращает пустой JSON (ядро только запустилось, трафика нет)
    'empty': {"stat": []},
    # Xray CLI возвращает JSON со странными записями (troubles)
    # Только записи без "user>>>" префикса (системные метрики, например)
    'with_troubles': {
        "stat": [
            {"name": "user>>>1>>>traffic>>>uplink", "value": 1048576},
            {"name": "inbound>>>proxy>>>traffic>>>uplink", "value": 999999},  # trouble: нет user>>>
            {"name": "outbound>>>direct>>>traffic>>>downlink", "value": 123},  # trouble: нет user>>>
            {"name": "user>>>2>>>traffic>>>downlink", "value": 2097152},
        ]
    },
}

# === AMNEZIAWG ===
# AWG использует табличный вывод CLI команды `awg show awg0 dump`
# Формат: pub_key \t psk \t endpoint \t allowed_ips \t handshake \t rx \t tx \t keepalive
SAMPLE_AWG_METRICS = {
    # AWG dump с трафиком 3х пользователей (IPv6 адреса fd00:1::1, fd00:1::2, fd00:1::3)
    'with_traffic': (
        "pub_key\tpsk\tendpoint\tallowed_ips\tlast_handshake\trx_bytes\ttx_bytes\tkeepalive\n"
        "key1abc\t(none)\t1.2.3.4:51820\tfd00:1::1/128\t1234567890\t1048576\t2097152\t25\n"  # user 1: rx=1MB, tx=2MB
        "key2def\t(none)\t5.6.7.8:51820\tfd00:1::2/128\t1234567891\t524288\t1572864\t25\n"  # user 2: rx=0.5MB, tx=1.5MB
        "key3ghi\t(none)\t9.10.11.12:51820\tfd00:1::3/128\t1234567892\t3145728\t0\t25\n"  # user 3: rx=3MB, tx=0
    ),
    # Пустой dump (только заголовок, пиров нет)
    'empty': "pub_key\tpsk\tendpoint\tallowed_ips\tlast_handshake\trx_bytes\ttx_bytes\tkeepalive\n",
    # Dump с неизвестным IP (trouble - пользователь не в vpn_users)
    'with_troubles': (
        "pub_key\tpsk\tendpoint\tallowed_ips\tlast_handshake\trx_bytes\ttx_bytes\tkeepalive\n"
        "key1abc\t(none)\t1.2.3.4:51820\tfd00:1::1/128\t1234567890\t1048576\t2097152\t25\n"  # OK
        "key_unk\t(none)\t99.99.99.99:51820\tfd00:1::999/128\t1234567893\t999999\t999999\t25\n"  # trouble: unknown IP
        "key2def\t(none)\t5.6.7.8:51820\tfd00:1::2/128\t1234567891\t524288\t1572864\t25\n"  # OK
    ),
}

# === HYSTERIA ===
# Hysteria использует HTTP API endpoint /traffic с JSON форматом
# Формат: {"user_sub_id_str": {"tx": bytes, "rx": bytes}}
SAMPLE_HYSTERIA_METRICS = {
    # HTTP ответ с трафиком 3х пользователей
    'with_traffic': {
        "1": {"tx": 2097152, "rx": 1048576},  # user 1: tx=2MB, rx=1MB
        "2": {"tx": 1572864, "rx": 524288},  # user 2: tx=1.5MB, rx=0.5MB
        "3": {"tx": 0, "rx": 3145728},  # user 3: tx=0, rx=3MB
    },
    # Пустой HTTP ответ (нет активных пользователей)
    'empty': {},
    # Hysteria не имеет troubles - если user_sub_id есть в ответе, значит он валиден
    # (сервер сам контролирует кого отдавать)
    'with_troubles': {"1": {"tx": 1048576, "rx": 1048576}, "2": {"tx": 2097152, "rx": 0}},
}


def get_sample_metrics_for_core(core_type: str) -> dict:
    """
    Возвращает mock метрики для указанного типа ядра

    Args:
        core_type: Тип ядра ('xray', 'singbox', 'amneziawg', 'hysteria')

    Returns:
        dict: Словарь с ключами 'with_traffic', 'empty', 'with_troubles'
    """
    if core_type in ['xray', 'singbox']:
        return SAMPLE_XRAY_METRICS
    elif core_type == 'amneziawg':
        return SAMPLE_AWG_METRICS
    elif core_type == 'hysteria':
        return SAMPLE_HYSTERIA_METRICS
    else:
        # Fallback на xray формат для неизвестных ядер
        return SAMPLE_XRAY_METRICS


def prepare_mock_vpn_users_for_core(core_type: str) -> dict:
    """
    Создаёт mock vpn_users с учётом специфики ядра

    AWG требует node_ipv6_subnet для расчёта IP адресов
    Парсеры ядер итерируют по vpn_users как по списку (не по dict!)

    Args:
        core_type: Тип ядра

    Returns:
        list: Mock vpn_users объект (список пользователей)
    """
    if core_type == 'amneziawg':
        # AWG парсер требует node_ipv6_subnet для вычисления IP
        # ВАЖНО: используем одну подсеть для всех пользователей (как в реальности)
        return [
            {'user_sub_id': 1, 'node_ipv6_subnet': 'fd00:1::/64'},
            {'user_sub_id': 2, 'node_ipv6_subnet': 'fd00:1::/64'},
            {'user_sub_id': 3, 'node_ipv6_subnet': 'fd00:1::/64'},
        ]
    # Базовый набор для xray/singbox/hysteria (не требуют vpn_users, только для troubles)
    return []


@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.parametrize("use_real_core", [False], ids=["mock"])
async def test_template_metrics_parsing(protocol_templates_with_extractors, use_real_core, request, is_real_mode):
    """
    Проверка: metrics_parser_code корректно парсит метрики от ядра

    Mock режим: используются заготовленные примеры JSON (разные сценарии)

    ВАЖНО: Real режим отключён до доработки (protobuf конвертация, Docker настройка)

    Проверяемые сценарии (mock):
    1. JSON с трафиком → корректный парсинг в формат users_traffics
    2. Пустой JSON → пустой список пользователей (не ошибка!)
    3. JSON с troubles → проблемные записи в отдельный список

    Проверяемые характеристики парсера:
    - Возвращает корректный результат через HotReloadExecutor
    - Формат users_traffics: [{'user_sub_id': int, 'total_mb_used': int}, ...]
    - Суммирует uplink + downlink для одного user_sub_id
    - Конвертирует bytes → MB
    - Корректно обрабатывает пустые данные

    ВАЖНО: Проверяются только шаблоны с is_accepted = true
    """
    for template in protocol_templates_with_extractors:
        core_type = get_core_type(template['title'])
        parser_code = template.get('metrics_parser_code')
        if not parser_code:
            # Пропускаем шаблоны без парсера метрик
            continue
        if use_real_core:
            # Real режим: собираем реальные метрики
            if not is_real_mode:
                pytest.skip("Real core tests require --mode=real")
            # Получаем контейнер через универсальную функцию
            core_ip, core_port = get_core_container(template['title'], is_real_mode)
            if not core_ip or not core_port:
                continue
            # Собираем метрики (API скрипт ИЛИ CLI команда)
            metrics_script = template.get('api_metrics_script')
            # Библиотеки всех скриптов шаблона — в proto_python_lib (metrics_parser_libs уходит, требование 11)
            lib_names = template.get('proto_python_lib')
            # Если есть API скрипт - используем его
            if metrics_script:
                success, raw_metrics = await HotReloadExecutor.execute_action_script(
                    script=metrics_script,
                    lib_names=lib_names,
                    node_ip=core_ip,
                    core_api_port=core_port,
                    action='get_metrics',
                    custom_params={},
                )
                assert success is True, (
                    f"Template '{template['title']}': "
                    f"Не удалось собрать метрики через api_metrics_script.\n"
                    f"Message: {raw_metrics}\n"
                    f"Core: {core_ip}:{core_port}"
                )
            else:
                # Без API скрипта используем mock данные (имитация stdout CLI команды)
                core_type = get_core_type(template['title'])
                sample_metrics = get_sample_metrics_for_core(core_type)
                raw_metrics = sample_metrics['with_traffic']
            # Парсим реальные метрики через HotReloadExecutor
            success, traffic_pack = await HotReloadExecutor.execute_action_script(
                script=parser_code,
                lib_names=lib_names,
                node_ip='0',  # Затычка для обязательных аргументов
                core_api_port=0,  # Затычка для обязательных аргументов
                action='parse_metrics',
                custom_params={
                    "raw_metrics": raw_metrics,
                    "vpn_users": {},  # Пустой словарь для тестов
                    "local_state": {},  # Пустой словарь для тестов
                },
            )
            assert success is True, (
                f"Template '{template['title']}': "
                f"Парсер упал на реальных данных: {traffic_pack}\n"
                f"Raw metrics: {raw_metrics}"
            )
            # Проверяем формат (данные могут быть пустыми - это нормально)
            assert isinstance(traffic_pack, list), (
                f"Template '{template['title']}': parse_metrics должен возвращать список traffic_pack"
            )
        else:
            # Mock режим: тестируем на примерах
            # Определяем тип ядра для выбора правильного формата метрик
            core_type = get_core_type(template['title'])
            # Получаем mock данные для этого ядра
            sample_metrics = get_sample_metrics_for_core(core_type)
            mock_vpn_users = prepare_mock_vpn_users_for_core(core_type)
            mock_local_state = {}
            # Библиотеки всех скриптов шаблона — в proto_python_lib (metrics_parser_libs уходит, требование 11)
            lib_names = template.get('proto_python_lib')
            # DEBUG: покажем какой шаблон тестируется и его библиотеки
            print(f"\n>>> Testing metrics parser for template: {template['title']} (core: {core_type})")
            print(f"    lib_names from DB: {repr(lib_names)}")
            # Тест 1: Данные с трафиком
            # Подготавливаем raw_metrics в зависимости от формата ядра
            raw_metrics_data = sample_metrics['with_traffic']
            if core_type in ['xray', 'singbox', 'hysteria']:
                # JSON формат - нужно serialize
                raw_metrics_str = json.dumps(raw_metrics_data)
            else:
                # AWG - уже строка
                raw_metrics_str = raw_metrics_data
            if core_type in XRAY_LIKE_CORES:
                # Парсер xray/sing-box отдаёт прирост с прошлого опроса, а первый опрос — точка отсчёта
                # (см. тесты группы 4). Делаем её пустым ответом: тогда счётчики ниже учитываются целиком
                success, _ = await HotReloadExecutor.execute_action_script(
                    script=parser_code,
                    lib_names=lib_names,
                    node_ip='0',
                    core_api_port=0,
                    action='parse_metrics',
                    custom_params={
                        "raw_metrics": json.dumps(sample_metrics['empty']),
                        "vpn_users": mock_vpn_users,
                        "local_state": mock_local_state,
                    },
                )
                assert success is True
            success, result = await HotReloadExecutor.execute_action_script(
                script=parser_code,
                lib_names=lib_names,
                node_ip='0',
                core_api_port=0,
                action='parse_metrics',
                custom_params={
                    "raw_metrics": raw_metrics_str,
                    "vpn_users": mock_vpn_users,
                    "local_state": mock_local_state,
                },
            )
            assert success is True, f"Парсер упал на тестовых данных: {result}"
            # Парсер возвращает tuple (users_traffics, troubles)
            assert isinstance(result, tuple) and len(result) == 2, (
                f"Template '{template['title']}': parse_metrics должен возвращать tuple (users_traffics, troubles)"
            )
            users_traffics, troubles = result
            assert isinstance(users_traffics, list), (
                f"Template '{template['title']}': users_traffics должен быть списком"
            )
            assert isinstance(troubles, list), f"Template '{template['title']}': troubles должен быть списком"
            # Проверяем что распарсили 3 пользователей
            assert len(users_traffics) == 3, (
                f"Template '{template['title']}': Ожидалось 3 пользователя, получено {len(users_traffics)}"
            )
            # Проверяем формат каждой записи
            for traffic_record in users_traffics:
                assert 'user_sub_id' in traffic_record, (
                    f"Template '{template['title']}': Запись должна содержать 'user_sub_id'"
                )
                assert 'total_mb_used' in traffic_record, (
                    f"Template '{template['title']}': Запись должна содержать 'total_mb_used'"
                )
                assert isinstance(traffic_record['user_sub_id'], int), (
                    f"Template '{template['title']}': 'user_sub_id' должен быть int"
                )
                assert isinstance(traffic_record['total_mb_used'], int), (
                    f"Template '{template['title']}': 'total_mb_used' должен быть int (MB)"
                )
            # Проверяем суммирование uplink + downlink
            user1_traffic = next((u for u in users_traffics if u['user_sub_id'] == 1), None)
            assert user1_traffic is not None, "Пользователь 1 должен быть в результатах"
            assert user1_traffic['total_mb_used'] == 3, (
                f"Template '{template['title']}': "
                f"Пользователь 1: ожидалось 3 MB (1+2), получено {user1_traffic['total_mb_used']}"
            )
            # Тест 2: Пустые данные (нет трафика)
            raw_metrics_empty = sample_metrics['empty']
            if core_type in ['xray', 'singbox', 'hysteria']:
                raw_metrics_empty_str = json.dumps(raw_metrics_empty)
            else:
                raw_metrics_empty_str = raw_metrics_empty
            success_empty, result_empty = await HotReloadExecutor.execute_action_script(
                script=parser_code,
                lib_names=lib_names,
                node_ip='0',
                core_api_port=0,
                action='parse_metrics',
                custom_params={
                    "raw_metrics": raw_metrics_empty_str,
                    "vpn_users": mock_vpn_users,
                    "local_state": {},  # Свежий state для второго теста
                },
            )
            assert success_empty is True, f"Парсер упал на пустом JSON: {result_empty}"
            # Распаковываем результат
            users_traffics_empty, troubles_empty = result_empty
            assert isinstance(users_traffics_empty, list), "users_traffics должен быть списком"
            assert len(users_traffics_empty) == 0, (
                f"Template '{template['title']}': Для пустого JSON должен возвращаться пустой список"
            )
            # Тест 3: JSON с troubles - пропускаем, т.к. troubles теперь в local_state
            # TODO: обновить тест когда уточним формат troubles в HotReloadExecutor


@pytest.mark.skip(reason="Real режим отключён: требуется доработка protobuf конвертации и Docker настройки")
@pytest.mark.real_core
@pytest.mark.parametrize("use_real_core", [True], ids=["real"])
@pytest.mark.asyncio
@pytest.mark.db
async def test_template_metrics_collection_execution(
    protocol_templates_with_extractors, use_real_core, request, is_real_mode, mock_universal_core
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
        # Получаем контейнер через универсальную функцию
        core_ip, core_port = get_core_container(template['title'], is_real_mode)
        if not core_ip or not core_port:
            continue
        # Проверяем наличие скрипта метрик
        metrics_script = template.get('api_metrics_script')
        if not metrics_script:
            pytest.fail(
                f"Template '{template['title']}': api_metrics_script не может быть пустым для is_accepted=true шаблонов"
            )
        lib_names = template.get('proto_python_lib')
        # Выполняем скрипт сбора метрик
        success, raw_metrics = await HotReloadExecutor.execute_action_script(
            script=metrics_script,
            lib_names=lib_names,
            node_ip=core_ip,
            core_api_port=core_port,
            action='get_metrics',
            custom_params={},
        )
        # Проверяем успешность выполнения
        assert success is True, (
            f"Template '{template['title']}': "
            f"Скрипт api_metrics_script должен выполняться без ошибок. "
            f"Raw metrics: {raw_metrics}"
        )
        # Проверяем что получили ответ (может быть пустым - это OK)
        assert raw_metrics is not None, (
            f"Template '{template['title']}': api_metrics_script должен возвращать ответ (может быть пустой JSON)"
        )
        # Проверяем что парсер не падает на реальных данных
        parser_code = template.get('metrics_parser_code')
        assert parser_code, f"Template '{template['title']}': metrics_parser_code не может быть пустым"
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
            'len': len,
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
                f"Template '{template['title']}': parse() должен возвращать список users_traffics"
            )
            assert isinstance(troubles, list), (
                f"Template '{template['title']}': parse() должен возвращать список troubles"
            )
        except Exception as e:
            pytest.fail(
                f"Template '{template['title']}': Парсер упал на реальных данных: {e}\nRaw metrics: {raw_metrics}"
            )


# ========== Группа 4: Метрики xray/sing-box — прирост по local_state, форматы входа ==========

MB = 1024 * 1024
XRAY_LIKE_CORES = ('xray', 'singbox')


def _xray_like_templates(templates: list[dict]) -> list[dict]:
    """Шаблоны xray/sing-box, по одному на каждый уникальный набор скриптов метрик (их 55 одинаковых)"""
    unique: dict[tuple, dict] = {}
    for template in templates:
        if get_core_type(template['title']) in XRAY_LIKE_CORES and template.get('metrics_parser_code'):
            unique.setdefault((template['metrics_parser_code'], template.get('api_metrics_script')), template)
    if not unique:
        pytest.skip("Среди выбранных шаблонов нет xray/sing-box с парсером метрик")
    return list(unique.values())


def _stats(**bytes_by_counter) -> list[dict]:
    """user_1_up=5 → [{'name': 'user>>>1>>>traffic>>>uplink', 'value': 5}] — формат ответа API-скрипта"""
    result = []
    for key, value in bytes_by_counter.items():
        _, user_sub_id, direction = key.split('_')
        result.append(
            {
                'name': f"user>>>{user_sub_id}>>>traffic>>>{'uplink' if direction == 'up' else 'downlink'}",
                'value': value,
            }
        )
    return result


async def _parse(template: dict, raw_metrics, local_state: dict) -> tuple[dict[int, int], list]:
    """Запускает парсер шаблона в песочнице. Возвращает ({user_sub_id: МБ}, troubles)"""
    success, result = await HotReloadExecutor.execute_action_script(
        script=template['metrics_parser_code'],
        lib_names=template.get('proto_python_lib'),
        node_ip='0',
        core_api_port=0,
        action='parse_metrics',
        custom_params={"raw_metrics": raw_metrics, "vpn_users": {}, "local_state": local_state},
    )
    assert success is True, f"Template '{template['title']}': парсер упал: {result}"
    users_traffics, troubles = result
    return {u['user_sub_id']: u['total_mb_used'] for u in users_traffics}, troubles


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_metrics_parser_counts_delta_between_polls(protocol_templates_with_extractors):
    """
    Парсер отдаёт ПРИРОСТ трафика между опросами, а не накопленный счётчик ядра.

    Счётчики ядра не сбрасываются (reset убран): коллектор прибавляет ответ парсера к used_mb, поэтому
    повторная отдача накопленного значения — это многократный учёт одного и того же трафика.
    """
    for template in _xray_like_templates(protocol_templates_with_extractors):
        state: dict = {}
        title = template['title']

        # Первый опрос с пустым state (нод-клиент перезапущен, ядро работает давно): трафик до этого момента
        # уже учтён прошлыми опросами — берём значения за точку отсчёта и ничего не отдаём
        traffic, _ = await _parse(template, _stats(user_1_up=5 * MB, user_1_down=7 * MB), state)
        assert traffic == {}, f"{title}: первый опрос — точка отсчёта, а не трафик: {traffic}"

        # Счётчики не изменились — трафика нет
        traffic, _ = await _parse(template, _stats(user_1_up=5 * MB, user_1_down=7 * MB), state)
        assert traffic == {}, f"{title}: без изменения счётчиков трафика быть не должно: {traffic}"

        # Прирост: +1 МБ вверх и +2 МБ вниз; у нового пользователя 2 счётчик появился после точки отсчёта —
        # он учитывается целиком
        traffic, _ = await _parse(template, _stats(user_1_up=6 * MB, user_1_down=9 * MB, user_2_down=4 * MB), state)
        assert traffic == {1: 3, 2: 4}, f"{title}: ожидался только прирост: {traffic}"


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_metrics_parser_keeps_sub_megabyte_remainder(protocol_templates_with_extractors):
    """Трафик меньше 1 МБ за опрос не теряется: остаток байт переносится на следующий опрос"""
    for template in _xray_like_templates(protocol_templates_with_extractors):
        state: dict = {}
        await _parse(template, [], state)  # точка отсчёта

        traffic, _ = await _parse(template, _stats(user_1_up=int(0.6 * MB)), state)
        assert traffic == {}, f"{template['title']}: 0.6 МБ — ещё не целый мегабайт: {traffic}"

        # uplink и downlink округляются не по отдельности: 0.6 + 0.3 + 0.3 = 1.2 МБ → 1 МБ, 0.2 в остатке
        traffic, _ = await _parse(template, _stats(user_1_up=int(0.9 * MB), user_1_down=int(0.3 * MB)), state)
        assert traffic == {1: 1}, f"{template['title']}: остаток прошлого опроса должен был добрать мегабайт: {traffic}"

        # 0.2 в остатке + 0.9 = 1.1 → ещё 1 МБ
        traffic, _ = await _parse(template, _stats(user_1_up=int(1.8 * MB), user_1_down=int(0.3 * MB)), state)
        assert traffic == {1: 1}, f"{template['title']}: {traffic}"


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_metrics_parser_survives_core_restart(protocol_templates_with_extractors):
    """Перезапуск ядра обнуляет счётчики: прирост после него — это новое значение счётчика, а не разность"""
    for template in _xray_like_templates(protocol_templates_with_extractors):
        title = template['title']

        # Счётчик стал меньше прошлого значения
        state: dict = {}
        await _parse(template, _stats(user_1_up=50 * MB), state)
        traffic, _ = await _parse(template, _stats(user_1_up=2 * MB), state)
        assert traffic == {1: 2}, f"{title}: после обнуления счётчика учитывается его новое значение: {traffic}"

        # Счётчик пропал из ответа (ядро перезапущено, пользователь ещё не ходил), а затем вернулся со
        # значением БОЛЬШЕ прежнего — учитывается целиком, а не как разность со старым
        state = {}
        await _parse(template, _stats(user_1_up=50 * MB), state)
        traffic, _ = await _parse(template, [], state)
        assert traffic == {}
        traffic, _ = await _parse(template, _stats(user_1_up=70 * MB), state)
        assert traffic == {1: 70}, f"{title}: счётчик после перезапуска ядра учитывается целиком: {traffic}"


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_metrics_parser_accepts_all_input_formats(protocol_templates_with_extractors):
    """
    Один парсер разбирает всё, что может прийти: список словарей от API-скрипта, JSON от CLI (строкой и словарём,
    значения — числами или строками) и список protobuf-сообщений, который отдаёт xtlsapi (stats_query(...).stat —
    на нём старый парсер падал с 'RepeatedCompositeContainer' object has no attribute 'get')
    """
    from xtlsapi.xray_api.app.stats.command import command_pb2

    def protobuf_stats(stats: list[dict]):
        return command_pb2.QueryStatsResponse(stat=[command_pb2.Stat(**s) for s in stats]).stat

    after = _stats(user_1_up=3 * MB, user_1_down=1 * MB, user_2_up=2 * MB)
    cli_json_with_string_values = {"stat": [{"name": s['name'], "value": str(s['value'])} for s in after]}

    formats = {
        # формат: (пустой ответ для точки отсчёта, ответ с трафиком)
        'список словарей (API-скрипт)': ([], after),
        'словарь CLI': ({"stat": []}, {"stat": after}),
        'JSON-строка CLI': ('{"stat": []}', json.dumps({"stat": after})),
        'JSON-строка CLI, пустой объект': ('{}', json.dumps(cli_json_with_string_values)),
        'protobuf от xtlsapi': (protobuf_stats([]), protobuf_stats(after)),
    }
    for template in _xray_like_templates(protocol_templates_with_extractors):
        for format_name, (empty, with_traffic) in formats.items():
            state: dict = {}
            traffic, troubles = await _parse(template, empty, state)
            assert traffic == {} and troubles == [], f"{template['title']} / {format_name}: пустой ответ: {traffic}"
            traffic, troubles = await _parse(template, with_traffic, state)
            assert traffic == {1: 4, 2: 2}, f"{template['title']} / {format_name}: {traffic}"
            assert troubles == []


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_metrics_parser_reports_troubles_without_failing(protocol_templates_with_extractors):
    """Чужие и битые записи уходят в troubles и не роняют разбор остальных"""
    for template in _xray_like_templates(protocol_templates_with_extractors):
        state: dict = {}
        await _parse(template, [], state)
        raw = [
            *_stats(user_1_up=2 * MB),
            {'name': 'inbound>>>api>>>traffic>>>uplink', 'value': 999},  # не пользовательский счётчик
            {'name': 'user>>>not-a-number>>>traffic>>>uplink', 'value': 5 * MB},  # user_sub_id не число
            {'name': 'user>>>7>>>traffic>>>uplink'},  # нулевое значение CLI не печатает вовсе
        ]
        traffic, troubles = await _parse(template, raw, state)
        assert traffic == {1: 2}, f"{template['title']}: {traffic}"
        assert len(troubles) == 2, f"{template['title']}: в troubles — 2 записи: {troubles}"


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_api_metrics_script_returns_plain_stats_without_reset(protocol_templates_with_extractors):
    """
    API-скрипт метрик отдаёт простой список {'name', 'value'} и НЕ сбрасывает счётчики ядра:
    прирост считает парсер. Со сбросом ответ, потерянный по дороге, терял и трафик
    """
    import xtlsapi
    from xtlsapi.xray_api.app.stats.command import command_pb2

    calls: list[dict] = []

    class FakeXrayClient:
        def __init__(self, host, port):
            pass

        def stats_query(self, pattern, reset=False):
            calls.append({'pattern': pattern, 'reset': reset})
            return command_pb2.QueryStatsResponse(
                stat=[command_pb2.Stat(name='user>>>1>>>traffic>>>uplink', value=3 * MB)]
            ).stat

    for template in _xray_like_templates(protocol_templates_with_extractors):
        if not template.get('api_metrics_script'):
            continue
        calls.clear()
        with patch.object(xtlsapi, 'XrayClient', FakeXrayClient):
            success, raw = await HotReloadExecutor.execute_action_script(
                script=template['api_metrics_script'],
                lib_names=template.get('proto_python_lib'),
                node_ip='127.0.0.1',
                core_api_port=10085,
                action='get_metrics',
                custom_params={},
            )
        assert success is True, f"{template['title']}: API-скрипт метрик упал: {raw}"
        assert raw == [{'name': 'user>>>1>>>traffic>>>uplink', 'value': 3 * MB}], f"{template['title']}: {raw!r}"
        assert calls == [{'pattern': 'user>>>', 'reset': False}], f"{template['title']}: {calls}"

        # CLI-команда (запасной путь) тоже не сбрасывает счётчики
        assert 'reset' not in (template.get('metrics_command') or ''), (
            f"{template['title']}: metrics_command сбрасывает счётчики: {template['metrics_command']}"
        )


# ========== Группа 5: flow (XTLS Vision) в шаблонах xray ==========


def _flow_allowed(title: str) -> bool:
    """
    XTLS Vision (flow) работает только у VLESS поверх голого TCP. На gRPC/XHTTP/WS ядро отвергает соединение
    («rejected since the client flow is empty»), а у Trojan с flow в конфиге xray не запускается вовсе
    («The feature Flow for Trojan has been removed»)
    """
    return '-vless-' in title and title.endswith('-tcp')


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_templates_use_flow_only_for_vless_over_tcp(protocol_templates_with_extractors):
    checked = 0
    for template in protocol_templates_with_extractors:
        title = template['title']
        if get_core_type(title) != 'xray' or _flow_allowed(title):
            continue
        checked += 1
        for field in ('constant_user_data_obj', 'bulk_add_script_custom_params', 'bulk_delete_script_custom_params'):
            value = template.get(field) or {}
            if isinstance(value, str):
                value = json.loads(value)
            assert 'flow' not in value, f"{title}: flow в {field}: {value}"
        for extractor in template.get('extractors') or []:
            assert 'flow' not in extractor['extractor_script'], (
                f"{title}: экстрактор пишет flow в конфиг ядра:\n{extractor['extractor_script']}"
            )
        assert 'flow=' not in (template.get('url_tmp') or ''), f"{title}: flow в ссылке подписки: {template['url_tmp']}"
        assert "'flow'" not in (template.get('sub_prepare_script') or ''), (
            f"{title}: sub_prepare_script читает flow пользователя"
        )
    if not checked:
        pytest.skip("Среди выбранных шаблонов нет xray-шаблонов без поддержки flow")


@pytest.mark.asyncio
@pytest.mark.db
async def test_xray_vless_add_script_does_not_default_to_vision_flow(protocol_templates_with_extractors):
    """
    Скрипт добавления пользователя берёт flow только из custom_params. Раньше при отсутствии параметра он
    подставлял xtls-rprx-vision — пользователь, добавленный через API ядра, не мог подключиться до перезапуска ядра
    """
    import xtlsapi

    added: list[dict] = []

    class FakeXrayClient:
        def __init__(self, host, port):
            pass

        def add_client(self, **kwargs):
            added.append(kwargs)

    checked = 0
    for template in protocol_templates_with_extractors:
        title = template['title']
        script = template.get('api_bulk_add_user_script') or ''
        if get_core_type(title) != 'xray' or '-vless-' not in title or 'flow' not in script:
            continue
        checked += 1
        added.clear()
        with patch.object(xtlsapi, 'XrayClient', FakeXrayClient):
            success, result = await HotReloadExecutor.execute_action_script(
                script=script,
                lib_names=template.get('proto_python_lib'),
                user_obj=[{'user_sub_id': '1', 'user_uuid': '11111111-1111-1111-1111-111111111111'}],
                node_ip='127.0.0.1',
                core_api_port=10085,
                action='user_core_operation',
                custom_params={'inbound_tag': 'vless-inbound'},
            )
        assert success is True and result == {'success': 1, 'failed': 0}, f"{title}: {result}"
        assert not added[0].get('flow'), f"{title}: без flow в custom_params скрипт передал ядру {added[0]}"
    if not checked:
        pytest.skip("Среди выбранных шаблонов нет xray-vless со скриптом добавления через API")
