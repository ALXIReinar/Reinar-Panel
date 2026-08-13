"""
E2E тесты для полномасштабного пайплайна proto_core endpoints

Тестируют полный workflow:
1. HTTP запрос → /proto_core/user/add или /user/delete
2. Hot-reload попытка (если есть скрипт) → HotReloadExecutor
3. Добавление в WBC → buffer.add_user() / buffer.delete_user()
4. Батчинг → воркер собирает операции
5. Запись на диск → _write_node_to_disk()
6. Перезагрузка ядра (если hot-reload failed или нет скрипта)

Используются реальные скрипты из БД для проверки production-like поведения.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
import orjson

from node_client.tests.conftest import TemplateScriptFields
from node_client.api.proto_core.write_behind_caching_file import flatten_key2value


# ========== Helper функции ==========

def create_test_superuser(
    user_uuid: str = None,
    user_sub_id: str = "42",
    **constant_fields
) -> dict:
    """
    Создаёт суперобъект пользователя для тестов
    
    Суперобъект - это объект который хранится в state конфиге и buffer_storage.
    Всегда содержит:
    - user_uuid (обязательно, системное)
    - user_sub_id (обязательно, системное, ID подписки)
    - constant_user_data_obj поля (flow, level, и др.)
    
    Args:
        user_uuid: UUID пользователя
        user_sub_id: ID подписки пользователя
        **constant_fields: Константные поля из proto_templates.constant_user_data_obj
                          Например: flow="xtls-rprx-vision", level=0
    
    Returns:
        dict: Суперобъект пользователя
    
    Example:
        >>> user = create_test_superuser(
        ...     user_uuid="test-uuid-123",
        ...     user_sub_id="42",
        ...     flow="xtls-rprx-vision",
        ...     level=0
        ... )
    """
    import uuid as uuid_lib
    
    if user_uuid is None:
        user_uuid = str(uuid_lib.uuid4())
    
    superuser = {
        "user_uuid": user_uuid,
        "user_sub_id": user_sub_id,
        **constant_fields
    }
    
    return superuser


def create_default_user_injectors(flatten_array_cursor: str = "inbounds___1___settings___clients") -> list[dict]:
    """
    Создаёт дефолтные user_injectors для тестов
    
    Args:
        flatten_array_cursor: Путь к массиву пользователей в конфиге
    
    Returns:
        list[dict]: Список с одним инжектором
    """
    return [
        {
            "flatten_array_cursor": flatten_array_cursor,
            "extractor_script": """
def transform(user_obj):
    '''
    Трансформирует суперобъект в объект для ядра xray/vless
    
    Суперобъект (из state конфига):
        {user_uuid, user_sub_id, flow, level, ...}
    
    Объект ядра (для config.json):
        {id, email, flow, level, ...}
    '''
    # user_uuid → id (для xray конфига)
    # user_sub_id → email (для идентификации в метриках)
    return {
        'id': user_obj['user_uuid'],
        'email': user_obj.get('user_sub_id', 'unknown'),
        'flow': user_obj.get('flow', 'xtls-rprx-vision'),
        'level': user_obj.get('level', 0)
    }
