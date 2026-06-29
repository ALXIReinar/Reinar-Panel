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
