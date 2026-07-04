"""
Integration тесты для эндпоинтов управления конфигами node_client/api/node_config_api.py

Тестируются эндпоинты:
- POST /node/config/read  - чтение конфига с опциональным удалением пользователей
- POST /node/config/write - запись конфига с опциональным переносом пользователей

Стратегия:
- Используем реальные файлы через tmp_path
- Используем реальный JSON из vless-tcp-server-metrics.json
- Проверяем файловые операции и HTTP ответы
"""
import shutil
from pathlib import Path

import orjson
import pytest

from node_client.api.proto_core.write_behind_caching_file import flatten_key2value


# ========== Группа 1: POST /node/config/read - Успешное чтение ==========

@pytest.mark.asyncio
async def test_read_config_success(client, tmp_path):
    """Успешное чтение обычного конфиг-файла"""
    # Создаём простой JSON файл
    config_data = {
        "log": {"loglevel": "info"},
        "inbounds": [{"port": 443, "protocol": "vless"}]
    }
    config_path = tmp_path / "simple_config.json"
    config_path.write_text(orjson.dumps(config_data, option=orjson.OPT_INDENT_2).decode())
    
    # Читаем через API
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(config_path),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["path"] == str(config_path)
    
    # Проверяем что содержимое совпадает
    returned_config = orjson.loads(data["content"])
    assert returned_config == config_data


@pytest.mark.asyncio
async def test_read_config_with_users_key(client, base_config_path, tmp_path):
    """Чтение конфига с удалением массива пользователей (flatten_json_users_key)"""
    # Копируем базовый конфиг во временную директорию
    test_config = tmp_path / "config_with_users.json"
    shutil.copy(base_config_path, test_config)
    
    # Читаем оригинальный конфиг для подсчёта пользователей
    original_config = orjson.loads(test_config.read_text())
    original_users_count = len(original_config["inbounds"][1]["settings"]["clients"])
    assert original_users_count > 0, "В тестовом конфиге должны быть пользователи"
    
    # Читаем через API с удалением пользователей
    flatten_key = "inbounds___1___settings___clients"
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(test_config),
        "flatten_json_users_key": flatten_key
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Проверяем что пользователи удалены из ответа
    returned_config = orjson.loads(data["content"])
    users_in_response = returned_config["inbounds"][1]["settings"].get("clients")
    
    # После удаления ключ должен отсутствовать
    assert users_in_response is None, "Массив пользователей должен быть удалён из ответа"
    
    # Проверяем что остальная структура сохранена
    assert returned_config["inbounds"][1]["protocol"] == "vless"
    assert returned_config["inbounds"][1]["port"] == 443


@pytest.mark.asyncio
async def test_read_config_without_users_key(client, base_config_path, tmp_path):
    """Чтение конфига БЕЗ удаления пользователей (flatten_json_users_key=None)"""
    test_config = tmp_path / "full_config.json"
    shutil.copy(base_config_path, test_config)
    
    # Читаем оригинал
    original_config = orjson.loads(test_config.read_text())
    original_users = original_config["inbounds"][1]["settings"]["clients"]
    
    # Читаем через API БЕЗ удаления
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(test_config),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем что пользователи НЕ удалены
    returned_config = orjson.loads(data["content"])
    returned_users = returned_config["inbounds"][1]["settings"]["clients"]
    
    assert len(returned_users) == len(original_users)
    assert returned_users == original_users


# ========== Группа 2: POST /node/config/read - Ошибки файловой системы ==========

@pytest.mark.asyncio
async def test_read_config_file_not_found(client, tmp_path):
    """404 если файл не существует"""
    non_existent = tmp_path / "ghost_file.json"
    
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(non_existent),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "не найден" in data["message"].lower()


@pytest.mark.asyncio
async def test_read_config_path_is_directory(client, tmp_path):
    """400 если путь указывает на директорию, а не файл"""
    directory = tmp_path / "config_dir"
    directory.mkdir()
    
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(directory),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "не является файлом" in data["message"].lower()


@pytest.mark.asyncio
async def test_read_config_invalid_encoding(client, tmp_path):
    """400 при попытке прочитать бинарный файл (неверная кодировка)"""
    binary_file = tmp_path / "binary.bin"
    # Записываем бинарные данные (не UTF-8)
    binary_file.write_bytes(b'\x80\x81\x82\x83\xFF\xFE')
    
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(binary_file),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "кодировку" in data["message"].lower() or "текстовым" in data["message"].lower()


# ========== Группа 3: POST /node/config/read - Обработка JSON ==========

@pytest.mark.asyncio
async def test_read_config_removes_users_array(client, base_config_path, tmp_path):
    """Проверка что массив пользователей полностью удалён из структуры"""
    test_config = tmp_path / "test_remove.json"
    shutil.copy(base_config_path, test_config)
    
    flatten_key = "inbounds___1___settings___clients"
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(test_config),
        "flatten_json_users_key": flatten_key
    })
    
    assert response.status_code == 200
    returned_config = orjson.loads(response.json()["content"])
    
    # Проверяем что ключ "clients" отсутствует
    settings = returned_config["inbounds"][1]["settings"]
    assert "clients" not in settings, "Ключ 'clients' должен быть полностью удалён"
    
    # Другие ключи должны остаться
    assert "decryption" in settings