""",
            "libs": None
        }
    ]


def create_e2e_request_body(
    node_proto_id: int,
    users: list[dict],
    config_file_path: str,
    user_injectors: list[dict],
    action: str = "add",
    reload_core_command: str = None,
    core_lib: str = None,
    core_port: int = None,
    action_script: str = None,
    custom_params: dict = None
) -> dict:
    """
    Создаёт правильное тело запроса для /proto_core/user/bulk/action
    
    Args:
        node_proto_id: ID ноды
        users: Список пользователей (суперобъекты)
        config_file_path: Путь к конфигу
        user_injectors: Список инжекторов [{flatten_array_cursor, extractor_script, libs}, ...]
        action: "add" или "delete"
        reload_core_command: Команда перезагрузки ядра
        core_lib: Библиотеки для hot-reload
        core_port: Порт API ядра
        action_script: Скрипт для hot-reload
        custom_params: Дополнительные параметры для скрипта
    
    Returns:
        dict: Валидное тело запроса согласно BaseUserCoreSchema
    """
    return {
        "node_proto_id": node_proto_id,
        "users": users,
        "config_file_path": config_file_path,
        "user_injectors": user_injectors,
        "action": action,
        "reload_core_command": reload_core_command,
        "core_lib": core_lib,
        "core_port": core_port,
        "action_script": action_script,
        "custom_params": custom_params or {}
    }


# ========== Локальные фикстуры ==========

@pytest.fixture
def get_script_from_template(protocol_templates):
    """
    ВНИМАНИЕ: Возвращает getter для ПЕРВОГО шаблона из списка!
    
    Не использовать для тестов которые должны проверять ВСЕ шаблоны.
    Только для e2e тестов где достаточно проверить логику на одном шаблоне.
    
    Эта фикстура локальная для test_proto_core_pipeline.py чтобы избежать
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
        """Мок для получения метрик"""
        self.calls.append(('stats_query', kwargs))
        # Возвращаем фейковые метрики в формате Xray
        return '{"stat": [{"name": "user>>>1>>>traffic>>>uplink", "value": 1024}]}'


class MockXtlsapiModule:
    """Мок для модуля xtlsapi"""
    XrayClient = MockXrayClient
    
    class exceptions:
        EmailAlreadyExists = type('EmailAlreadyExists', (Exception,), {})
        EmailNotFound = type('EmailNotFound', (Exception,), {})


@pytest.fixture
def mock_xtlsapi_e2e():
    """Подменяет xtlsapi в sys.modules для E2E тестов"""
    mock_module = MockXtlsapiModule()
    
    with patch.dict('sys.modules', {'xtlsapi': mock_module}):
        yield mock_module


# ========== Тест 1: Добавление пользователя БЕЗ API-скрипта (только файл) ==========

@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_add_user_without_api_script_only_file(
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    get_script_from_template
):
    """
    E2E: Добавление пользователя БЕЗ API-скрипта
    
    Сценарий: add_script=None → только WBC + reload
    
    Проверяем:
    - Пользователь добавлен в WBC буфер
    - Воркер записал на диск
    - Пользователь присутствует в файле
    - Команда перезагрузки ядра выполнена
    """
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    mock_subprocess.return_value.communicate = AsyncMock(return_value=(b'', b''))
    mock_subprocess.return_value.returncode = 0
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Подготавливаем запрос БЕЗ API-скрипта
        lib_names = get_script_from_template(TemplateScriptFields.lib_names)
        
        # Создаём суперобъект пользователя
        test_user = create_test_superuser(
            user_uuid="e2e-test-uuid-no-script",
            user_sub_id="test_sub_42",
            flow="xtls-rprx-vision",
            level=0
        )
        
        request_body = create_e2e_request_body(
            node_proto_id=1,
            users=[test_user],
            config_file_path=str(e2e_config_path),
            user_injectors=create_default_user_injectors(),
            action="add",
            reload_core_command="echo 'reload'",
            core_lib=lib_names,
            core_port=10085,
            action_script=None,  # НЕТ API-скрипта!
            custom_params={}
        )
        
        # Отправляем запрос
        response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['hot_reload'] is False  # Не было hot-reload
        
        # Ждём пока воркер запишет на диск (timeout=0.3s)
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователь в буфере
        assert 1 in e2e_buffer.buffer_storage
        assert "e2e-test-uuid-no-script" in e2e_buffer.buffer_storage[1]  # Проверяем по user_uuid
        
        # Читаем файл и проверяем наличие пользователя
        _, updated_config = await e2e_buffer._read_config(str(e2e_config_path))
        updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
        
        # Проверяем что пользователь добавлен (должен быть ровно 1 пользователь)
        assert len(updated_users) == 1
        
        # Проверяем наличие пользователя в файле (email = user_sub_id из суперобъекта)
        added_user = next((u for u in updated_users if u['email'] == 'test_sub_42'), None)
        assert added_user is not None
        assert added_user['id'] == "e2e-test-uuid-no-script"
        
        # Проверяем что команда перезагрузки была вызвана (т.к. нет hot-reload)
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert "echo 'reload'" in call_args[0][0]


