"""
Integration тесты для эндпоинтов управления конфигами node_client/api/node_config_api.py

Тестируются эндпоинты:
- POST /node/config/read  - чтение конфига с опциональным удалением пользователей
- POST /node/config/write - запись конфига с опциональным переносом пользователей

Стратегия:
- Используем реальные файлы через tmp_path
- Используем реальный JSON из vless-tcp-server-metrics.json
- Проверяем файловые операции и HTTP ответы
- Для тестов с кастомными конвертерами используем данные из БД (protocol_templates_with_extractors):
  нода регистрируется с конвертерами шаблона, запросы — без служебных полей. Запуск: --protocol '*'
"""

import shutil  # noqa: F401, I001
from pathlib import Path

import orjson
import pytest

from node_client.api.proto_core.write_behind_caching_file import flatten_key2value
from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.tests.utils.test_data_factory import create_vnode_service_data


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
    return template.get('config2json_script') is not None or template.get('json2config_script') is not None


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
            current[last_key] = [{"username": f"user{i}", "password": f"pass{i}"} for i in range(add_test_users)]
        else:
            # Стандартный формат: {id, email}
            current[last_key] = [
                {"id": f"test-uuid-{i}", "email": f"user{i}@test.local"} for i in range(add_test_users)
            ]
    return config


# ========== Регистрация ноды по шаблону ==========

READ_URL = "/api/v1/server/node/config/read"
WRITE_URL = "/api/v1/server/node/config/write"


async def register_template_node(buffer, template: dict, config_path) -> int:
    """
    Регистрирует в буфере виртуальную ноду с конвертерами и экстракторами шаблона.

    Так нод-клиент получает их в рабочем режиме — из /startup, а не в теле запроса.
    Возвращает node_proto_id (берём id шаблона: он уникален в пределах теста).
    """
    item = create_vnode_service_data(
        node_proto_id=template['id'],
        filepath=str(config_path),
        user_injectors=[
            {
                'flatten_array_cursor': ext['flatten_array_cursor'],
                'extractor_script': ext['extractor_script'],
                'libs': ext['libs'],
            }
            for ext in template['extractors']
        ],
        config2json_script=template['config2json_script'],
        json2config_script=template['json2config_script'],
        conf_converter_libs=template['conf_converter_libs'],
    )
    await buffer.register_node(item)
    return template['id']


def write_native_config(template: dict, config_path, flatten_keys: list[str], users_count: int) -> None:
    """Генерирует конфиг с пользователями и пишет его в нативном формате шаблона (json2config)"""
    conf_dumper = HotReloadExecutor.get_compiled_func(
        template['json2config_script'], 'json2config', template['conf_converter_libs']
    )
    config_dict = create_nested_config_from_flatten_keys(flatten_keys, add_test_users=users_count)
    config_path.write_bytes(conf_dumper(config_dict))


def custom_converter_templates(templates: list[dict]) -> list[dict]:
    """Шаблоны с кастомными конвертерами и экстракторами; если в выборке их нет — явный skip, а не пустой проход"""
    selected = [t for t in templates if has_custom_converters(t) and extract_flatten_keys_from_template(t)]
    if not selected:
        pytest.skip(
            "В выборке --protocol нет шаблонов с кастомными конвертерами (amneziawg, hysteria): запусти с --protocol '*'"
        )
    return selected


def report(results: list[str], errors: list[str]) -> None:
    """Печатает отчёт по шаблонам и валит тест, если хоть один шаблон упал"""
    print("\n" + "\n".join(results + errors))
    print(f"\nИтого: {len(results)}/{len(results) + len(errors)} шаблонов passed")
    if errors:
        pytest.fail(f"Тесты упали для {len(errors)} шаблонов:\n" + "\n".join(errors))


# ========== Тесты с реальными шаблонами из БД (кастомные конвертеры) ==========


@pytest.mark.asyncio
@pytest.mark.db
async def test_read_config_with_custom_converters_from_db(protocol_templates_with_extractors, client, tmp_path):
    """
    /read для шаблонов с кастомными конвертерами (conf, yaml): пользователи вырезаются.

    1. Конфиг с 3 пользователями пишется в нативном формате шаблона (json2config)
    2. Нода регистрируется с конвертерами и экстракторами шаблона
    3. /read без служебных полей (exclude_users по умолчанию True)
    4. Ответ разбирается config2json: массивов пользователей быть не должно
    """
    buffer = client.app.state.core_buffer
    results, errors = [], []

    for template in custom_converter_templates(protocol_templates_with_extractors):
        template_title = template['title']
        flatten_keys = extract_flatten_keys_from_template(template)
        try:
            config_path = tmp_path / f"{template_title}_read.conf"
            write_native_config(template, config_path, flatten_keys, users_count=3)
            node_proto_id = await register_template_node(buffer, template, config_path)

            response = await client.post(READ_URL, json={"node_proto_id": node_proto_id, "path": str(config_path)})
            if response.status_code != 200:
                raise AssertionError(f"Unexpected status: {response.status_code}, body: {response.text}")

            conf_loader = HotReloadExecutor.get_compiled_func(
                template['config2json_script'], 'config2json', template['conf_converter_libs']
            )
            returned_dict = conf_loader(response.json()["content"])
            for flatten_array_cursor in flatten_keys:
                users = flatten_key2value(returned_dict, flatten_array_cursor)
                assert users is None or users is Exception or (isinstance(users, list) and len(users) == 0), (
                    f"Пользователи должны быть удалены для {flatten_array_cursor}, получено: {users}"
                )
            results.append(f"✅ {template_title}: OK")
        except Exception as e:
            errors.append(f"❌ {template_title}: {e!r}")

    report(results, errors)


