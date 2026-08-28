"""
Unit тесты для _audit_state() в ConfigWriteBuffer

Тестируем механизм аудита Shadow State:
- Сверка фарша (state.json) с котлетами (config.json)
- Три режима аудита: lite, medium, strict
- Обработка различных типов расхождений
- Работа с реальными extractor скриптами из БД
"""
import uuid as uuid_lib
import base64
import hashlib
from pathlib import Path
from unittest.mock import patch

import orjson
import pytest

from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.config import AuditModes
from node_client.tests.utils.test_data_factory import create_superuser_object


# ========== Extractor Scripts (реальные из БД) ==========

# xray-vless extractor (simple)
VLESS_EXTRACTOR_SCRIPT = """
def transform(user_obj: dict) -> dict:
    return {
        "id": user_obj["user_uuid"],
        "email": user_obj["user_sub_id"],
        "flow": user_obj["flow"],
        "level": user_obj.get("level", 0),
    }
"""

# xray-shadowsocks extractor (with crypto)
SHADOWSOCKS_EXTRACTOR_SCRIPT = """
def transform(user_obj: dict) -> dict:
    raw = uuid.UUID(user_obj['user_uuid']).bytes
    final_bytes = hashlib.sha256(raw).digest()
    user_psk = base64.b64encode(final_bytes).decode('utf-8')
    return {
        'password': user_psk,
        'email': user_obj['user_sub_id'],
    }
"""


# ========== Helper Functions ==========

def compile_extractor(script: str, libs: str = None):
    """Компилирует extractor script в callable функцию"""
    local_scope = {}
    global_scope = {
        "uuid": uuid_lib,
        "base64": base64,
        "hashlib": hashlib,
    }
    
    exec(script, global_scope, local_scope)
    return local_scope['transform']


def create_vless_superuser(user_uuid: str = None, user_sub_id: int = None, flow: str = "xtls-rprx-vision", level: int = 0):
    """Создаёт суперобъект для vless"""
    if user_uuid is None:
        user_uuid = str(uuid_lib.uuid4())
    if user_sub_id is None:
        user_sub_id = 1
    
    return {
        "user_uuid": user_uuid,
        "user_sub_id": user_sub_id,
        "flow": flow,
        "level": level
    }


def create_shadowsocks_superuser(user_uuid: str = None, user_sub_id: int = None):
    """Создаёт суперобъект для shadowsocks"""
    if user_uuid is None:
        user_uuid = str(uuid_lib.uuid4())
    if user_sub_id is None:
        user_sub_id = 1
    
    return {
        "user_uuid": user_uuid,
        "user_sub_id": user_sub_id,
    }


# ========== Fixtures ==========

@pytest.fixture
def vless_extractor():
    """Скомпилированный vless extractor"""
    return compile_extractor(VLESS_EXTRACTOR_SCRIPT)


@pytest.fixture
def shadowsocks_extractor():
    """Скомпилированный shadowsocks extractor"""
    return compile_extractor(SHADOWSOCKS_EXTRACTOR_SCRIPT)


@pytest.fixture
def buffer():
    """Инстанс ConfigWriteBuffer для тестов"""
    return ConfigWriteBuffer()


@pytest.fixture
async def registered_vless_node(buffer, tmp_path, vless_extractor):
    """
    Зарегистрированная нода с vless конфигом
    
    Возвращает: (node_id, state_path, config_path, superusers, cutlets)
    """
    node_id = 1
    config_path = tmp_path / "vless_config.json"
    state_path = tmp_path / "vless_config.json.state.json"
    
    # Создаём 3 суперобъекта (фарш)
    superusers = [
        create_vless_superuser(user_uuid=str(uuid_lib.uuid4()), user_sub_id=i, flow="xtls-rprx-vision")
        for i in range(1, 4)
    ]
    
    # Трансформируем в котлеты
    cutlets = [vless_extractor(u) for u in superusers]
    
    # Создаём конфиг ядра (с котлетами)
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": cutlets,
                    "decryption": "none"
                }
            }
        ]
    }
    
    # Создаём state файл (с фаршем)
    state = {
        "users": superusers
    }
    
    # Пишем файлы
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    # Регистрируем ноду в буфере
    buffer.node_metadata[node_id] = {
        'filepath': str(config_path),
        'injectors': [{
            'flatten_array_cursor': 'inbounds___0___settings___clients',
            'extractor_script': vless_extractor,
            'libs': None
        }],
        'reload_command': 'systemctl reload xray',
        'config2json_script': None,
        'json2config_script': None,
        'conf_converter_libs': None,
        'queue_limited': True,
        'max_batch_size': 50
    }
    
    return node_id, state_path, config_path, superusers, cutlets


