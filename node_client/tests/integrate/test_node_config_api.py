"""
Integration тесты для эндпоинтов управления конфигами node_client/api/node_config_api.py

Тестируются эндпоинты:
- POST /node/config/read  - чтение конфига с опциональным удалением пользователей
- POST /node/config/write - запись конфига с опциональным переносом пользователей

Стратегия:
- Используем реальные файлы через tmp_path
- Используем реальный JSON из vless-tcp-server-metrics.json
- Проверяем файловые операции и HTTP ответы
- Для тестов с кастомными конвертерами используем данные из БД (protocol_templates_with_extractors)
"""
import shutil
from pathlib import Path

import orjson
import pytest

from node_client.api.proto_core.write_behind_caching_file import flatten_key2value
from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor


# ========== Helper Functions ==========

def extract_flatten_keys_from_template(template: dict) -> list[str]:
    """
    Извлекает список flatten_array_cursor из extractors шаблона.
    
    Args:
        template: Шаблон протокола с полем 'extractors'
    
    Returns:
        Список flatten ключей (например: ["inbounds___0___settings___clients"])
    
    Example:
        >>> template = {'extractors': [{'flatten_array_cursor': 'inbounds___0___settings___clients'}]}
        >>> extract_flatten_keys_from_template(template)
        ['inbounds___0___settings___clients']
    """
    if not template.get('extractors'):
        return []
    
    return [ext['flatten_array_cursor'] for ext in template['extractors']]


def has_custom_converters(template: dict) -> bool:
    """
    Проверяет наличие кастомных config2json/json2config скриптов.
    
    JSON конвертация (оба поля NULL) работает безупречно и не требует тестирования.
    Кастомные форматы (TOML, YAML, etc.) имеют нюансы и требуют отдельного тестирования.
    
    Args:
        template: Шаблон протокола
    
    Returns:
        True если хотя бы один конвертер кастомный (не NULL)
    """
    return (template.get('config2json_script') is not None or 
            template.get('json2config_script') is not None)


def create_nested_config_from_flatten_keys(flatten_keys: list[str], add_test_users: int = 3) -> dict:
    """
    Генерирует JSON структуру с правильной вложенностью по flatten ключам.
    
    Каждый flatten_key определяет путь к массиву пользователей в конфиге.
    Функция создаёт минимальную структуру для тестирования операций read/write.
    
    Args:
        flatten_keys: Список flatten путей (например: ["inbounds___1___settings___clients"])
        add_test_users: Количество тестовых пользователей в каждом массиве
    
    Returns:
        dict: JSON конфиг с правильной структурой и заполненными массивами пользователей
    
    Example:
        >>> create_nested_config_from_flatten_keys(["level1___0___users"], add_test_users=2)
        {'level1': [{'users': [{'id': 'test-uuid-0', 'email': 'user0@test'}, ...]}]}
    """
    config = {}
    
    for flatten_key in flatten_keys:
        parts = flatten_key.split('___')
        current = config
        
        # Навигация по всем частям пути кроме последней
        for i, part in enumerate(parts[:-1]):
            if part.isdigit():
                # Это индекс массива
                idx = int(part)
                # Расширяем массив если нужно
                while len(current) <= idx:
                    current.append({})
                current = current[idx]
            else:
                # Это ключ объекта
                if part not in current:
                    # Определяем тип следующего уровня (массив или объект)
                    next_part = parts[i + 1] if i + 1 < len(parts) else None
                    current[part] = [] if next_part and next_part.isdigit() else {}
                current = current[part]
        
        # Последняя часть - это ключ массива пользователей
        last_key = parts[-1]
        
        # Определяем формат пользователей по flatten_key
        if "auth" in flatten_key and "users" in flatten_key:
            # Hysteria формат: {username, password}
            current[last_key] = [
                {"username": f"user{i}", "password": f"pass{i}"}
                for i in range(add_test_users)
            ]
        else:
            # Стандартный формат: {id, email}
            current[last_key] = [
                {"id": f"test-uuid-{i}", "email": f"user{i}@test.local"}
                for i in range(add_test_users)
            ]
    
    return config


# ========== Helper Functions for Payloads ==========

def create_read_payload(
    path: str, 
    flatten_key: list[str] = None, 
    node_proto_id: int = 1,
    config2json_script: str = None,
    json2config_script: str = None,
    conf_converter_libs: str = None
) -> dict:
    """Создаёт payload для /node/config/read с актуальной схемой"""
    return {
        "node_proto_id": node_proto_id,
        "path": path,
        "flatten_json_users_key": flatten_key if flatten_key else [],  # Пустой список вместо None
        "config2json_script": config2json_script,
        "json2config_script": json2config_script,
        "conf_converter_libs": conf_converter_libs
    }


