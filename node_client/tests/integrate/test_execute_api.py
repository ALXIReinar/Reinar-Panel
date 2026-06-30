"""
Integration тесты для эндпоинта выполнения команд node_client/api/execute_api.py

Тестируется эндпоинт:
- POST /node/execute - выполнение shell команд на ноде

Стратегия:
- Используем реальные команды (не моки subprocess)
- Тестируем Windows-специфичные команды (echo, dir, where)
- Мокируем только для timeout тестов
"""
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
    # Windows команда: cd (без аргументов выводит текущую директорию)
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "cd"
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
    # Команда которая ничего не выводит (создание пустого файла потом удаление)
    response = await client.post("/api/v1/server/node/execute", json={
        "command": "echo. > nul"
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
async def test_get_metrics_with_script_success(client):
    """Успешное получение метрик через скрипт get_metrics"""
    with patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor:
        # Мокируем успешный результат выполнения скрипта
        mock_metrics = '{"stat": [{"name": "user>>>test@test.com>>>traffic>>>uplink", "value": 1024}]}'
        mock_executor.return_value = (True, mock_metrics)
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": "async def get_metrics(node_ip, core_port, custom_params): return 'metrics'",
            "core_lib": ["xtlsapi"],
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["stdout"] == mock_metrics
        
        # Проверяем что HotReloadExecutor был вызван с правильными параметрами
        mock_executor.assert_called_once()
        call_kwargs = mock_executor.call_args[1]
        assert call_kwargs["action"] == "get_metrics"
        assert call_kwargs["node_ip"] == "127.0.0.1"
        assert call_kwargs["core_api_port"] == 10085


@pytest.mark.asyncio
async def test_get_metrics_fallback_to_cli(client):
    """Fallback на CLI команду когда скрипт провалился"""
    with patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor, \
         patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        # Скрипт провалился
        mock_executor.return_value = (False, "Script failed")
        
        # CLI команда успешна
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"stat": [{"name": "user>>>cli@test.com>>>traffic>>>downlink", "value": 2048}]}'
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": "async def get_metrics(): raise Exception('fail')",
            "core_lib": ["xtlsapi"],
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "cli@test.com" in data["stdout"]
        
        # Проверяем что CLI команда была вызвана
        mock_subprocess.assert_called_once()


@pytest.mark.asyncio
async def test_get_metrics_no_script_uses_cli(client):
    """Использование CLI когда скрипт не передан"""
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = 'metrics from cli'
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": None,  # Нет скрипта
            "core_lib": [],
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["stdout"] == "metrics from cli"


@pytest.mark.asyncio
async def test_get_metrics_cli_command_timeout(client):
    """408 при timeout CLI команды"""
    with patch('node_client.api.execute_api.HotReloadExecutor.execute_action_script') as mock_executor, \
         patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        # Скрипт провалился или отсутствует
        mock_executor.return_value = (False, "No script")
        
        # CLI команда timeout
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd="xray api statsquery",
            timeout=10
        )
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": None,
            "core_lib": [],
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}"
        })
        
        assert response.status_code == 408
        data = response.json()
        
        assert data["detail"]["success"] is False
        assert "timeout" in data["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_get_metrics_cli_non_zero_exit(client):
    """400 при ненулевом exit code CLI команды"""
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "xray: command not found"
        mock_subprocess.return_value = mock_result
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": None,
            "core_lib": [],
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}"
        })
        
        assert response.status_code == 400
        data = response.json()
        
        assert data["detail"]["error"] == "Failed to get stats"
        assert data["detail"]["exit_code"] == 1


@pytest.mark.asyncio
async def test_get_metrics_exception_handling(client):
    """500 при непредвиденной ошибке"""
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        # Симулируем непредвиденное исключение
        mock_subprocess.side_effect = RuntimeError("Unexpected error")
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": None,
            "core_lib": [],
            "metrics_port": 10085,
            "command": "xray api statsquery --server=127.0.0.1:{}"
        })
        
        assert response.status_code == 500
        data = response.json()
        
        assert data["detail"]["success"] is False
        assert "ошибка" in data["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_get_metrics_command_formatting(client):
    """Проверка правильного форматирования команды с портом"""
    with patch('node_client.api.execute_api.subprocess.run') as mock_subprocess:
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "metrics"
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        response = await client.post("/api/v1/server/node/metrics", json={
            "metrics_script": None,
            "core_lib": [],
            "metrics_port": 12345,
            "command": "xray api statsquery --server=127.0.0.1:{} -pattern user"
        })
        
        assert response.status_code == 200
        
        # Проверяем что команда была отформатирована с портом
        call_args = mock_subprocess.call_args
        command_parts = call_args[0][0]  # Первый позиционный аргумент
        
        # Команда должна содержать порт 12345
        full_command = ' '.join(command_parts)
        assert '12345' in full_command