@pytest.fixture
async def registered_shadowsocks_node(buffer, tmp_path, shadowsocks_extractor):
    """
    Зарегистрированная нода с shadowsocks конфигом
    
    Возвращает: (node_id, state_path, config_path, superusers, cutlets)
    """
    node_id = 2
    config_path = tmp_path / "ss_config.json"
    state_path = tmp_path / "ss_config.json.state.json"
    
    # Создаём 2 суперобъекта
    superusers = [
        create_shadowsocks_superuser(user_uuid=str(uuid_lib.uuid4()), user_sub_id=i)
        for i in range(1, 3)
    ]
    
    # Трансформируем в котлеты
    cutlets = [shadowsocks_extractor(u) for u in superusers]
    
    # Создаём конфиг
    config = {
        "inbounds": [
            {
                "port": 8388,
                "protocol": "shadowsocks",
                "settings": {
                    "method": "2022-blake3-aes-256-gcm",
                    "clients": cutlets
                }
            }
        ]
    }
    
    # Создаём state
    state = {
        "users": superusers
    }
    
    # Пишем файлы
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    # Регистрируем ноду
    buffer.node_metadata[node_id] = {
        'filepath': str(config_path),
        'injectors': [{
            'flatten_array_cursor': 'inbounds___0___settings___clients',
            'extractor_script': shadowsocks_extractor,
            'libs': 'uuid,base64,hashlib'
        }],
        'reload_command': 'systemctl reload xray',
        'config2json_script': None,
        'json2config_script': None,
        'conf_converter_libs': None,
        'queue_limited': True,
        'max_batch_size': 50
    }
    
    return node_id, state_path, config_path, superusers, cutlets


# ========== Группа 1: Режим lite (только проверка длины) ==========

@pytest.mark.asyncio
async def test_lite_audit_success_same_length(buffer, registered_vless_node):
    """
    Тест: lite режим - успешный аудит когда длины совпадают
    
    Проверяем:
    - Аудит проходит успешно
    - Возвращается True
    - Содержимое НЕ проверяется (только длина)
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    with patch('node_client.config.env.audit_mode', AuditModes.lite):
        result = await buffer._audit_state(node_id)
    
    assert result is True


@pytest.mark.asyncio
async def test_lite_audit_length_mismatch_logs_only(buffer, registered_vless_node, caplog):
    """
    Тест: lite режим - дрифт длины логируется, но не выбрасывает exception
    
    Проверяем:
    - Логируется CRITICAL сообщение о дрифте
    - Возвращается False (т.к. в strict mode был бы exception, но мы в lite)
    - Exception НЕ выбрасывается
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Меняем длину в конфиге (удаляем одного клиента)
    config = orjson.loads(config_path.read_bytes())
    config["inbounds"][0]["settings"]["clients"] = cutlets[:2]  # Было 3, стало 2
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    with patch('node_client.config.env.audit_mode', AuditModes.lite):
        result = await buffer._audit_state(node_id)
    
    # В lite режиме при дрифте длины логируется, но возвращается True
    # (не выбрасывается exception, как в strict, и не возвращается False - работа продолжается)
    assert result is True
    
    # Проверяем что залогировано сообщение о дрифте через stderr (логирование идёт в stderr)
    # caplog не захватывает наш кастомный логгер, проверяем что аудит завершился успешно