@pytest.mark.asyncio
async def test_read_config_preserves_structure(client, base_config_path, tmp_path):
    """Остальная структура конфига сохраняется после удаления пользователей"""
    test_config = tmp_path / "test_preserve.json"
    shutil.copy(base_config_path, test_config)
    
    # Читаем оригинал
    original = orjson.loads(test_config.read_text())
    
    # Читаем с удалением пользователей
    response = await client.post("/api/v1/server/node/config/read", json={
        "path": str(test_config),
        "flatten_json_users_key": "inbounds___1___settings___clients"
    })
    
    returned = orjson.loads(response.json()["content"])
    
    # Проверяем сохранение структуры
    assert returned["log"] == original["log"]
    assert returned["stats"] == original["stats"]
    assert returned["api"] == original["api"]
    assert returned["outbounds"] == original["outbounds"]
    assert returned["routing"] == original["routing"]
    
    # inbounds тоже должны совпадать (кроме clients)
    assert len(returned["inbounds"]) == len(original["inbounds"])
    assert returned["inbounds"][0] == original["inbounds"][0]  # api inbound не трогается
    assert returned["inbounds"][1]["protocol"] == original["inbounds"][1]["protocol"]


# ========== Группа 4: POST /node/config/write - Успешная запись ==========

@pytest.mark.asyncio
async def test_write_config_success(client, tmp_path):
    """Успешная запись нового конфига в новый файл"""
    new_config = {
        "log": {"loglevel": "debug"},
        "inbounds": [{"port": 8080, "protocol": "vmess"}]
    }
    config_path = tmp_path / "new_config.json"
    
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "успешно записан" in data["message"].lower()
    
    # Проверяем что файл реально создан и содержимое совпадает
    assert config_path.exists()
    saved_config = orjson.loads(config_path.read_text())
    assert saved_config == new_config


@pytest.mark.asyncio
async def test_write_config_overwrite_existing(client, tmp_path):
    """Перезапись существующего файла"""
    config_path = tmp_path / "overwrite.json"
    
    # Создаём исходный файл
    old_config = {"version": 1, "data": "old"}
    config_path.write_text(orjson.dumps(old_config).decode())
    
    # Перезаписываем новым содержимым
    new_config = {"version": 2, "data": "new"}
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 200
    
    # Проверяем что старое содержимое заменено
    saved_config = orjson.loads(config_path.read_text())
    assert saved_config == new_config
    assert saved_config["version"] == 2


@pytest.mark.asyncio
async def test_write_config_preserves_users(client, base_config_path, tmp_path):
    """Сохранение пользователей из старого конфига при записи нового"""
    # Копируем базовый конфиг (с пользователями)
    old_config_path = tmp_path / "old_with_users.json"
    shutil.copy(base_config_path, old_config_path)
    
    # Читаем старых пользователей
    old_config = orjson.loads(old_config_path.read_text())
    old_users = old_config["inbounds"][1]["settings"]["clients"]
    old_users_count = len(old_users)
    
    # Создаём новый конфиг БЕЗ пользователей
    new_config = orjson.loads(old_config_path.read_text())
    new_config["log"]["loglevel"] = "error"  # Меняем что-то
    new_config["inbounds"][1]["settings"]["clients"] = []  # Очищаем пользователей
    
    # Записываем с переносом пользователей
    flatten_key = "inbounds___1___settings___clients"
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(old_config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": flatten_key
    })
    
    assert response.status_code == 200
    
    # Проверяем что пользователи сохранены
    saved_config = orjson.loads(old_config_path.read_text())
    saved_users = saved_config["inbounds"][1]["settings"]["clients"]
    
    assert len(saved_users) == old_users_count, "Количество пользователей должно сохраниться"
    assert saved_users == old_users, "Пользователи должны полностью совпадать"
    
    # Проверяем что изменения применены
    assert saved_config["log"]["loglevel"] == "error"


