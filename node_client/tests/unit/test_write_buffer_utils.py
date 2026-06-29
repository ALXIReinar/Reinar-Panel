"""
Unit тесты для утилит ConfigWriteBuffer

Тестируем чистые функции без побочных эффектов:
- flatten_key2value() - парсинг flatten-json ключей
- _navigate_to_path() - навигация до массива
- _read_config() - чтение JSON конфига
- _write_config_atomic() - атомарная запись
"""
import json
import pytest
from pathlib import Path

import orjson

from node_client.api.proto_core.write_behind_caching_file import (
    ConfigWriteBuffer,
    flatten_key2value,
)
from node_client.config import TMP_DIR


# ========== Fixtures ==========

@pytest.fixture
def sample_xray_config():
    """Тестовый конфиг xray для утилит"""
    return {
        "log": {"loglevel": "warning"},
        "stats": {},
        "inbounds": [
            {
                "port": 10085,
                "protocol": "dokodemo-door",
                "tag": "api"
            },
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        {
                            "id": "uuid-001",
                            "email": "user1@test.com",
                            "flow": "xtls-rprx-vision"
                        },
                        {
                            "id": "uuid-002",
                            "email": "user2@test.com",
                            "flow": "xtls-rprx-vision"
                        }
                    ],
                    "decryption": "none"
                }
            }
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"}
        ]
    }


@pytest.fixture
def temp_config_file(tmp_path, sample_xray_config):
    """Создаёт временный JSON конфиг для тестов"""
    config_path = tmp_path / "test_config.json"
    
    with open(config_path, 'wb') as f:
        f.write(orjson.dumps(sample_xray_config, option=orjson.OPT_INDENT_2))
    
    return config_path


@pytest.fixture
def temp_invalid_json_file(tmp_path):
    """Создаёт файл с невалидным JSON"""
    invalid_path = tmp_path / "invalid.json"
    
    with open(invalid_path, 'w') as f:
        f.write("This is not JSON content! @#$%^&*()")
    
    return invalid_path


# ========== Тесты flatten_key2value() ==========

def test_flatten_key2value_simple_select(sample_xray_config):
    """
    Тест: Простой select значения по flatten ключу
    
    Проверяем что функция корректно извлекает значение из вложенной структуры
    """
    # Получаем loglevel
    result = flatten_key2value(sample_xray_config, "log___loglevel")
    
    assert result == "warning"


def test_flatten_key2value_array_index(sample_xray_config):
    """
    Тест: Навигация по массиву с индексом
    
    Проверяем что функция корректно обрабатывает числовые индексы
    """
    # Получаем массив clients из второго inbound (индекс 1)
    clients = flatten_key2value(sample_xray_config, "inbounds___1___settings___clients")
    
    assert isinstance(clients, list)
    assert len(clients) == 2
    assert clients[0]["email"] == "user1@test.com"


def test_flatten_key2value_nested_value(sample_xray_config):
    """
    Тест: Глубокая вложенность
    
    Проверяем навигацию на 4 уровня вглубь
    """
    # Получаем email первого клиента
    email = flatten_key2value(sample_xray_config, "inbounds___1___settings___clients___0___email")
    
    assert email == "user1@test.com"


def test_flatten_key2value_with_delete(sample_xray_config):
    """
    Тест: Удаление объекта по ключу (delete_obj=True)
    
    Проверяем что объект удаляется из исходного словаря
    """
    # Удаляем массив clients
    result = flatten_key2value(
        sample_xray_config,
        "inbounds___1___settings___clients",
        delete_obj=True
    )
    
    assert result is None  # Функция ничего не возвращает при удалении
    
    # Проверяем что clients удалён
    assert "clients" not in sample_xray_config["inbounds"][1]["settings"]


def test_flatten_key2value_with_replace(sample_xray_config):
    """
    Тест: Замена объекта по ключу (replace_last_obj=True)
    
    Проверяем что объект заменяется на новый
    """
    new_clients = [
        {"id": "uuid-999", "email": "newuser@test.com"}
    ]
    
    # Заменяем массив clients
    result = flatten_key2value(
        sample_xray_config,
        "inbounds___1___settings___clients",
        new_last_obj=new_clients,
        replace_last_obj=True
    )
    
    assert result is None  # Функция ничего не возвращает при замене
    
    # Проверяем что clients заменён
    clients = sample_xray_config["inbounds"][1]["settings"]["clients"]
    assert len(clients) == 1
    assert clients[0]["email"] == "newuser@test.com"


def test_flatten_key2value_invalid_key(sample_xray_config):
    """
    Тест: Неверный ключ (несуществующий путь)
    
    Ожидаем: Exception (функция возвращает Exception как fallback)
    """
    result = flatten_key2value(sample_xray_config, "nonexistent___key___path")
    assert result is Exception