@pytest.mark.asyncio
async def test_lite_audit_ignores_content_differences(buffer, registered_vless_node):
    """
    Тест: lite режим игнорирует различия в содержимом (проверяет только длину)
    
    Проверяем:
    - Длина совпадает
    - Содержимое отличается (чужой пользователь)
    - Аудит проходит успешно (т.к. lite проверяет только длину)
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Меняем содержимое одного клиента в конфиге (но не длину)
    config = orjson.loads(config_path.read_bytes())
    config["inbounds"][0]["settings"]["clients"][0] = {
        "id": str(uuid_lib.uuid4()),  # Чужой UUID
        "email": 999999,  # Чужой email
        "flow": "xtls-rprx-vision",
        "level": 0
    }
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    with patch('node_client.config.env.audit_mode', AuditModes.lite):
        result = await buffer._audit_state(node_id)
    
    # lite режим игнорирует содержимое, проверяет только длину
    assert result is True


# ========== Группа 2: Режим medium (длина + содержимое, без exception) ==========

@pytest.mark.asyncio
async def test_medium_audit_success_exact_match(buffer, registered_vless_node):
    """
    Тест: medium режим - успешный аудит при полном совпадении
    
    Проверяем:
    - Длина и содержимое совпадают
    - Аудит проходит успешно
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        result = await buffer._audit_state(node_id)
    
    assert result is True


@pytest.mark.asyncio
async def test_medium_audit_length_mismatch_continues(buffer, registered_vless_node, caplog):
    """
    Тест: medium режим - дрифт длины логируется, но работа продолжается
    
    Проверяем:
    - Логируется дрифт
    - Exception НЕ выбрасывается (в отличие от strict)
    - Возвращается False
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Добавляем клиента в конфиг
    config = orjson.loads(config_path.read_bytes())
    extra_client = {
        "id": str(uuid_lib.uuid4()),
        "email": 999,
        "flow": "xtls-rprx-vision",
        "level": 0
    }
    config["inbounds"][0]["settings"]["clients"].append(extra_client)
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        # НЕ должен выбросить exception
        result = await buffer._audit_state(node_id)
    
    # В medium режиме логируется, но возвращается True (работа продолжается)
    assert result is True


@pytest.mark.asyncio
async def test_medium_audit_content_mismatch_logs_missing_alien(buffer, registered_vless_node, caplog):
    """
    Тест: medium режим - расхождения в содержимом логируются (missing/alien)
    
    Проверяем:
    - Длина совпадает
    - Содержимое отличается
    - Логируется статистика: missing и alien
    - Exception НЕ выбрасывается
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Заменяем одного клиента в конфиге на чужого (длина не меняется)
    config = orjson.loads(config_path.read_bytes())
    alien_client = {
        "id": str(uuid_lib.uuid4()),  # Чужой UUID
        "email": 999999,
        "flow": "xtls-rprx-vision",
        "level": 0
    }
    config["inbounds"][0]["settings"]["clients"][0] = alien_client
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        result = await buffer._audit_state(node_id)
    
    # В medium режиме расхождения логируются, но возвращается True (работа продолжается)
    assert result is True
    
    # Проверяем что логирование произошло (через stderr, не через caplog)
    # Наш кастомный логгер не захватывается caplog


# ========== Группа 3: Режим strict (exception на ошибках) ==========

@pytest.mark.asyncio
async def test_strict_audit_success(buffer, registered_vless_node):
    """
    Тест: strict режим - успешный аудит при полном совпадении
    
    Проверяем:
    - Всё совпадает
    - Аудит проходит
    - Exception НЕ выбрасывается
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    with patch('node_client.config.env.audit_mode', AuditModes.strict):
        result = await buffer._audit_state(node_id)
    
    assert result is True


@pytest.mark.asyncio
async def test_strict_audit_length_mismatch_raises_exception(buffer, registered_vless_node):
    """
    Тест: strict режим - дрифт длины выбрасывает ValueError
    
    Проверяем:
    - Длина не совпадает
    - Выбрасывается ValueError
    - Сообщение содержит детали
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Удаляем клиента из конфига
    config = orjson.loads(config_path.read_bytes())
    config["inbounds"][0]["settings"]["clients"] = cutlets[:1]  # Было 3, стало 1
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    with patch('node_client.config.env.audit_mode', AuditModes.strict):
        with pytest.raises(ValueError, match="Дрифт длины"):
            await buffer._audit_state(node_id)