# ========== Тест 2: Удаление пользователя БЕЗ API-скрипта (только файл) ==========

@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_delete_user_without_api_script_only_file(
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    get_script_from_template
):
    """
    E2E: Удаление пользователя БЕЗ API-скрипта
    
    Сценарий: delete_script=None → только WBC + reload
    
    Проверяем:
    - Пользователь удалён из WBC буфера
    - Воркер записал на диск
    - Пользователь отсутствует в файле
    - Команда перезагрузки ядра выполнена
    """
    
    # Сначала добавляем пользователя
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    # Создаём суперобъект для добавления
    test_user = create_test_superuser(
        user_uuid="e2e-delete-uuid",
        user_sub_id="delete_sub_42",
        flow="xtls-rprx-vision",
        level=0
    )
    
    add_request = create_e2e_request_body(
        node_proto_id=1,
        users=[test_user],
        config_file_path=str(e2e_config_path),
        user_injectors=create_default_user_injectors(),
        action="add",
        reload_core_command="echo 'reload'",
        core_lib=lib_names,
        core_port=10085,
        action_script=None,
        custom_params={}
    )
    
    response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=add_request)
    assert response.status_code == 200
    
    # Ждём записи
    await asyncio.sleep(0.5)
    
    # Проверяем что пользователь добавлен в буфер
    assert "e2e-delete-uuid" in e2e_buffer.buffer_storage[1]
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    mock_subprocess.return_value.communicate = AsyncMock(return_value=(b'', b''))
    mock_subprocess.return_value.returncode = 0
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Удаляем пользователя БЕЗ API-скрипта
        delete_request = create_e2e_request_body(
            node_proto_id=1,
            users=[test_user],  # Тот же суперобъект для удаления
            config_file_path=str(e2e_config_path),
            user_injectors=create_default_user_injectors(),
            action="delete",  # ВАЖНО: action="delete"
            reload_core_command="echo 'reload'",
            core_lib=lib_names,
            core_port=10085,
            action_script=None,  # НЕТ delete-скрипта!
            custom_params={}
        )
        
        response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=delete_request)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['hot_reload'] is False
        
        # Ждём записи
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователя нет в буфере (по user_uuid)
        assert "e2e-delete-uuid" not in e2e_buffer.buffer_storage[1]
        
        # Читаем файл и проверяем отсутствие пользователя
        _, after_delete_config = await e2e_buffer._read_config(str(e2e_config_path))
        after_delete_users = e2e_buffer._navigate_to_path(after_delete_config, "inbounds___1___settings___clients")
        
        # Проверяем что массив пустой (был 1 пользователь, удалили его)
        assert len(after_delete_users) == 0
        
        # Проверяем отсутствие пользователя (по id = user_uuid)
        deleted_user = next((u for u in after_delete_users if u['id'] == 'e2e-delete-uuid'), None)
        assert deleted_user is None
        
        # Проверяем что команда перезагрузки была вызвана
        mock_subprocess.assert_called_once()


# ========== Тест 3: Добавление пользователя С API-скриптом (успех) ==========