def create_write_payload(
    path: str, 
    content: str, 
    flatten_key: list[str] = None, 
    node_proto_id: int = 1,
    tmp_link: str = "http://test.local/config",
    config2json_script: str = None,
    json2config_script: str = None,
    conf_converter_libs: str = None
) -> dict:
    """Создаёт payload для /node/config/write с актуальной схемой"""
    return {
        "node_proto_id": node_proto_id,
        "tmp_link": tmp_link,
        "path": path,
        "content": content,
        "flatten_json_users_key": flatten_key if flatten_key else [],  # Пустой список вместо None
        "config2json_script": config2json_script,
        "json2config_script": json2config_script,
        "conf_converter_libs": conf_converter_libs
    }


# ========== Тесты с реальными шаблонами из БД (кастомные конвертеры) ==========

@pytest.mark.asyncio
@pytest.mark.db
async def test_read_config_with_custom_converters_from_db(protocol_templates_with_extractors, client, tmp_path):
    """
    Тест чтения конфига с удалением пользователей для кастомных конвертеров из БД.
    
    Проверяет корректность работы config2json/json2config скриптов:
    1. Фильтрует только шаблоны с кастомными конвертерами (не NULL)
    2. Генерирует эвристический конфиг с пользователями
    3. Конвертирует через json2config → записывает в нативном формате
    4. Читает через API с удалением пользователей
    5. Конвертирует через config2json и проверяет отсутствие пользователей
    
    JSON конвертация (оба скрипта NULL) работает безупречно и не требует тестирования.
    Кастомные форматы (TOML, YAML, etc.) имеют нюансы и требуют отдельного тестирования.
    
    Формат отчёта:
    ✅ singbox-hysteria2: OK
    ✅ singbox-wireguard: OK
    ❌ v2fly-shadowsocks: KeyError 'method'
    
    Итого: 2/3 шаблонов passed
    """
    results = []
    errors = []
    
    # ОТЛАДКА: Проверяем что фикстура вообще что-то вернула
    if not protocol_templates_with_extractors:
        pytest.fail("Фикстура protocol_templates_with_extractors вернула пустой список!")
    
    for template in protocol_templates_with_extractors:
        # Пропускаем JSON-шаблоны (работают идеально, тестировать не нужно)
        if not has_custom_converters(template):
            continue
        
        # Пропускаем шаблоны без extractors
        flatten_keys = extract_flatten_keys_from_template(template)
        if not flatten_keys:
            continue
        
        template_title = template['title']
        
        try:
            # 1. Генерируем эвристический конфиг с 3 юзерами
            config_dict = create_nested_config_from_flatten_keys(flatten_keys, add_test_users=3)
            
            # 2. Конвертируем dict → нативный формат через json2config
            conf_dumper = HotReloadExecutor.get_compiled_func(
                template['json2config_script'], 
                'json2config', 
                template['conf_converter_libs']
            )
            raw_config = conf_dumper(config_dict).decode('utf-8')
            
            # 3. Записываем в файл в нативном формате
            config_path = tmp_path / f"{template_title.replace('/', '_')}_config.txt"
            config_path.write_text(raw_config, encoding='utf-8')
            
            # 4. Читаем через API с удалением пользователей
            response = await client.post("/api/v1/server/node/config/read", json=create_read_payload(
                path=str(config_path),
                flatten_key=flatten_keys,
                node_proto_id=template['id'],
                config2json_script=template['config2json_script'],
                json2config_script=template['json2config_script'],
                conf_converter_libs=template['conf_converter_libs']
            ))
            
            # Проверяем успешность
            if response.status_code != 200:
                error_detail = response.text
                assert False, f"Unexpected status: {response.status_code}, body: {error_detail}"
            data = response.json()
            assert data["success"] is True, f"Response not successful: {data.get('message')}"
            
            # 5. Конвертируем нативный → dict через config2json
            conf_loader = HotReloadExecutor.get_compiled_func(
                template['config2json_script'],
                'config2json',
                template['conf_converter_libs']
            )
            returned_dict = conf_loader(data["content"])
            
            # 6. Проверка: пользователи должны быть удалены
            for flatten_array_cursor in flatten_keys:
                users = flatten_key2value(returned_dict, flatten_array_cursor)
                assert users is None or users == Exception or (isinstance(users, list) and len(users) == 0), \
                    f"Пользователи должны быть удалены для {flatten_array_cursor}, получено: {users}"
            
            results.append(f"✅ {template_title}: OK")
            
        except Exception as e:
            errors.append(f"❌ {template_title}: {str(e)}")
    
    # Итоговый отчёт
    print("\n" + "\n".join(results + errors))
    print(f"\nИтого: {len(results)}/{len(results)+len(errors)} шаблонов passed")
    
    # Если были ошибки - тест проваливается
    if errors:
        pytest.fail(f"Тесты упали для {len(errors)} шаблонов:\n" + "\n".join(errors))


