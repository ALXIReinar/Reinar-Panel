"""
Фабрики для создания тестовых данных
"""

import uuid as uuid_lib

import orjson


def create_test_user(
    email: str | None = None,
    uuid: str | None = None,
    flow: str = "xtls-rprx-vision",
    level: int = 0,
    as_superuser: bool = True,
) -> dict:
    """
    Создаёт тестового пользователя

    Args:
        email: Email пользователя (генерируется если None)
        uuid: UUID пользователя (генерируется если None)
        flow: Flow для VLESS (по умолчанию xtls-rprx-vision)
        level: Уровень пользователя
        as_superuser: Если True, создаёт суперобъект с user_uuid (для buffer_storage)
                      Если False, создаёт объект ядра с id (для конфига xray)

    Returns:
        dict: Объект пользователя

    Example (суперобъект для buffer):
        >>> user = create_test_user()
        >>> user
        {
            "user_uuid": "550e8400-e29b-41d4-a716-446655440000",
            "email": "test_user_550e8400",
            "flow": "xtls-rprx-vision",
            "level": 0
        }

    Example (объект для конфига ядра):
        >>> user = create_test_user(as_superuser=False)
        >>> user
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "email": "test_user_550e8400",
            "flow": "xtls-rprx-vision",
            "level": 0
        }
    """
    if uuid is None:
        uuid = str(uuid_lib.uuid4())
    if email is None:
        # Генерируем email на основе первых 8 символов UUID
        email = f"test_user_{uuid[:8]}"
    if as_superuser:
        # Суперобъект для buffer_storage (используется в новой архитектуре)
        return {"user_uuid": uuid, "email": email, "flow": flow, "level": level}
    else:
        # Объект для конфига ядра (старый формат, используется в fixtures)
        return {"id": uuid, "email": email, "flow": flow, "level": level}


def create_bulk_test_users(count: int, prefix: str = "bulk_user") -> list[dict]:
    """
    Создаёт список тестовых пользователей

    Args:
        count: Количество пользователей
        prefix: Префикс для email

    Returns:
        list[dict]: Список пользователей

    Example:
        >>> users = create_bulk_test_users(3, "test")
        >>> len(users)
        3
    """
    return [create_test_user(email=f"{prefix}_{i}") for i in range(count)]


def create_user_injectors(
    flatten_array_cursor: str = "inbounds___0___settings___clients",
    extractor_script: str | None = None,
    libs: str | None = None,
) -> list[dict]:
    """
    Создаёт user_injectors для ConfigWriteBuffer в новом формате

    Args:
        flatten_array_cursor: Путь к массиву в JSON конфиге (flatten format)
        extractor_script: Скрипт трансформации user_obj для ядра
        libs: Библиотеки для скрипта (например, 'grpcio,requests')

    Returns:
        list[dict]: Список инжекторов с flatten_array_cursor, extractor_script, libs

    Example:
        >>> injectors = create_user_injectors()
        >>> injectors[0]['flatten_array_cursor']
        'inbounds___0___settings___clients'

    Notes:
        - Дефолтный extractor_script преобразует user_obj в формат xray/vless
        - Скрипт должен содержать функцию transform(user_obj) -> dict
    """
    if extractor_script is None:
        # Дефолтный скрипт для xray/vless конфигов
        # Преобразует наш внутренний формат в формат ядра
        extractor_script = """
def transform(user_obj):
    '''Трансформирует суперобъект в объект для ядра xray/vless'''
    return {
        'id': user_obj.get('user_uuid', user_obj.get('id')),
        'email': user_obj.get('email', 'test@test.com'),
        'flow': user_obj.get('flow', 'xtls-rprx-vision'),
        'level': user_obj.get('level', 0)
    }
"""
    return [{'flatten_array_cursor': flatten_array_cursor, 'extractor_script': extractor_script, 'libs': libs}]


def create_superuser_object(
    user_uuid: str | None = None,
    email: str | None = None,
    flow: str = "xtls-rprx-vision",
    level: int = 0,
    **extra_fields,
) -> dict:
    """
    Создаёт суперобъект пользователя для buffer_storage

    Args:
        user_uuid: UUID пользователя (генерируется если None)
        email: Email пользователя (генерируется если None)
        flow: Flow для VLESS
        level: Уровень пользователя
        **extra_fields: Дополнительные поля для суперобъекта

    Returns:
        dict: Суперобъект пользователя с user_uuid в качестве ключа

    Example:
        >>> superuser = create_superuser_object()
        >>> 'user_uuid' in superuser
        True

    Notes:
        - Суперобъект хранится в buffer_storage
        - Из суперобъекта получаются "котлеты" через extractor_script
        - user_uuid используется как ключ в buffer_storage[node_proto_id][user_uuid]
    """
    if user_uuid is None:
        user_uuid = str(uuid_lib.uuid4())
    if email is None:
        email = f"test_user_{user_uuid[:8]}"
    superuser = {"user_uuid": user_uuid, "email": email, "flow": flow, "level": level, **extra_fields}
    return superuser


def create_vnode_service_data(
    node_proto_id: int = 1,
    filepath: str = "/tmp/config.json",
    user_injectors: list[dict] | None = None,
    reload_command: str | None = None,
    config2json_script: str | None = None,
    json2config_script: str | None = None,
    conf_converter_libs: str | None = None,
    api_bulk_add_user_script: str | None = None,
    api_bulk_delete_user_script: str | None = None,
    metrics_command: str | None = None,
    api_metrics_script: str | None = None,
    proto_python_lib: str | None = None,
    metrics_parser_code: str | None = None,
) -> dict:
    """Создаёт тестовый словарь VnodeServiceData для ConfigWriteBuffer.register_node"""
    if user_injectors is None:
        user_injectors = create_user_injectors()
    return {
        'node_proto_id': node_proto_id,
        'filepath': filepath,
        'user_injectors': user_injectors,
        'reload_command': reload_command,
        'config2json_script': config2json_script,
        'json2config_script': json2config_script,
        'conf_converter_libs': conf_converter_libs,
        'api_bulk_add_user_script': api_bulk_add_user_script,
        'api_bulk_delete_user_script': api_bulk_delete_user_script,
        'metrics_command': metrics_command,
        'api_metrics_script': api_metrics_script,
        'proto_python_lib': proto_python_lib,
        'metrics_parser_code': metrics_parser_code,
    }


def create_vnode_item_with_config(tmp_path, node_proto_id: int, extractor_script: str | None = None) -> dict:
    """
    Создаёт JSON-конфиг виртуальной ноды в tmp_path и элемент ответа /startup для неё.

    Конфиг минимальный: массив клиентов по курсору инжектора по умолчанию (inbounds___0___settings___clients).
    """
    config_path = tmp_path / f"node_{node_proto_id}.json"
    config_path.write_bytes(orjson.dumps({"inbounds": [{"settings": {"clients": []}}]}))
    return create_vnode_service_data(
        node_proto_id=node_proto_id,
        filepath=str(config_path),
        user_injectors=create_user_injectors(extractor_script=extractor_script),
    )
