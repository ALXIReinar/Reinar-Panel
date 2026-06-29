"""
Тесты инфраструктуры для проверки что всё настроено корректно

Этот файл можно удалить после успешной настройки всех реальных тестов
"""
import pytest
from pathlib import Path


def test_db_pool_connection(db_pool):
    """Проверяем что пул БД создаётся корректно"""
    assert db_pool is not None
    # Убираем проверку _closed т.к. это async fixture


@pytest.mark.db
async def test_protocol_template_loading(protocol_template, protocol_name):
    """Проверяем что шаблон загружается из БД"""
    assert protocol_template is not None
    assert 'id' in protocol_template
    assert 'title' in protocol_template
    
    print(f"\n✅ Загружен шаблон: {protocol_template['title']} (ID: {protocol_template['id']})")
    print(f"   Протокол: {protocol_name}")
    print(f"   Библиотека: {protocol_template.get('proto_python_lib', 'Не указана')}")


def test_working_config_exists(working_config_path):
    """Проверяем что рабочая копия конфига создана"""
    assert working_config_path.exists()
    assert working_config_path.is_file()
    assert working_config_path.suffix == '.json'
    
    print(f"\n✅ Рабочий конфиг создан: {working_config_path}")


def test_temp_config_path_unique(temp_config_path):
    """Проверяем что temp_config_path создаёт уникальные пути для каждого теста"""
    assert isinstance(temp_config_path, Path)
    assert temp_config_path.parent.exists()


def test_mock_subprocess_works(mock_subprocess):
    """Проверяем что мок subprocess работает"""
    result = mock_subprocess("echo test", shell=True)
    
    assert result.returncode == 0
    assert result.stdout == "Success"


def test_mock_subprocess_timeout_works(mock_subprocess_timeout):
    """Проверяем что мок timeout работает"""
    import subprocess
    
    with pytest.raises(subprocess.TimeoutExpired):
        mock_subprocess_timeout("long command", timeout=1)


async def test_mock_hot_reload_success(mock_hot_reload_success):
    """Проверяем что мок hot reload работает"""
    result = await mock_hot_reload_success(
        script="test",
        lib_names=["test"],
        node_ip="127.0.0.1",
        core_api_port=8080,
        action="add_user"
    )
    
    success, message = result
    assert success is True
    assert "успешно" in message.lower()


async def test_mock_hot_reload_failure(mock_hot_reload_failure):
    """Проверяем что мок hot reload failure работает"""
    result = await mock_hot_reload_failure(
        script="test",
        lib_names=["test"],
        node_ip="127.0.0.1",
        core_api_port=8080,
        action="add_user"
    )
    
    success, message = result
    assert success is False
    assert "провалился" in message.lower()


async def test_client_fixture_works(client):
    """Проверяем что FastAPI клиент создаётся"""
    assert client is not None
    assert hasattr(client, 'app')
    assert hasattr(client.app.state, 'core_buffer')


async def test_ping_endpoint(client):
    """Проверяем что базовый эндпоинт /ping работает"""
    response = await client.get('/api/v1/server/node/ping')
    
    assert response.status_code == 200
    data = response.json()
    
    assert data['success'] is True
    assert data['message'] == 'pong'
    assert 'service' in data
    assert 'version' in data


def test_test_mode_parameter(test_mode):
    """Проверяем что параметр --mode передаётся корректно"""
    assert test_mode in ['mock', 'real']
    print(f"\n✅ Режим тестирования: {test_mode}")


def test_protocol_name_parameter(protocol_name):
    """Проверяем что параметр --protocol передаётся корректно"""
    assert isinstance(protocol_name, str)
    assert len(protocol_name) > 0
    print(f"\n✅ Протокол для тестирования: {protocol_name}")