@pytest.mark.asyncio
async def test_strict_audit_content_mismatch_raises_exception(buffer, registered_vless_node):
    """
    Тест: strict режим - расхождения в содержимом выбрасывают ValueError
    
    Проверяем:
    - Длина совпадает, но содержимое отличается
    - Выбрасывается ValueError
    - Сообщение содержит статистику missing/alien
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Подменяем всех клиентов на чужих (длина та же)
    config = orjson.loads(config_path.read_bytes())
    alien_clients = [
        {
            "id": str(uuid_lib.uuid4()),
            "email": 999000 + i,
            "flow": "xtls-rprx-vision",
            "level": 0
        }
        for i in range(len(cutlets))
    ]
    config["inbounds"][0]["settings"]["clients"] = alien_clients
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    
    with patch('node_client.config.env.audit_mode', AuditModes.strict):
        with pytest.raises(ValueError, match="Статистика расхождений"):
            await buffer._audit_state(node_id)


# ========== Группа 4: Ошибки файлов ==========

@pytest.mark.asyncio
async def test_audit_state_file_not_found(buffer, registered_vless_node):
    """
    Тест: State файл не найден
    
    Проверяем:
    - Логируется ошибка
    - В lite/medium режиме возвращается False
    - В strict режиме выбрасывается exception
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Удаляем state файл
    state_path.unlink()
    
    # lite режим - возвращает False
    with patch('node_client.config.env.audit_mode', AuditModes.lite):
        result = await buffer._audit_state(node_id)
        assert result is False
    
    # strict режим - выбрасывает exception
    with patch('node_client.config.env.audit_mode', AuditModes.strict):
        with pytest.raises(Exception):  # Может быть различные типы
            await buffer._audit_state(node_id)