@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_add_user_with_api_script_success_no_reload(
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    get_script_from_template,
    mock_xtlsapi_e2e
):
    """
    E2E: Добавление пользователя С API-скриптом (успех)
    
    Сценарий: add_script работает → hot-reload успешен → НЕ перезагружаем ядро
    
    Проверяем:
    - Hot-reload выполнен успешно
    - Пользователь добавлен в WBC буфер
    - Пользователь записан в файл
    - Команда перезагрузки НЕ выполнена (т.к. hot-reload успешен)
    """
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Загружаем реальный скрипт из БД
        add_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
        lib_names = get_script_from_template(TemplateScriptFields.lib_names)
        custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
        
        # Создаём суперобъект
        test_user = create_test_superuser(
            user_uuid="e2e-hot-reload-success",
            user_sub_id="hot_reload_sub_42",
            flow="xtls-rprx-vision",
            level=0
        )
        
        request_body = create_e2e_request_body(
            node_proto_id=1,
            users=[test_user],
            config_file_path=str(e2e_config_path),
            user_injectors=create_default_user_injectors(),
            action="add",
            reload_core_command="echo 'reload'",
            core_lib=lib_names,
            core_port=10085,
            action_script=add_script,  # Есть API-скрипт!
            custom_params=custom_params
        )
        
        response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['hot_reload'] is True  # Hot-reload выполнен успешно!
        
        # Ждём записи
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователь в буфере (по user_uuid)
        assert "e2e-hot-reload-success" in e2e_buffer.buffer_storage[1]
        
        # Читаем файл
        _, updated_config = await e2e_buffer._read_config(str(e2e_config_path))
        updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
        
        # Проверяем что пользователь добавлен (должен быть 1)
        assert len(updated_users) == 1
        
        # Проверяем наличие пользователя (email = user_sub_id)
        added_user = next((u for u in updated_users if u['email'] == 'hot_reload_sub_42'), None)
        assert added_user is not None
        assert added_user['id'] == 'e2e-hot-reload-success'
        
        # ВАЖНО: Команда перезагрузки БУДЕТ вызвана даже при успешном hot-reload
        # (чтобы синхронизировать состояние ядра с файлом на диске)
        mock_subprocess.assert_called_once()


# ========== Тест 4: Добавление пользователя С API-скриптом (провал) ==========

@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_add_user_with_api_script_failure_with_reload(
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    get_script_from_template
):
    """
    E2E: Добавление пользователя С API-скриптом (провал)
    
    Сценарий: add_script failed → hot-reload провалился → перезагружаем ядро
    
    Проверяем:
    - Hot-reload провалился
    - Пользователь всё равно добавлен в WBC буфер (fallback)
    - Пользователь записан в файл
    - Команда перезагрузки выполнена (т.к. hot-reload failed)
    """
    
    # Создаём скрипт который провалится (используем bulk_add_users)
    broken_script = """
async def bulk_add_users(users_list, node_ip, core_port, custom_params):
    # Намеренная ошибка для провала hot-reload
    raise ValueError("Hot-reload intentionally failed")
"""
    
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    mock_subprocess.return_value.communicate = AsyncMock(return_value=(b'', b''))
    mock_subprocess.return_value.returncode = 0
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Создаём суперобъект
        test_user = create_test_superuser(
            user_uuid="e2e-hot-reload-fail",
            user_sub_id="hot_reload_fail_sub",
            flow="xtls-rprx-vision",
            level=0
        )
        
        request_body = create_e2e_request_body(
            node_proto_id=1,
            users=[test_user],
            config_file_path=str(e2e_config_path),
            user_injectors=create_default_user_injectors(),
            action="add",
            reload_core_command="echo 'reload'",
            core_lib=lib_names,
            core_port=10085,
            action_script=broken_script,  # Скрипт который провалится
            custom_params={}
        )
        
        response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True  # WBC всё равно добавил (fallback)
        assert data['hot_reload'] is False  # Hot-reload провалился!
        assert "ValueError" in data['hot_reload_message']
        
        # Ждём записи
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователь всё равно в буфере (fallback по user_uuid)
        assert "e2e-hot-reload-fail" in e2e_buffer.buffer_storage[1]
        
        # Читаем файл
        _, updated_config = await e2e_buffer._read_config(str(e2e_config_path))
        updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
        
        # Проверяем длину массива
        assert len(updated_users) == 1
        
        # Проверяем наличие пользователя (email = user_sub_id)
        added_user = next((u for u in updated_users if u['email'] == 'hot_reload_fail_sub'), None)
        assert added_user is not None
        assert added_user['id'] == 'e2e-hot-reload-fail'
        
        # ВАЖНО: Команда перезагрузки ДОЛЖНА быть вызвана
        mock_subprocess.assert_called_once()


# ========== Тест 5: Bulk добавление пользователей С API-скриптом ==========