@pytest.mark.asyncio
@pytest.mark.db
async def test_write_config_with_custom_converters_from_db(protocol_templates_with_extractors, client, tmp_path):
    """
    /write для шаблонов с кастомными конвертерами: пользователи переносятся из старого файла.

    1. Старый конфиг с 3 пользователями пишется в нативном формате шаблона
    2. Нода регистрируется с конвертерами и экстракторами шаблона
    3. /write нового содержимого с пустыми массивами пользователей
    4. /read с exclude_users=False: в файле снова 3 пользователя из старого конфига
    """
    buffer = client.app.state.core_buffer
    results, errors = [], []

    for template in custom_converter_templates(protocol_templates_with_extractors):
        template_title = template['title']
        flatten_keys = extract_flatten_keys_from_template(template)
        try:
            config_path = tmp_path / f"{template_title}_write.conf"
            write_native_config(template, config_path, flatten_keys, users_count=3)
            node_proto_id = await register_template_node(buffer, template, config_path)

            conf_dumper = HotReloadExecutor.get_compiled_func(
                template['json2config_script'], 'json2config', template['conf_converter_libs']
            )
            new_content = conf_dumper(create_nested_config_from_flatten_keys(flatten_keys, add_test_users=0))
            response_write = await client.post(
                WRITE_URL,
                json={
                    "node_proto_id": node_proto_id,
                    "path": str(config_path),
                    "content": new_content.decode('utf-8'),
                    "tmp_link": "http://test.local/config",
                    "transfer_users": True,
                },
            )
            if response_write.status_code != 200:
                raise AssertionError(f"WRITE: {response_write.status_code}, body: {response_write.text}")

            response_read = await client.post(
                READ_URL, json={"node_proto_id": node_proto_id, "path": str(config_path), "exclude_users": False}
            )
            if response_read.status_code != 200:
                raise AssertionError(f"READ: {response_read.status_code}, body: {response_read.text}")

            conf_loader = HotReloadExecutor.get_compiled_func(
                template['config2json_script'], 'config2json', template['conf_converter_libs']
            )
            saved_dict = conf_loader(response_read.json()["content"])
            for flatten_array_cursor in flatten_keys:
                users = flatten_key2value(saved_dict, flatten_array_cursor)
                assert isinstance(users, list) and len(users) == 3, (
                    f"Должно быть 3 пользователя из старого файла для {flatten_array_cursor}, получено: {users}"
                )
            results.append(f"✅ {template_title}: OK (3 users перенесены)")
        except Exception as e:
            errors.append(f"❌ {template_title}: {e!r}")

    report(results, errors)


# ========== Незарегистрированная нода (требования 5.3, 6.5) ==========

NOT_REGISTERED_MESSAGE = "нода не зарегистрирована в нод-клиенте, выполните реинициализацию"


@pytest.mark.asyncio
async def test_read_config_not_registered_node_returns_428(client, tmp_path):
    """/read для ноды, которой нет в памяти нод-клиента, отвечает 428, а не 500"""
    config_path = tmp_path / "config.json"
    config_path.write_text('{"inbounds": []}', encoding='utf-8')

    response = await client.post(
        "/api/v1/server/node/config/read", json={"node_proto_id": 999, "path": str(config_path)}
    )

    assert response.status_code == 428
    assert response.json() == {"success": False, "message": NOT_REGISTERED_MESSAGE, "node_proto_id": 999}


@pytest.mark.asyncio
async def test_write_config_not_registered_node_returns_428(client, tmp_path):
    """/write для ноды, которой нет в памяти нод-клиента, отвечает 428 и не трогает файл"""
    config_path = tmp_path / "config.json"
    config_path.write_text('{"inbounds": []}', encoding='utf-8')

    response = await client.post(
        "/api/v1/server/node/config/write",
        json={"node_proto_id": 999, "path": str(config_path), "content": "{}", "tmp_link": "vless://x"},
    )

    assert response.status_code == 428
    assert response.json()["node_proto_id"] == 999
    assert config_path.read_text(encoding='utf-8') == '{"inbounds": []}'


# ========== /write: перенос пользователей только по запросу (прежний контракт админки) ==========


def _write_json(path: str, data: dict) -> None:
    Path(path).write_bytes(orjson.dumps(data))


def _read_json(path: str) -> dict:
    return orjson.loads(Path(path).read_bytes())


@pytest.mark.asyncio
@pytest.mark.parametrize(("transfer_users", "expected_clients"), [(False, []), (True, [{"id": "old-user"}])])
async def test_write_config_transfers_users_only_on_request(client, tmp_path, transfer_users, expected_clients):
    """Пользователи из старого файла переносятся, только если админка попросила (transfer_users)"""
    from node_client.tests.utils.test_data_factory import create_vnode_item_with_config

    item = create_vnode_item_with_config(tmp_path, 41)
    config_path = item["filepath"]
    _write_json(config_path, {"inbounds": [{"settings": {"clients": [{"id": "old-user"}]}}]})
    await client.app.state.core_buffer.register_node(item)

    response = await client.post(
        "/api/v1/server/node/config/write",
        json={
            "node_proto_id": 41,
            "path": config_path,
            "content": orjson.dumps({"inbounds": [{"settings": {"clients": []}}]}).decode(),
            "tmp_link": "vless://x",
            "transfer_users": transfer_users,
        },
    )

    assert response.status_code == 200
    assert _read_json(config_path)["inbounds"][0]["settings"]["clients"] == expected_clients