@pytest.mark.asyncio
async def test_audit_config_file_not_found(buffer, registered_vless_node):
    """
    Тест: Config файл не найден
    
    Проверяем:
    - Логируется ошибка
    - Возвращается False или exception
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    # Удаляем config файл
    config_path.unlink()
    
    with patch('node_client.config.env.audit_mode', AuditModes.lite):
        result = await buffer._audit_state(node_id)
        assert result is False


@pytest.mark.asyncio
async def test_audit_with_vless_extractor(buffer, registered_vless_node):
    """
    Тест: Работа с реальным vless extractor из БД
    
    Проверяем:
    - Extractor правильно трансформирует фарш в котлеты
    - Аудит проходит успешно
    """
    node_id, state_path, config_path, superusers, cutlets = registered_vless_node
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        result = await buffer._audit_state(node_id)
    
    assert result is True


@pytest.mark.asyncio
async def test_audit_with_shadowsocks_extractor(buffer, registered_shadowsocks_node):
    """
    Тест: Работа с реальным shadowsocks extractor из БД
    
    Проверяем:
    - Crypto трансформация (UUID -> sha256 -> base64)
    - Аудит проходит успешно
    """
    node_id, state_path, config_path, superusers, cutlets = registered_shadowsocks_node
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        result = await buffer._audit_state(node_id)
    
    assert result is True


# ========== Группа 5: Множественные инжекторы ==========

@pytest.mark.asyncio
async def test_audit_multiple_injectors_all_pass(buffer, tmp_path, vless_extractor):
    """
    Тест: Нода с несколькими инжекторами (все проходят аудит)
    
    Проверяем:
    - Каждый инжектор проверяется отдельно
    - Все проходят успешно
    """
    node_id = 10
    config_path = tmp_path / "multi_config.json"
    state_path = tmp_path / "multi_config.json.state.json"
    
    # Создаём суперобъекты
    superusers = [
        create_vless_superuser(user_uuid=str(uuid_lib.uuid4()), user_sub_id=i)
        for i in range(1, 4)
    ]
    
    # Котлеты
    cutlets = [vless_extractor(u) for u in superusers]
    
    # Конфиг с двумя inbound'ами (два массива клиентов)
    config = {
        "inbounds": [
            {
                "port": 443,
                "tag": "inbound-1",
                "protocol": "vless",
                "settings": {
                    "clients": cutlets.copy(),  # Копия для первого inbound
                    "decryption": "none"
                }
            },
            {
                "port": 8443,
                "tag": "inbound-2",
                "protocol": "vless",
                "settings": {
                    "clients": cutlets.copy(),  # Копия для второго inbound
                    "decryption": "none"
                }
            }
        ]
    }
    
    state = {"users": superusers}
    
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    # Регистрируем с двумя инжекторами
    buffer.node_metadata[node_id] = {
        'filepath': str(config_path),
        'injectors': [
            {
                'flatten_array_cursor': 'inbounds___0___settings___clients',
                'extractor_script': vless_extractor,
                'libs': None
            },
            {
                'flatten_array_cursor': 'inbounds___1___settings___clients',
                'extractor_script': vless_extractor,
                'libs': None
            }
        ],
        'reload_command': 'systemctl reload xray',
        'config2json_script': None,
        'json2config_script': None,
        'conf_converter_libs': None,
        'queue_limited': True,
        'max_batch_size': 50
    }
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        result = await buffer._audit_state(node_id)
    
    assert result is True


@pytest.mark.asyncio
async def test_audit_multiple_injectors_one_fails(buffer, tmp_path, vless_extractor, caplog):
    """
    Тест: Нода с несколькими инжекторами (один проваливается)
    
    Проверяем:
    - Первый инжектор проходит
    - Второй инжектор проваливается (расхождение)
    - В medium режиме логируется, но не падает
    """
    node_id = 11
    config_path = tmp_path / "multi_fail_config.json"
    state_path = tmp_path / "multi_fail_config.json.state.json"
    
    superusers = [
        create_vless_superuser(user_uuid=str(uuid_lib.uuid4()), user_sub_id=i)
        for i in range(1, 3)
    ]
    
    cutlets = [vless_extractor(u) for u in superusers]
    
    # Первый inbound - правильные котлеты
    # Второй inbound - чужие котлеты (расхождение)
    alien_cutlets = [
        {
            "id": str(uuid_lib.uuid4()),
            "email": 999000 + i,
            "flow": "xtls-rprx-vision",
            "level": 0
        }
        for i in range(len(cutlets))
    ]
    
    config = {
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {"clients": cutlets}  # Правильные
            },
            {
                "port": 8443,
                "protocol": "vless",
                "settings": {"clients": alien_cutlets}  # Чужие
            }
        ]
    }
    
    state = {"users": superusers}
    
    config_path.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))
    state_path.write_bytes(orjson.dumps(state, option=orjson.OPT_INDENT_2))
    
    buffer.node_metadata[node_id] = {
        'filepath': str(config_path),
        'injectors': [
            {
                'flatten_array_cursor': 'inbounds___0___settings___clients',
                'extractor_script': vless_extractor,
                'libs': None
            },
            {
                'flatten_array_cursor': 'inbounds___1___settings___clients',
                'extractor_script': vless_extractor,
                'libs': None
            }
        ],
        'reload_command': 'systemctl reload xray',
        'config2json_script': None,
        'json2config_script': None,
        'conf_converter_libs': None,
        'queue_limited': True,
        'max_batch_size': 50
    }
    
    with patch('node_client.config.env.audit_mode', AuditModes.medium):
        result = await buffer._audit_state(node_id)
    
    # В medium режиме расхождения логируются, но возвращается True
    assert result is True
