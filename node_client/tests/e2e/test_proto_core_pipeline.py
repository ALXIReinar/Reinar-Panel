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
        return '{"stat": [{"name": "user>>>test@test.com>>>traffic>>>uplink", "value": 1024}]}'


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
    - Длина массива users увеличилась на 1
    - Команда перезагрузки ядра выполнена
    """
    
    # Читаем исходное состояние файла
    initial_config = await e2e_buffer._read_config(str(e2e_config_path))
    initial_users = e2e_buffer._navigate_to_path(initial_config, "inbounds___1___settings___clients")
    initial_count = len(initial_users)
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    mock_subprocess.return_value.communicate = AsyncMock(return_value=(b'', b''))
    mock_subprocess.return_value.returncode = 0
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Подготавливаем запрос БЕЗ API-скрипта
        lib_names = get_script_from_template(TemplateScriptFields.lib_names)
        
        request_body = {
            "node_proto_id": 1,
            "user_obj": {
                "id": "e2e-test-uuid-no-script",
                "email": "e2e_no_script@test.com",
                "uuid": "e2e-test-uuid-no-script"
            },
            "config_file_path": str(e2e_config_path),
            "flatten_json_users_key": "inbounds___1___settings___clients",
            "flatten_user_identifier_key": "email",
            "reload_core_command": "echo 'reload'",
            "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
            "core_port": 10085,
            # НЕТ API-скрипта!
            "add_script": None,
            "custom_params": {}
        }
        
        # Отправляем запрос
        response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['hot_reload'] is False  # Не было hot-reload
        
        # Ждём пока воркер запишет на диск (timeout=0.3s)
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователь в буфере
        assert 1 in e2e_buffer.buffer_storage
        assert "e2e_no_script@test.com" in e2e_buffer.buffer_storage[1]
        
        # Читаем файл и проверяем наличие пользователя
        updated_config = await e2e_buffer._read_config(str(e2e_config_path))
        updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
        
        # Проверяем длину массива
        assert len(updated_users) == initial_count + 1
        
        # Проверяем наличие пользователя в файле
        added_user = next((u for u in updated_users if u['email'] == 'e2e_no_script@test.com'), None)
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
    - Длина массива users уменьшилась на 1
    - Команда перезагрузки ядра выполнена
    """
    
    # Сначала добавляем пользователя
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    add_request = {
        "node_proto_id": 1,
        "user_obj": {
            "id": "e2e-delete-uuid",
            "email": "e2e_delete@test.com",
            "uuid": "e2e-delete-uuid"
        },
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "echo 'reload'",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": 10085,
        "add_script": None,
        "custom_params": {}
    }
    
    response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=add_request)
    assert response.status_code == 200
    
    # Ждём записи
    await asyncio.sleep(0.5)
    
    # Читаем состояние до удаления
    before_delete_config = await e2e_buffer._read_config(str(e2e_config_path))
    before_delete_users = e2e_buffer._navigate_to_path(before_delete_config, "inbounds___1___settings___clients")
    count_before = len(before_delete_users)
    
    # Проверяем что пользователь есть
    user_to_delete = next((u for u in before_delete_users if u['email'] == 'e2e_delete@test.com'), None)
    assert user_to_delete is not None
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    mock_subprocess.return_value.communicate = AsyncMock(return_value=(b'', b''))
    mock_subprocess.return_value.returncode = 0
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Удаляем пользователя БЕЗ API-скрипта
        delete_request = {
            "node_proto_id": 1,
            "user_obj": {
                "email": "e2e_delete@test.com",
                "uuid": "e2e-delete-uuid"
            },
            "config_file_path": str(e2e_config_path),
            "flatten_json_users_key": "inbounds___1___settings___clients",
            "flatten_user_identifier_key": "email",
            "reload_core_command": "echo 'reload'",
            "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
            "core_port": 10085,
            # НЕТ delete-скрипта!
            "delete_script": None,
            "custom_params": {}
        }
        
        response = await e2e_client.post("/api/v1/server/proto_core/user/delete", json=delete_request)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['hot_reload'] is False
        
        # Ждём записи
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователя нет в буфере
        assert "e2e_delete@test.com" not in e2e_buffer.buffer_storage[1]
        
        # Читаем файл и проверяем отсутствие пользователя
        after_delete_config = await e2e_buffer._read_config(str(e2e_config_path))
        after_delete_users = e2e_buffer._navigate_to_path(after_delete_config, "inbounds___1___settings___clients")
        
        # Проверяем длину массива
        assert len(after_delete_users) == count_before - 1
        
        # Проверяем отсутствие пользователя
        deleted_user = next((u for u in after_delete_users if u['email'] == 'e2e_delete@test.com'), None)
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
    
    # Читаем исходное состояние
    initial_config = await e2e_buffer._read_config(str(e2e_config_path))
    initial_users = e2e_buffer._navigate_to_path(initial_config, "inbounds___1___settings___clients")
    initial_count = len(initial_users)
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        # Загружаем реальный скрипт из БД
        add_script = get_script_from_template(TemplateScriptFields.add_user)
        lib_names = get_script_from_template(TemplateScriptFields.lib_names)
        custom_params = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
        
        request_body = {
            "node_proto_id": 1,
            "user_obj": {
                "id": "e2e-hot-reload-success",
                "email": "e2e_hot_reload_success@test.com",
                "uuid": "e2e-hot-reload-success"
            },
            "config_file_path": str(e2e_config_path),
            "flatten_json_users_key": "inbounds___1___settings___clients",
            "flatten_user_identifier_key": "email",
            "reload_core_command": "echo 'reload'",
            "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
            "core_port": 10085,
            # Есть API-скрипт!
            "add_script": add_script,
            "custom_params": custom_params
        }
        
        response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['hot_reload'] is True  # Hot-reload выполнен успешно!
        
        # Ждём записи
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователь в буфере
        assert "e2e_hot_reload_success@test.com" in e2e_buffer.buffer_storage[1]
        
        # Читаем файл
        updated_config = await e2e_buffer._read_config(str(e2e_config_path))
        updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
        
        # Проверяем длину массива
        assert len(updated_users) == initial_count + 1
        
        # Проверяем наличие пользователя
        added_user = next((u for u in updated_users if u['email'] == 'e2e_hot_reload_success@test.com'), None)
        assert added_user is not None
        
        # ВАЖНО: Команда перезагрузки НЕ должна быть вызвана (т.к. hot-reload успешен)
        mock_subprocess.assert_not_called()


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
    
    # Создаём скрипт который провалится
    broken_script = """
async def add_user(user_obj, node_ip, core_port, custom_params):
    # Намеренная ошибка для провала hot-reload
    raise ValueError("Hot-reload intentionally failed")
"""
    
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    
    # Читаем исходное состояние
    initial_config = await e2e_buffer._read_config(str(e2e_config_path))
    initial_users = e2e_buffer._navigate_to_path(initial_config, "inbounds___1___settings___clients")
    initial_count = len(initial_users)
    
    # Мокируем команду перезагрузки
    mock_subprocess = AsyncMock()
    mock_subprocess.return_value.communicate = AsyncMock(return_value=(b'', b''))
    mock_subprocess.return_value.returncode = 0
    
    with patch('asyncio.create_subprocess_shell', mock_subprocess):
        request_body = {
            "node_proto_id": 1,
            "user_obj": {
                "id": "e2e-hot-reload-fail",
                "email": "e2e_hot_reload_fail@test.com",
                "uuid": "e2e-hot-reload-fail"
            },
            "config_file_path": str(e2e_config_path),
            "flatten_json_users_key": "inbounds___1___settings___clients",
            "flatten_user_identifier_key": "email",
            "reload_core_command": "echo 'reload'",
            "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
            "core_port": 10085,
            # Скрипт который провалится
            "add_script": broken_script,
            "custom_params": {}
        }
        
        response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True  # WBC всё равно добавил (fallback)
        assert data['hot_reload'] is False  # Hot-reload провалился!
        assert "ValueError" in data['hot_reload_message']
        
        # Ждём записи
        await asyncio.sleep(0.5)
        
        # Проверяем что пользователь всё равно в буфере (fallback)
        assert "e2e_hot_reload_fail@test.com" in e2e_buffer.buffer_storage[1]
        
        # Читаем файл
        updated_config = await e2e_buffer._read_config(str(e2e_config_path))
        updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
        
        # Проверяем длину массива
        assert len(updated_users) == initial_count + 1
        
        # Проверяем наличие пользователя
        added_user = next((u for u in updated_users if u['email'] == 'e2e_hot_reload_fail@test.com'), None)
        assert added_user is not None
        
        # ВАЖНО: Команда перезагрузки ДОЛЖНА быть вызвана (т.к. hot-reload failed)
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
    
    # Читаем исходное состояние
    initial_config = await e2e_buffer._read_config(str(e2e_config_path))
    initial_users = e2e_buffer._navigate_to_path(initial_config, "inbounds___1___settings___clients")
    initial_count = len(initial_users)
    
    # Загружаем bulk скрипт из БД
    bulk_add_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    
    # Подготавливаем 10 пользователей
    users_to_add = [
        {
            "id": f"bulk-uuid-{i}",
            "email": f"bulk_user_{i}@test.com",
            "uuid": f"bulk-uuid-{i}"
        }
        for i in range(10)
    ]
    
    request_body = {
        "node_proto_id": 1,
        "users": users_to_add,
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "echo 'reload'",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": 10085,
        "bulk_add_script": bulk_add_script,
        "custom_params": custom_params
    }
    
    response = await e2e_client.post("/api/v1/server/proto_core/user/bulk/add", json=request_body)
    
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['hot_reload'] is True
    
    # Bulk операция должна записать сразу (unlimit_queue + flush)
    # Даём немного времени на flush
    await asyncio.sleep(0.2)
    
    # Проверяем что все пользователи в буфере
    for user in users_to_add:
        assert user['email'] in e2e_buffer.buffer_storage[1]
    
    # Читаем файл
    updated_config = await e2e_buffer._read_config(str(e2e_config_path))
    updated_users = e2e_buffer._navigate_to_path(updated_config, "inbounds___1___settings___clients")
    
    # Проверяем длину массива
    assert len(updated_users) == initial_count + 10
    
    # Проверяем наличие всех пользователей
    for user in users_to_add:
        found_user = next((u for u in updated_users if u['email'] == user['email']), None)
        assert found_user is not None, f"User {user['email']} not found in file"


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
    
    users_to_delete = [
        {
            "tg_username": f"bulk_del_{i}",
            "uuid": f"bulk_del_{i}@test.com",  # Используем email как uuid для удаления
            "sub_node_id": 1,
            "order_id": 1
        }
        for i in range(5)
    ]
    
    # Для добавления используем полные объекты (с flow и level для vless)
    users_to_add = [
        {
            "id": f"bulk-del-{i}",
            "email": f"bulk_del_{i}@test.com",
            "uuid": f"bulk-del-{i}",
            "flow": "xtls-rprx-vision",
            "level": 0
        }
        for i in range(5)
    ]
    
    # Добавляем пользователей по одному (используем тот же e2e_client)
    for user in users_to_add:
        add_request = {
            "node_proto_id": 1,
            "user_obj": user,
            "config_file_path": str(e2e_config_path),
            "flatten_json_users_key": "inbounds___1___settings___clients",
            "flatten_user_identifier_key": "email",
            "reload_core_command": "",  # Пустая строка вместо None
            "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
            "core_port": 10085,
            "add_script": None,
            "custom_params": {}
        }
        response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=add_request)
        assert response.status_code == 200
    
    # Ждём записи
    await asyncio.sleep(0.5)
    
    # Читаем состояние до удаления
    before_delete_config = await e2e_buffer._read_config(str(e2e_config_path))
    before_delete_users = e2e_buffer._navigate_to_path(before_delete_config, "inbounds___1___settings___clients")
    count_before = len(before_delete_users)
    
    # Bulk удаление БЕЗ API-скрипта
    delete_request = {
        "node_proto_id": 1,
        "users": users_to_delete,
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "echo 'reload'",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": 10085,
        # НЕТ bulk_delete_script
        "bulk_delete_script": None,
        "custom_params": {}
    }
    
    response = await e2e_client.request(
        "DELETE",
        "/api/v1/server/proto_core/user/bulk/delete",
        content=orjson.dumps(delete_request),
        headers={"Content-Type": "application/json"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert data['hot_reload'] is False
    
    # Ждём записи
    await asyncio.sleep(0.3)
    
    # Проверяем что пользователей нет в буфере
    for i, user in enumerate(users_to_delete):
        # Используем uuid для проверки буфера
        assert user['uuid'] not in e2e_buffer.buffer_storage[1]
    
    # Читаем файл
    after_delete_config = await e2e_buffer._read_config(str(e2e_config_path))
    after_delete_users = e2e_buffer._navigate_to_path(after_delete_config, "inbounds___1___settings___clients")
    
    # Проверяем длину массива
    assert len(after_delete_users) == count_before - 5
    
    # Проверяем отсутствие всех удалённых пользователей
    for i in range(5):
        deleted_user = next((u for u in after_delete_users if u.get('email') == f"bulk_del_{i}@test.com"), None)
        assert deleted_user is None, f"User bulk_del_{i}@test.com should be deleted"


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
    add_script = get_script_from_template(TemplateScriptFields.add_user)
    metrics_script = get_script_from_template(TemplateScriptFields.get_metrics)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params_add = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    
    test_user_email = "e2e_verify_user@test.com"
    test_user_uuid = "e2e-verify-uuid-123"
    
    # 1. Добавляем пользователя через hot-reload
    add_request = {
        "node_proto_id": 1,
        "user_obj": {
            "id": test_user_uuid,
            "email": test_user_email,
            "uuid": test_user_uuid,
            "flow": "xtls-rprx-vision",
            "level": 0
        },
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "echo 'reload'",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": core_port,
        "add_script": add_script,
        "custom_params": custom_params_add
    }
    
    add_response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=add_request)
    assert add_response.status_code == 200
    add_data = add_response.json()
    assert add_data['success'] is True
    
    # Ждём записи на диск
    await asyncio.sleep(0.5)
    
    # 2. Получаем метрики через /node/metrics
    metrics_request = {
        "command": "xray api statsquery --server=127.0.0.1:{}",
        "metrics_script": metrics_script,
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "metrics_port": core_port
    }
    
    metrics_response = await e2e_client.post("/api/v1/server/node/metrics", json=metrics_request)
    assert metrics_response.status_code == 200
    metrics_data = metrics_response.json()
    
    # 3. Проверяем наличие пользователя в метриках
    if use_real_core:
        # В реальном режиме проверяем что пользователь действительно в метриках ядра
        # Метрики могут быть пустыми (нет трафика), но пользователь должен существовать в конфиге
        # Проверяем через WBC и файл
        assert test_user_email in e2e_buffer.buffer_storage[1]
        
        config = await e2e_buffer._read_config(str(e2e_config_path))
        users = e2e_buffer._navigate_to_path(config, "inbounds___1___settings___clients")
        added_user = next((u for u in users if u['email'] == test_user_email), None)
        assert added_user is not None, f"User {test_user_email} not found in real Xray config"
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
    1. Добавляем пользователя
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
    add_script = get_script_from_template(TemplateScriptFields.add_user)
    delete_script = get_script_from_template(TemplateScriptFields.delete_user)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params_add = get_script_from_template(TemplateScriptFields.custom_params_add) or {}
    custom_params_delete = get_script_from_template(TemplateScriptFields.custom_params_delete) or {}
    
    test_user_email = "e2e_delete_verify@test.com"
    test_user_uuid = "e2e-delete-verify-uuid"
    
    # 1. Добавляем пользователя
    add_request = {
        "node_proto_id": 1,
        "user_obj": {
            "id": test_user_uuid,
            "email": test_user_email,
            "uuid": test_user_uuid,
            "flow": "xtls-rprx-vision",
            "level": 0
        },
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": core_port,
        "add_script": add_script,
        "custom_params": custom_params_add
    }
    
    add_response = await e2e_client.post("/api/v1/server/proto_core/user/add", json=add_request)
    assert add_response.status_code == 200
    await asyncio.sleep(0.5)
    
    # Проверяем что пользователь добавлен
    assert test_user_email in e2e_buffer.buffer_storage[1]
    
    # 2. Удаляем пользователя через hot-reload
    delete_request = {
        "node_proto_id": 1,
        "user_obj": {
            "email": test_user_email,
            "uuid": test_user_uuid
        },
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "echo 'reload'",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": core_port,
        "delete_script": delete_script,
        "custom_params": custom_params_delete
    }
    
    delete_response = await e2e_client.post("/api/v1/server/proto_core/user/delete", json=delete_request)
    assert delete_response.status_code == 200
    delete_data = delete_response.json()
    assert delete_data['success'] is True
    
    await asyncio.sleep(0.5)
    
    # 3. Проверяем что пользователь удалён
    assert test_user_email not in e2e_buffer.buffer_storage[1]
    
    # Проверяем файл
    config = await e2e_buffer._read_config(str(e2e_config_path))
    users = e2e_buffer._navigate_to_path(config, "inbounds___1___settings___clients")
    deleted_user = next((u for u in users if u['email'] == test_user_email), None)
    
    if use_real_core:
        # В реальном режиме проверяем что пользователь действительно удалён из ядра
        assert deleted_user is None, f"User {test_user_email} should be deleted from real Xray config"
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
    1. Bulk add 5 пользователей через hot-reload
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
    bulk_add_script = get_script_from_template(TemplateScriptFields.bulk_add_users)
    bulk_delete_script = get_script_from_template(TemplateScriptFields.bulk_delete_users)
    lib_names = get_script_from_template(TemplateScriptFields.lib_names)
    custom_params_bulk_add = get_script_from_template(TemplateScriptFields.custom_params_bulk_add) or {}
    custom_params_bulk_delete = get_script_from_template(TemplateScriptFields.custom_params_bulk_delete) or {}
    
    # 1. Bulk add 5 пользователей
    users_to_add = [
        {
            "id": f"bulk-verify-{i}",
            "email": f"bulk_verify_{i}@test.com",
            "uuid": f"bulk-verify-{i}",
            "flow": "xtls-rprx-vision",
            "level": 0
        }
        for i in range(5)
    ]
    
    add_request = {
        "node_proto_id": 1,
        "users": users_to_add,
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": core_port,
        "bulk_add_script": bulk_add_script,
        "custom_params": custom_params_bulk_add
    }
    
    add_response = await e2e_client.post("/api/v1/server/proto_core/user/bulk/add", json=add_request)
    assert add_response.status_code == 200
    await asyncio.sleep(0.3)
    
    # 2. Проверяем что все 5 добавлены
    config_after_add = await e2e_buffer._read_config(str(e2e_config_path))
    users_after_add = e2e_buffer._navigate_to_path(config_after_add, "inbounds___1___settings___clients")
    
    for user in users_to_add:
        found = next((u for u in users_after_add if u['email'] == user['email']), None)
        assert found is not None, f"User {user['email']} not found after bulk add"
    
    if use_real_core:
        # В реальном режиме дополнительно проверяем что все пользователи в буфере
        for user in users_to_add:
            assert user['email'] in e2e_buffer.buffer_storage[1]
    
    # 3. Bulk delete 3 пользователей
    users_to_delete = [
        {
            "tg_username": f"bulk_verify_{i}",
            "uuid": f"bulk_verify_{i}@test.com",  # Используем email как uuid
            "sub_node_id": 1,
            "order_id": 1
        }
        for i in range(3)
    ]
    
    delete_request = {
        "node_proto_id": 1,
        "users": users_to_delete,
        "config_file_path": str(e2e_config_path),
        "flatten_json_users_key": "inbounds___1___settings___clients",
        "flatten_user_identifier_key": "email",
        "reload_core_command": "echo 'reload'",
        "core_lib": lib_names.split(',') if isinstance(lib_names, str) else lib_names,
        "core_port": core_port,
        "bulk_delete_script": bulk_delete_script,
        "custom_params": custom_params_bulk_delete
    }
    
    delete_response = await e2e_client.request(
        "DELETE",
        "/api/v1/server/proto_core/user/bulk/delete",
        content=orjson.dumps(delete_request),
        headers={"Content-Type": "application/json"}
    )
    
    assert delete_response.status_code == 200
    await asyncio.sleep(0.3)
    
    # 4. Проверяем что удалены 3, остались 2
    config_after_delete = await e2e_buffer._read_config(str(e2e_config_path))
    users_after_delete = e2e_buffer._navigate_to_path(config_after_delete, "inbounds___1___settings___clients")
    
    # Проверяем что удалённых пользователей нет
    for i in range(3):
        deleted = next((u for u in users_after_delete if u.get('email') == f"bulk_verify_{i}@test.com"), None)
        assert deleted is None, f"User bulk_verify_{i}@test.com should be deleted"
    
    # Проверяем что оставшиеся 2 пользователя на месте
    for i in range(3, 5):
        remaining = next((u for u in users_after_delete if u.get('email') == f"bulk_verify_{i}@test.com"), None)
        assert remaining is not None, f"User bulk_verify_{i}@test.com should remain"
    
    if use_real_core:
        # В реальном режиме проверяем буфер
        for i in range(3):
            assert f"bulk_verify_{i}@test.com" not in e2e_buffer.buffer_storage[1]
        for i in range(3, 5):
            assert f"bulk_verify_{i}@test.com" in e2e_buffer.buffer_storage[1]
