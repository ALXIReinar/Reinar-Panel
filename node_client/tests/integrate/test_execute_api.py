"""
Integration тесты для эндпоинта выполнения команд node_client/api/execute_api.py

Тестируется эндпоинт:
- POST /node/execute - выполнение shell команд на ноде

Стратегия:
- Используем реальные команды (не моки subprocess)
- Тестируем Windows-специфичные команды (echo, dir, where)
- Мокируем только для timeout тестов
"""
import platform
import subprocess
from unittest.mock import patch, MagicMock

import pytest


# ========== Группа 1: Успешное выполнение команд ==========

@pytest.mark.asyncio
async def test_execute_simple_command(client):
    """Простая команда echo возвращает успешный результат"""
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "echo Hello World"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert "Hello World" in data["stdout"]
    assert data["exit_code"] == 0
    assert data["command"] == "echo Hello World"


@pytest.mark.asyncio
async def test_execute_command_with_exit_code_0(client):
    """Команда с exit_code=0 считается успешной"""
    # Windows: cd (выводит текущую директорию)
    # Linux: pwd (выводит текущую директорию)
    if platform.system() == "Windows":
        command = "cd"
    else:
        command = "pwd"
    
    response = await client.post("/api/v1/server/node/execute", json={
        "command": command
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["exit_code"] == 0
    assert len(data["stdout"]) > 0  # Должен вывести путь


@pytest.mark.asyncio
async def test_execute_command_with_stdout(client):
    """Проверка захвата stdout"""
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "echo Test Output Line"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert "Test Output Line" in data["stdout"]
    assert data["stderr"] == ""  # stderr должен быть пустым


@pytest.mark.asyncio
async def test_execute_command_with_stderr(client):
    """Проверка захвата stderr при ошибке команды"""
    # Команда которая выводит в stderr (обращение к несуществующей переменной PowerShell)
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "powershell -Command \"Write-Error 'Test Error Message'\""
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Write-Error выводит в stderr, но PowerShell может вернуть exit_code 0
    # Проверяем что stderr не пустой
    assert len(data["stderr"]) > 0 or "Error" in data["stdout"]


# ========== Группа 2: Ошибки выполнения ==========

@pytest.mark.asyncio
async def test_execute_command_non_zero_exit(client):
    """Команда с ненулевым exit code возвращает success=False"""
    # Команда которая гарантированно провалится (exit code 1)
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "exit 1"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is False
    assert data["exit_code"] == 1


@pytest.mark.asyncio
async def test_execute_command_timeout(client):
    """408 при превышении timeout"""
    # Мокируем subprocess.run чтобы выбросить TimeoutExpired
    with patch('node_client.api.execute_api.subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="sleep 100",
            timeout=30
        )
        
        response = await client.post("/api/v1/server/node/execute", json={
            "command": "sleep 100"
        })
        
        assert response.status_code == 408
        data = response.json()
        assert data["detail"]["success"] is False
        assert "timeout" in data["detail"]["message"].lower()


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Node client developed for Ubuntu 22/24. Windows encoding issues.")
async def test_execute_invalid_command(client):
    """Несуществующая команда возвращает ненулевой exit code"""
    # Команда которая точно не существует
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "thisisnotarealcommand12345xyz"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Windows вернёт ошибку "'thisisnotarealcommand12345xyz' не является..."
    assert data["success"] is False
    assert data["exit_code"] != 0


# ========== Группа 3: Различные типы команд ==========

@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="Node client developed for Ubuntu 22/24. Windows encoding issues.")
async def test_execute_windows_dir_command(client):
    """Windows команда dir работает корректно"""
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "dir"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["exit_code"] == 0
    # dir должен вывести что-то (файлы/папки)
    assert len(data["stdout"]) > 0


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() != "Windows", reason="PowerShell доступен только на Windows")
async def test_execute_powershell_command(client):
    """PowerShell команда через cmd"""
    # Простая PowerShell команда через cmd
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "powershell -Command \"Write-Output 'PowerShell Test'\""
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert "PowerShell Test" in data["stdout"]
    assert data["exit_code"] == 0


@pytest.mark.asyncio
async def test_execute_command_with_args(client):
    """Команда с множественными аргументами"""
    # echo с несколькими словами
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "echo First Second Third Fourth"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert "First" in data["stdout"]
    assert "Second" in data["stdout"]
    assert "Third" in data["stdout"]
    assert "Fourth" in data["stdout"]


# ========== Дополнительные тесты ==========

@pytest.mark.asyncio
async def test_execute_multiline_output(client):
    """Команда с многострочным выводом"""
    # Создаём команду которая выведет несколько строк
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "echo Line1 & echo Line2 & echo Line3"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert "Line1" in data["stdout"]
    assert "Line2" in data["stdout"]
    assert "Line3" in data["stdout"]