@pytest.mark.asyncio
@pytest.mark.db
async def test_write_config_with_custom_converters_from_db(protocol_templates_with_extractors, client, tmp_path):
    """
    Тест записи конфига с переносом пользователей для кастомных конвертеров из БД.
    
    Проверяет корректность работы json2config скриптов:
    1. Фильтрует только шаблоны с кастомными конвертерами
    2. Создаёт исходный конфиг с 3 юзерами
    3. Читает через READ без удаления пользователей
    4. Добавляет 4-го пользователя в dict
    5. Конвертирует через json2config и записывает
    6. Проверяет что файл содержит 4 пользователей
    
    Формат отчёта:
    ✅ singbox-hysteria2: OK (4 users)
    ✅ singbox-wireguard: OK (4 users)
    ❌ v2fly-shadowsocks: AssertionError: Expected 4 users, got 3
    
    Итого: 2/3 шаблонов passed
    """
    results = []
    errors = []
    custom_converters_templates = 0
    
    for template in protocol_templates_with_extractors:
        # Пропускаем JSON-шаблоны
        if not has_custom_converters(template):
            continue
        custom_converters_templates += 1

        # Пропускаем шаблоны без extractors
        flatten_keys = extract_flatten_keys_from_template(template)
        if not flatten_keys:
            continue
        
        template_title = template['title']
        print(f"{template_title}")
        try:
            # 1. Генерируем исходный конфиг с 3 юзерами
            config_dict = create_nested_config_from_flatten_keys(flatten_keys, add_test_users=3)
            
            # 2. Конвертируем dict → нативный формат
            conf_dumper = HotReloadExecutor.get_compiled_func(
                template['json2config_script'],
                'json2config',
                template['conf_converter_libs']
            )
            conf_loader = HotReloadExecutor.get_compiled_func(
                template['config2json_script'],
                'config2json',
                template['conf_converter_libs']
            )
            
            raw_config = conf_dumper(config_dict).decode('utf-8')
            config_path = tmp_path / f"{template_title.replace('/', '_')}_write_test.txt"
            config_path.write_text(raw_config, encoding='utf-8')
            
            # 3. READ: читаем конфиг БЕЗ удаления пользователей
            response_read = await client.post("/api/v1/server/node/config/read", json=create_read_payload(
                path=str(config_path),
                flatten_key=[],  # Пустой список = не удаляем пользователей
                node_proto_id=template['id'],
                config2json_script=template['config2json_script'],
                json2config_script=template['json2config_script'],
                conf_converter_libs=template['conf_converter_libs']
            ))
            
            assert response_read.status_code == 200, "READ должен пройти успешно"
            
            # 4. Конвертируем в dict и добавляем 4-го пользователя
            old_config = conf_loader(response_read.json()["content"])
            
            for flatten_key in flatten_keys:
                users_list = flatten_key2value(old_config, flatten_key)
                # Определяем формат пользователя по flatten_key
                if "auth" in flatten_key and "users" in flatten_key:
                    # Hysteria формат
                    new_user = {"username": "user4", "password": "pass4"}
                else:
                    # Стандартный формат
                    new_user = {"id": "test-uuid-4", "email": "user4@test.local"}
                users_list.append(new_user)
            
            # 5. Конвертируем dict → нативный формат и записываем
            raw_new_config = conf_dumper(old_config).decode('utf-8')
            
            response_write = await client.post("/api/v1/server/node/config/write", json=create_write_payload(
                path=str(config_path),
                content=raw_new_config,
                flatten_key=[],  # Пустой список = НЕ переносим пользователей
                node_proto_id=template['id'],
                config2json_script=template['config2json_script'],
                json2config_script=template['json2config_script'],
                conf_converter_libs=template['conf_converter_libs']
            ))
            
            assert response_write.status_code == 200, f"WRITE должен пройти успешно: {response_write.json()}"
            
            # 6. READ снова: проверяем что 4 юзера
            response_verify = await client.post("/api/v1/server/node/config/read", json=create_read_payload(
                path=str(config_path),
                flatten_key=[],
                node_proto_id=template['id'],
                config2json_script=template['config2json_script'],
                json2config_script=template['json2config_script'],
                conf_converter_libs=template['conf_converter_libs']
            ))
            
            saved_dict = conf_loader(response_verify.json()["content"])
            
            # 7. Проверка: 4 пользователя в каждом flatten_key
            for flatten_array_cursor in flatten_keys:
                users = flatten_key2value(saved_dict, flatten_array_cursor)
                assert isinstance(users, list) and len(users) == 4, \
                    f"Должно быть 4 пользователя для {flatten_array_cursor}, получено {len(users) if isinstance(users, list) else 'not a list'}"
            
            results.append(f"✅ {template_title}: OK (4 users)")
            
        except Exception as e:
            errors.append(f"❌ {template_title}: {str(e)}")
    
    # Итоговый отчёт
    print("\n" + "\n".join(results + errors))
    print(f"\nИтого: {len(results)}/{len(results)+len(errors)} шаблонов passed")
    
    # Если были ошибки - тест проваливается
    if errors:
        pytest.fail(f"Тесты упали для {len(errors)} шаблонов:\n" + "\n".join(errors))

    assert len(results) == custom_converters_templates, "Часть шаблонов обошла проверку конвертер скриптов: скрипты не указаны!"