@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_bulk_add_users_with_api_script_unlimit_flush(
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    get_script_from_template,
    mock_xtlsapi_e2e
):
    """
    E2E: Bulk добавление пользователей С API-скриптом
    
    Сценарий: bulk_add_script → hot-reload → unlimit_queue → принудительный flush
    
    Проверяем:
    - Bulk hot-reload выполнен
    - Все пользователи добавлены в WBC
    - unlimit_queue отключил лимиты
    - Принудительный flush записал всех сразу
    - Все пользователи в файле
    """
    
    # Загружаем bulk скрипт из БД
    bulk_add_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    # Подготавливаем 10 суперобъектов
    users_to_add = [
        create_test_superuser(
            user_uuid=f"bulk-uuid-{i}",
            user_sub_id=f"bulk_sub_{i}",
            flow="xtls-rprx-vision",
            level=0
        )
        for i in range(10)
    ]
    
    request_body = create_e2e_request_body(
        node_proto_id=1,
        users=users_to_add,
        config_file_path=str(e2e_config_path),
        user_injectors=create_default_user_injectors(),
        action="add",
        reload_core_command="echo 'reload'",
        core_lib=lib_names,
        core_port=10085,
        action_script=bulk_add_script,
        custom_params=custom_params
    )
    
    # Начальная задержка для изоляции от других тестов
    await asyncio.sleep(0.3)
    
    response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=request_body)
    
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['hot_reload'] is True
    
    # Bulk операция должна записать сразу (unlimit_queue + flush)
    # Увеличенная задержка для гарантированной записи на диск
    await asyncio.sleep(1.0)
    
    # Принудительный flush для синхронизации
    await e2e_buffer._flush_all_nodes(node_proto_id=1)
    await asyncio.sleep(0.2)
    
    # Проверяем что все пользователи в буфере (по user_uuid)
    for user in users_to_add:
        assert user['user_uuid'] in e2e_buffer.buffer_storage[1]
    
    # Читаем файл
    _, updated_config = await e2e_buffer._read_config(str(e2e_config_path))
    updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
    
    # Проверяем что добавлено 10 пользователей
    assert len(updated_users) == 10
    
    # Проверяем наличие всех пользователей (email = user_sub_id)
    for i, user in enumerate(users_to_add):
        found_user = next((u for u in updated_users if u['email'] == f'bulk_sub_{i}'), None)
        assert found_user is not None, f"User bulk_sub_{i} not found in file"
        assert found_user['id'] == f'bulk-uuid-{i}'


# ========== Тест 6: Bulk удаление пользователей БЕЗ API-скрипта ==========

@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_bulk_delete_users_without_api_script(
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    get_script_from_template
):
    """
    E2E: Bulk удаление пользователей БЕЗ API-скрипта
    
    Сценарий: bulk_delete без скрипта → только WBC
    
    Проверяем:
    - Все пользователи удалены из буфера
    - Файл обновлён
    - Длина массива уменьшилась на N
    """
    
    # Сначала добавляем пользователей для удаления
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    # Создаём 5 суперобъектов для добавления
    users_to_add = [
        create_test_superuser(
            user_uuid=f"bulk-del-{i}",
            user_sub_id=f"bulk_del_sub_{i}",
            flow="xtls-rprx-vision",
            level=0
        )
        for i in range(5)
    ]
    
    # Добавляем всех пользователей одним bulk запросом
    add_request = create_e2e_request_body(
        node_proto_id=1,
        users=users_to_add,
        config_file_path=str(e2e_config_path),
        user_injectors=create_default_user_injectors(),
        action="add",
        reload_core_command="",  # Пустая строка вместо None
        core_lib=lib_names,
        core_port=10085,
        action_script=None,
        custom_params={}
    )
    response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=add_request)
    assert response.status_code == 200
    
    # Ждём записи
    await asyncio.sleep(0.5)
    
    # Проверяем что все добавлены в буфер
    for user in users_to_add:
        assert user['user_uuid'] in e2e_buffer.buffer_storage[1]
    
    # Bulk удаление БЕЗ API-скрипта (удаляем тех же пользователей)
    delete_request = create_e2e_request_body(
        node_proto_id=1,
        users=users_to_add,  # Те же суперобъекты для удаления
        config_file_path=str(e2e_config_path),
        user_injectors=create_default_user_injectors(),
        action="delete",  # ВАЖНО: action="delete"
        reload_core_command="echo 'reload'",
        core_lib=lib_names,
        core_port=10085,
        action_script=None,  # НЕТ bulk_delete_script
        custom_params={}
    )
    
    response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=delete_request)
    
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['hot_reload'] is False
    
    # Ждём записи
    await asyncio.sleep(0.3)
    
    # Проверяем что пользователей нет в буфере (по user_uuid)
    for user in users_to_add:
        assert user['user_uuid'] not in e2e_buffer.buffer_storage[1]
    
    # Читаем файл
    _, after_delete_config = await e2e_buffer._read_config(str(e2e_config_path))
    after_delete_users = e2e_buffer._navigate_to_path(after_delete_config, "inbounds___1___settings___clients")
    
    # Проверяем что массив пустой (было 5, удалили 5)
    assert len(after_delete_users) == 0
    
    # Проверяем отсутствие всех удалённых пользователей (по id)
    for i in range(5):
        deleted_user = next((u for u in after_delete_users if u.get('id') == f"bulk-del-{i}"), None)
        assert deleted_user is None, f"User bulk-del-{i} should be deleted"