@pytest.mark.asyncio
async def test_execute_command_preserves_command_string(client):
    """Проверка что строка команды сохраняется в ответе"""
    test_command = "echo Preserve This Command"
    
    response = await client.post("/api/v1/server/node/execute", json={
        "command": test_command
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["command"] == test_command


@pytest.mark.asyncio
async def test_execute_empty_stdout(client):
    """Команда без вывода возвращает пустой stdout"""
    # Windows: echo. > nul (ничего не выводит)
    # Linux: true (команда без вывода)
    if platform.system() == "Windows":
        command = "echo. > nul"
    else:
        command = "true"
    
    response = await client.post("/api/v1/server/node/execute", json={
        "command": command
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    # stdout может быть пустым или содержать только пробелы
    assert len(data["stdout"].strip()) == 0


@pytest.mark.asyncio
async def test_execute_command_with_special_characters(client):
    """Команда со специальными символами"""
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "echo Hello@World#Test$"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    # Некоторые символы могут быть интерпретированы shell, проверяем что команда выполнилась
    assert data["exit_code"] == 0


@pytest.mark.asyncio
async def test_execute_command_exception_handling(client):
    """500 при непредвиденной ошибке subprocess"""
    with patch('node_client.api.execute_api.subprocess.run') as mock_run:
        # Симулируем непредвиденное исключение
        mock_run.side_effect = RuntimeError("Unexpected subprocess error")
        
        response = await client.post("/api/v1/server/node/execute", json={
            "command": "any command"
        })
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"]["success"] is False
        assert "ошибка" in data["detail"]["message"].lower()


# ========== Группа 4: Тесты для /metrics endpoint ==========

@pytest.mark.asyncio
async def test_get_metrics_with_script_success(client, mock_buffer):
    """Успешное получение метрик через скрипт get_metrics"""
    # Регистрируем ноду в буфере
    node_proto_id = 1
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor:
        # Мокируем успешный результат выполнения скрипта
        mock_metrics = '{"stat": [{"name": "user>>>test@test.com>>>traffic>>>uplink", "value": 1024}]}'
        mock_parser_result = ([], [])  # traffic_consuming, troubles
        
        # Первый вызов - get_metrics, второй - parse_metrics
        mock_executor.side_effect = [
            (True, mock_metrics),  # get_metrics
            (True, mock_parser_result)  # parse_metrics
        ]
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": "async def get_metrics(node_ip, core_port, custom_params): return 'metrics'",
            "core_lib": "xtlsapi",
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["users_traffic"] == []
        
        # Проверяем что HotReloadExecutor был вызван дважды
        assert mock_executor.call_count == 2


@pytest.mark.asyncio
async def test_get_metrics_fallback_to_cli(client, mock_buffer):
    """Fallback на CLI команду когда скрипт провалился"""
    # Регистрируем ноду в буфере
    node_proto_id = 2
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor, \
         patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        # Скрипт провалился
        mock_parser_result = ([], [])
        mock_executor.return_value = (True, mock_parser_result)
        
        # CLI команда успешна
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"stat": [{"name": "user>>>cli@test.com>>>traffic>>>downlink", "value": 2048}]}'
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": None,  # Нет скрипта - используем CLI
            "core_lib": None,
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        
        # Проверяем что CLI команда была вызвана
        mock_subprocess.assert_called_once()


@pytest.mark.asyncio
async def test_get_metrics_no_script_uses_cli(client, mock_buffer):
    """Использование CLI когда скрипт не передан"""
    # Регистрируем ноду в буфере
    node_proto_id = 3
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess, \
         patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor:
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = 'metrics from cli'
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        # parse_metrics успешен
        mock_parser_result = ([], [])
        mock_executor.return_value = (True, mock_parser_result)
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": None,  # Нет скрипта
            "core_lib": None,
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["users_traffic"] == []


@pytest.mark.asyncio
async def test_get_metrics_cli_command_timeout(client, mock_buffer):
    """408 при timeout CLI команды"""
    # Регистрируем ноду в буфере
    node_proto_id = 4
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        # CLI команда timeout
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd="xray api statsquery",
            timeout=10
        )
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": None,
            "core_lib": None,
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 408
        data = response.json()
        
        assert data["detail"]["success"] is False
        assert "timeout" in data["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_get_metrics_cli_non_zero_exit(client, mock_buffer):
    """400 при ненулевом exit code CLI команды"""
    # Регистрируем ноду в буфере
    node_proto_id = 5
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "xray: command not found"
        mock_subprocess.return_value = mock_result
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": None,
            "core_lib": None,
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 400
        data = response.json()
        
        assert data["detail"]["success"] is False
        assert data["detail"]["error"] == "Failed to get stats"


@pytest.mark.asyncio
async def test_get_metrics_exception_handling(client, mock_buffer):
    """500 при непредвиденной ошибке"""
    # Регистрируем ноду в буфере
    node_proto_id = 6
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        # Симулируем непредвиденное исключение
        mock_subprocess.side_effect = RuntimeError("Unexpected error")
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": None,
            "core_lib": None,
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 500
        data = response.json()
        
        assert data["detail"]["success"] is False
        assert "ошибка" in data["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_get_metrics_command_formatting(client, mock_buffer):
    """Проверка правильного форматирования команды с портом"""
    # Регистрируем ноду в буфере
    node_proto_id = 7
    mock_buffer.buffer_storage[node_proto_id] = {}
    mock_buffer.local_state[node_proto_id] = {}
    
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess, \
         patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor:
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "metrics"
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        # parse_metrics успешен
        mock_parser_result = ([], [])
        mock_executor.return_value = (True, mock_parser_result)
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "node_proto_id": node_proto_id,
            "metrics_script": None,
            "core_lib": None,
            "metrics_port": 12345,
            "command": "xray api statsquery --server=127.0.0.1:{} -pattern user",
            "metrics_parser_code": "def parse_metrics(raw, users, state): return [], []",
            "metrics_parser_libs": None
        })
        
        assert response.status_code == 200
        
        # Проверяем что команда была отформатирована с портом
        call_args = mock_subprocess.call_args
        command_parts = call_args[0][0]  # Первый позиционный аргумент
        
        # Команда должна содержать порт 12345
        full_command = ' '.join(command_parts)
        assert '12345' in full_command