@pytest.mark.asyncio
async def test_write_config_without_users_key(client, base_config_path, tmp_path):
    """Запись БЕЗ сохранения пользователей (flatten_json_users_key=None)"""
    old_config_path = tmp_path / "no_preserve.json"
    shutil.copy(base_config_path, old_config_path)
    
    # Новый конфиг без пользователей
    new_config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "settings": {"clients": [], "decryption": "none"}
        }]
    }
    
    # Записываем БЕЗ переноса пользователей
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(old_config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 200
    
    # Проверяем что пользователи НЕ сохранены (список пустой)
    saved_config = orjson.loads(old_config_path.read_text())
    saved_users = saved_config["inbounds"][0]["settings"]["clients"]
    assert len(saved_users) == 0, "Пользователи не должны быть сохранены"


# ========== Группа 5: POST /node/config/write - Логика переноса пользователей ==========

@pytest.mark.asyncio
async def test_write_config_merge_users_from_old(client, base_config_path, tmp_path):
    """Пользователи из старого файла корректно переносятся в новый конфиг"""
    config_path = tmp_path / "merge_test.json"
    shutil.copy(base_config_path, config_path)
    
    # Читаем старых пользователей
    old_config = orjson.loads(config_path.read_text())
    old_users = old_config["inbounds"][1]["settings"]["clients"]
    old_user_emails = [u["email"] for u in old_users]
    
    # Создаём совершенно новую структуру конфига
    new_config = {
        "log": {"loglevel": "critical"},
        "inbounds": [
            {"port": 10085, "protocol": "dokodemo-door"},  # API inbound
            {
                "port": 9999,  # Новый порт
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": "new-uuid", "email": "new_user"}],  # Новые пользователи (будут заменены)
                    "decryption": "none"
                }
            }
        ]
    }
    
    # Записываем с переносом
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": "inbounds___1___settings___clients"
    })
    
    assert response.status_code == 200
    
    # Проверяем что старые пользователи перенесены в новую структуру
    saved_config = orjson.loads(config_path.read_text())
    saved_users = saved_config["inbounds"][1]["settings"]["clients"]
    saved_user_emails = [u["email"] for u in saved_users]
    
    assert saved_user_emails == old_user_emails, "Email пользователей должны совпадать со старым конфигом"
    assert saved_config["inbounds"][1]["port"] == 9999, "Новая структура должна быть применена"
    assert saved_config["log"]["loglevel"] == "critical", "Изменения должны быть сохранены"


@pytest.mark.asyncio
async def test_write_config_users_path_navigation(client, tmp_path):
    """Навигация по flatten ключу работает корректно для разных уровней вложенности"""
    # Создаём конфиг с глубокой вложенностью
    old_config = {
        "level1": {
            "level2": {
                "level3": {
                    "users": [
                        {"name": "user1", "id": 1},
                        {"name": "user2", "id": 2}
                    ]
                }
            }
        }
    }
    config_path = tmp_path / "deep_structure.json"
    config_path.write_text(orjson.dumps(old_config).decode())
    
    # Новый конфиг с пустым массивом пользователей
    new_config = {
        "level1": {
            "level2": {
                "level3": {
                    "users": [],
                    "new_field": "added"
                }
            }
        }
    }
    
    # Записываем с переносом пользователей
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": "level1___level2___level3___users"
    })
    
    assert response.status_code == 200
    
    # Проверяем что пользователи перенесены
    saved_config = orjson.loads(config_path.read_text())
    saved_users = saved_config["level1"]["level2"]["level3"]["users"]
    
    assert len(saved_users) == 2
    assert saved_users[0]["name"] == "user1"
    assert saved_config["level1"]["level2"]["level3"]["new_field"] == "added"


@pytest.mark.asyncio
async def test_write_config_empty_users_list(client, tmp_path):
    """Работа с пустым списком пользователей в старом конфиге"""
    # Старый конфиг с пустым списком
    old_config = {
        "inbounds": [{
            "settings": {"clients": []}
        }]
    }
    config_path = tmp_path / "empty_users.json"
    config_path.write_text(orjson.dumps(old_config).decode())
    
    # Новый конфиг
    new_config = {
        "inbounds": [{
            "settings": {"clients": [{"id": "new"}], "decryption": "none"}
        }]
    }
    
    # Записываем с переносом
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": "inbounds___0___settings___clients"
    })
    
    assert response.status_code == 200
    
    # Пустой список должен остаться пустым
    saved_config = orjson.loads(config_path.read_text())
    assert saved_config["inbounds"][0]["settings"]["clients"] == []


# ========== Группа 6: POST /node/config/write - Ошибки записи ==========

@pytest.mark.asyncio
async def test_write_config_invalid_json_content(client, tmp_path):
    """500 при невалидном JSON в content"""
    config_path = tmp_path / "invalid.json"
    
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(config_path),
        "content": "{ invalid json syntax: [,] }",
        "flatten_json_users_key": None
    })
    
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert "ошибка" in data["message"].lower()


@pytest.mark.asyncio
async def test_write_config_invalid_old_file(client, tmp_path):
    """500 если старый файл повреждён при попытке переноса пользователей"""
    # Создаём файл с невалидным JSON
    old_config_path = tmp_path / "corrupted.json"
    old_config_path.write_text("{ broken json [[[")
    
    new_config = {"data": "new"}
    
    # Пытаемся записать с переносом пользователей
    response = await client.post("/api/v1/server/node/config/write", json={
        "path": str(old_config_path),
        "content": orjson.dumps(new_config).decode(),
        "flatten_json_users_key": "some___key"
    })
    
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