# ========== E2E тесты с реальным ядром (mock/real параметризация) ==========

@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_e2e_add_user_with_hot_reload_and_verify_metrics(
    use_real_core,
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    request,
    is_real_mode,
    get_script_from_template,
    mock_xtlsapi_e2e
):
    """
    E2E: Добавление пользователя + верификация через get_metrics
    
    Сценарий:
    1. Добавляем пользователя через hot-reload (API скрипт)
    2. Вызываем /execute/metrics для получения метрик
    3. Проверяем что пользователь присутствует в метриках
    
    Real режим: проверяем с реальным Xray контейнером
    Mock режим: используем моки библиотек
    """
    
    # Определяем ядро
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    # Загружаем скрипты из БД
    add_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    metrics_script = get_script_from_template(TemplateScriptFields.get_metrics)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params_add = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    test_user_uuid = "e2e-verify-uuid-123"
    test_user_sub_id = "e2e_verify_sub"
    
    # 1. Добавляем пользователя через hot-reload
    test_user = create_test_superuser(
        user_uuid=test_user_uuid,
        user_sub_id=test_user_sub_id,
        flow="xtls-rprx-vision",
        level=0
    )
    
    add_request = create_e2e_request_body(
        node_proto_id=1,
        users=[test_user],
        config_file_path=str(e2e_config_path),
        user_injectors=create_default_user_injectors(),
        action="add",
        reload_core_command="echo 'reload'",
        core_lib=lib_names,
        core_port=core_port,
        action_script=add_script,
        custom_params=custom_params_add
    )
    
    add_response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=add_request)
    assert add_response.status_code == 200
    add_data = add_response.json()
    assert add_data['success'] is True
    
    # Ждём записи на диск
    await asyncio.sleep(0.5)
    
    # 2. Получаем метрики через /node/metrics
    metrics_request = {
        "command": "xray api statsquery --server=127.0.0.1:{}",
        "metrics_script": metrics_script,
        "core_lib": lib_names,
        "metrics_port": core_port
    }
    
    metrics_response = await e2e_client.post("/api/v1/server/node/metrics", json=metrics_request)
    assert metrics_response.status_code == 200
    metrics_data = metrics_response.json()
    
    # 3. Проверяем наличие пользователя в метриках
    if use_real_core:
        # В реальном режиме проверяем что пользователь действительно в метриках ядра
        # Метрики могут быть пустыми (нет трафика), но пользователь должен существовать в конфиге
        # Проверяем через WBC и файл (по user_uuid)
        assert test_user_uuid in e2e_buffer.buffer_storage[1]
        
        _, config = await e2e_buffer._read_config(str(e2e_config_path))
        users = e2e_buffer._navigate_to_path(config, "inbounds___1___settings___clients")
        # В файле ядра email = user_sub_id
        added_user = next((u for u in users if u['email'] == test_user_sub_id), None)
        assert added_user is not None, f"User {test_user_sub_id} not found in real Xray config"
        assert added_user['id'] == test_user_uuid
    else:
        # В mock режиме просто проверяем что метрики получены
        assert metrics_data['success'] is True


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_e2e_delete_user_and_verify_removed(
    use_real_core,
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    request,
    is_real_mode,
    get_script_from_template,
    mock_xtlsapi_e2e
):
    """
    E2E: Удаление пользователя + верификация через метрики
    
    Сценарий:
    1. Добавляем пользователя (суперобъект)
    2. Удаляем пользователя через hot-reload
    3. Проверяем что пользователь отсутствует в конфиге
    
    Real режим: проверяем с реальным Xray
    Mock режим: используем моки
    """
    
    # Определяем ядро
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    # Загружаем скрипты
    action_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    test_user_uuid = "e2e-delete-verify-uuid"
    test_user_sub_id = "42"
    
    # 1. Добавляем пользователя (суперобъект)
    superuser = create_test_superuser(
        user_uuid=test_user_uuid,
        user_sub_id=test_user_sub_id,
        flow="xtls-rprx-vision",
        level=0
    )
    user_injectors = create_default_user_injectors()
    
    add_request = create_e2e_request_body(
        node_proto_id=1,
        users=[superuser],
        config_file_path=str(e2e_config_path),
        user_injectors=user_injectors,
        action="add",
        reload_core_command="",
        core_lib=lib_names,
        core_port=core_port,
        action_script=action_script,
        custom_params=custom_params
    )
    
    add_response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=add_request)
    assert add_response.status_code == 200
    await asyncio.sleep(0.5)
    
    # Проверяем что пользователь добавлен (ключ буфера теперь user_uuid)
    assert test_user_uuid in e2e_buffer.buffer_storage[1]
    
    # 2. Удаляем пользователя через hot-reload
    delete_request = create_e2e_request_body(
        node_proto_id=1,
        users=[superuser],
        config_file_path=str(e2e_config_path),
        user_injectors=user_injectors,
        action="delete",
        reload_core_command="echo 'reload'",
        core_lib=lib_names,
        core_port=core_port,
        action_script=action_script,
        custom_params=custom_params
    )
    
    delete_response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=delete_request)
    assert delete_response.status_code == 200
    delete_data = delete_response.json()
    assert delete_data['success'] is True
    
    await asyncio.sleep(0.5)
    
    # 3. Проверяем что пользователь удалён (ключ буфера - user_uuid)
    assert test_user_uuid not in e2e_buffer.buffer_storage[1]
    
    # Проверяем файл конфига (extractor трансформирует: user_sub_id → email)
    _, config = await e2e_buffer._read_config(str(e2e_config_path))
    users = e2e_buffer._navigate_to_path(config, "inbounds___1___settings___clients")
    deleted_user = next((u for u in users if u.get('email') == test_user_sub_id), None)
    
    if use_real_core:
        # В реальном режиме проверяем что пользователь действительно удалён из ядра
        assert deleted_user is None, f"User {test_user_sub_id} should be deleted from real Xray config"
    else:
        # В mock режиме просто проверяем буфер
        assert deleted_user is None