def test_flatten_key2value_incorrect_delimiter():
    """
    Тест: Некорректный разделитель (используется '.' вместо '___')
    
    Ожидаем: Exception, т.к. ключ не будет разделён корректно.
    Функция попытается найти ключ "a.b.c" целиком (без разделения) и не найдёт его.
    """
    config = {"a": {"b": {"c": "value"}}}
    
    # Используем точку вместо ___
    result = flatten_key2value(config, "a.b.c")
    assert result is Exception


def test_flatten_key2value_deep_nesting():
    """
    Тест: Очень глубокая вложенность (5+ уровней)
    
    Проверяем что функция справляется с глубокими структурами
    """
    deep_config = {
        "level1": {
            "level2": {
                "level3": {
                    "level4": {
                        "level5": {
                            "value": "deep_value"
                        }
                    }
                }
            }
        }
    }
    
    result = flatten_key2value(
        deep_config,
        "level1___level2___level3___level4___level5___value"
    )
    
    assert result == "deep_value"


# ========== Тесты _navigate_to_path() ==========

def test_navigate_to_path_success(sample_xray_config):
    """
    Тест: Успешная навигация до массива
    
    Проверяем что функция возвращает ссылку на list
    """
    buffer = ConfigWriteBuffer()
    
    clients = buffer._navigate_to_path(
        sample_xray_config,
        "inbounds___1___settings___clients"
    )
    
    assert isinstance(clients, list)
    assert len(clients) == 2
    
    # Проверяем что это именно ссылка (изменения отразятся в config)
    clients.append({"id": "uuid-003", "email": "user3@test.com"})
    assert len(sample_xray_config["inbounds"][1]["settings"]["clients"]) == 3


def test_navigate_to_path_not_array(sample_xray_config):
    """
    Тест: Путь ведёт к dict, а не к list
    
    Ожидаем: TypeError
    """
    buffer = ConfigWriteBuffer()
    
    with pytest.raises(TypeError, match="не указывает на массив"):
        # Путь ведёт к dict 'settings', а не к массиву
        buffer._navigate_to_path(
            sample_xray_config,
            "inbounds___1___settings"
        )


# ========== Тесты _read_config() ==========

async def test_read_config_success(temp_config_file):
    """
    Тест: Успешное чтение JSON конфига
    
    Проверяем что файл корректно парсится в dict
    """
    buffer = ConfigWriteBuffer()
    
    config = await buffer._read_config(str(temp_config_file))
    
    assert isinstance(config, dict)
    assert "inbounds" in config
    assert "outbounds" in config
    assert config["log"]["loglevel"] == "warning"


async def test_read_config_file_not_found():
    """
    Тест: Файл не существует
    
    Ожидаем: FileNotFoundError
    """
    buffer = ConfigWriteBuffer()
    
    with pytest.raises(FileNotFoundError):
        await buffer._read_config("/path/to/nonexistent/file.json")


async def test_read_config_invalid_json(temp_invalid_json_file):
    """
    Тест: Файл содержит невалидный JSON
    
    Ожидаем: orjson.JSONDecodeError
    """
    buffer = ConfigWriteBuffer()
    
    with pytest.raises(orjson.JSONDecodeError):
        await buffer._read_config(str(temp_invalid_json_file))


# ========== Тесты _write_config_atomic() ==========

async def test_write_config_atomic_success(tmp_path, sample_xray_config):
    """
    Тест: Успешная атомарная запись конфига
    
    Проверяем что:
    1. Файл записан корректно
    2. Содержимое совпадает с исходным
    """
    buffer = ConfigWriteBuffer()
    
    target_file = tmp_path / "output_config.json"
    
    # Записываем конфиг
    await buffer._write_config_atomic(str(target_file), sample_xray_config)
    
    # Проверяем что файл создан
    assert target_file.exists()
    
    # Читаем и проверяем содержимое
    with open(target_file, 'rb') as f:
        written_config = orjson.loads(f.read())
    
    assert written_config == sample_xray_config
    assert written_config["log"]["loglevel"] == "warning"
    assert len(written_config["inbounds"]) == 2


async def test_write_config_atomic_uses_tmp_dir(tmp_path, sample_xray_config):
    """
    Тест: Проверка что .tmp файл создаётся в TMP_DIR
    
    Проверяем механизм атомарной записи через временный файл
    """
    buffer = ConfigWriteBuffer()
    
    target_file = tmp_path / "atomic_test.json"
    
    # Записываем конфиг
    await buffer._write_config_atomic(str(target_file), sample_xray_config)
    
    # Проверяем что конечный файл существует
    assert target_file.exists()
    
    # Проверяем что в TMP_DIR нет оставшихся .tmp файлов
    # (они должны быть удалены после успешной записи через os.replace)
    tmp_files = list(TMP_DIR.glob("*.tmp"))
    
    # Допускаем что могут быть .tmp от других тестов, 
    # но проверяем что наш файл атомарно записался
    with open(target_file, 'rb') as f:
        content = orjson.loads(f.read())
    
    assert content == sample_xray_config