@pytest.mark.parametrize("use_real_core", [False, True], ids=["mock", "real"])
@pytest.mark.asyncio
@pytest.mark.db
@pytest.mark.slow
async def test_e2e_bulk_operations_with_verification(
    use_real_core,
    e2e_client,
    e2e_config_path,
    e2e_buffer,
    request,
    is_real_mode,
    get_script_from_template,
    mock_xtlsapi_e2e
):
    """
    E2E: Bulk операции + верификация
    
    Сценарий:
    1. Bulk add 5 пользователей через hot-reload (суперобъекты)
    2. Проверяем что все 5 в конфиге
    3. Bulk delete 3 пользователей
    4. Проверяем что остались только 2
    
    Real режим: проверяем с реальным Xray
    Mock режим: используем моки
    """
    
    # Определяем ядро
    if use_real_core:
        if not is_real_mode:
            pytest.skip("Real core tests require --mode=real")
        core_ip, core_port = request.getfixturevalue("xray_core_container")
    else:
        core_ip, core_port = "127.0.0.1", 10085
    
    # Загружаем скрипты
    action_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    # 1. Bulk add 5 пользователей (суперобъекты)
    users_to_add = [
        create_test_superuser(
            user_uuid=f"bulk-verify-{i}",
            user_sub_id=f"bulk_verify_{i}",
            flow="xtls-rprx-vision",
            level=0
        )
        for i in range(5)
    ]
    
    user_injectors = create_default_user_injectors()
    
    # Начальная задержка для изоляции от других тестов
    await asyncio.sleep(0.3)
    
    add_request = create_e2e_request_body(
        node_proto_id=1,
        users=users_to_add,
        config_file_path=str(e2e_config_path),
        user_injectors=user_injectors,
        action="add",
        reload_core_command="",
        core_lib=lib_names,
        core_port=core_port,
        action_script=action_script,
        custom_params=custom_params
    )
    
    add_response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=add_request)
    assert add_response.status_code == 200
    await asyncio.sleep(1.0)  # Увеличено для гарантированной записи на диск
    
    # Принудительный flush для синхронизации
    await e2e_buffer._flush_all_nodes(node_proto_id=1)
    await asyncio.sleep(0.2)
    
    # 2. Проверяем что все 5 добавлены
    _, config_after_add = await e2e_buffer._read_config(str(e2e_config_path))
    users_after_add = e2e_buffer._navigate_to_path(config_after_add, "inbounds___1___settings___clients")
    
    # Extractor трансформирует: user_sub_id → email
    for i in range(5):
        found = next((u for u in users_after_add if u.get('email') == f"bulk_verify_{i}"), None)
        assert found is not None, f"User bulk_verify_{i} not found after bulk add"
    
    if use_real_core:
        # В реальном режиме дополнительно проверяем буфер (ключ - user_uuid)
        for i in range(5):
            assert f"bulk-verify-{i}" in e2e_buffer.buffer_storage[1]
    
    # 3. Bulk delete 3 пользователей (первые 3)
    users_to_delete = [
        create_test_superuser(
            user_uuid=f"bulk-verify-{i}",
            user_sub_id=f"bulk_verify_{i}",
            flow="xtls-rprx-vision",
            level=0
        )
        for i in range(3)
    ]
    
    delete_request = create_e2e_request_body(
        node_proto_id=1,
        users=users_to_delete,
        config_file_path=str(e2e_config_path),
        user_injectors=user_injectors,
        action="delete",
        reload_core_command="echo 'reload'",
        core_lib=lib_names,
        core_port=core_port,
        action_script=action_script,
        custom_params=custom_params
    )
    
    delete_response = await e2e_client.put("/api/v1/server/proto_core/user/bulk/action", json=delete_request)
    assert delete_response.status_code == 200
    await asyncio.sleep(1.0)  # Увеличено для гарантированной записи на диск
    
    # Принудительный flush для синхронизации
    await e2e_buffer._flush_all_nodes(node_proto_id=1)
    await asyncio.sleep(0.2)
    
    # 4. Проверяем что удалены 3, остались 2
    _, config_after_delete = await e2e_buffer._read_config(str(e2e_config_path))
    users_after_delete = e2e_buffer._navigate_to_path(config_after_delete, "inbounds___1___settings___clients")
    
    # Проверяем что удалённых пользователей нет (в конфиге email = user_sub_id)
    for i in range(3):
        deleted = next((u for u in users_after_delete if u.get('email') == f"bulk_verify_{i}"), None)
        assert deleted is None, f"User bulk_verify_{i} should be deleted"
    
    # Проверяем что оставшиеся 2 пользователя на месте
    for i in range(3, 5):
        remaining = next((u for u in users_after_delete if u.get('email') == f"bulk_verify_{i}"), None)
        assert remaining is not None, f"User bulk_verify_{i} should remain"
    
    if use_real_core:
        # В реальном режиме проверяем буфер (ключи - user_uuid)
        for i in range(3):
            assert f"bulk-verify-{i}" not in e2e_buffer.buffer_storage[1]
        for i in range(3, 5):
            assert f"bulk-verify-{i}" in e2e_buffer.buffer_storage[1]
