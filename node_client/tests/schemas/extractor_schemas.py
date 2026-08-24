"""
JSON Schema определения для валидации extractor outputs

Каждая схема соответствует конкретному (ЯДРО, ПРОТОКОЛ) комбинации.
Схемы НЕ переиспользуются между разными ядрами для избежания путаницы.

Организация:
- Схемы группируются по ядрам (XRAY, SINGBOX, и т.д.)
- В рамках одного ядра схемы могут объединяться если протоколы имеют одинаковую структуру
- Между ядрами схемы НЕ объединяются даже для одинаковых протоколов

Примеры использования:
    >>> from node_client.tests.schemas.extractor_schemas import get_schema_for_template
    >>> schema = get_schema_for_template('xray-vless-reality-tcp')
    >>> jsonschema.validate(user_dict, schema)
"""

# ========== XRAY ЯДРО ==========

XRAY_VLESS_SCHEMA = {
    "type": "object",
    "required": ["id", "email", "level"],  # flow НЕ обязателен (есть только в Reality)
    "properties": {
        "id": {
            "type": "string",
            "description": "UUID пользователя (user_uuid)"
        },
        "email": {
            "type": "string",
            "description": "ID подписки пользователя (user_sub_id)"
        },
        "flow": {
            "type": "string",
            "description": "XTLS flow control (только для Reality, опционально для TLS)",
            "enum": ["xtls-rprx-vision", "xtls-rprx-direct", ""]
        },
        "level": {
            "type": "integer",
            "description": "Уровень пользователя (обычно 0)",
            "minimum": 0
        }
    },
    "additionalProperties": False
}

XRAY_VMESS_SCHEMA = {
    "type": "object",
    "required": ["id", "email", "alterId"],
    "properties": {
        "id": {
            "type": "string",
            "description": "UUID пользователя (user_uuid)"
        },
        "email": {
            "type": "string",
            "description": "ID подписки пользователя (user_sub_id)"
        },
        "alterId": {
            "type": "integer",
            "description": "VMess alterId (обычно 0)",
            "minimum": 0
        }
    },
    "additionalProperties": False
}

XRAY_TROJAN_SHADOWSOCKS_SCHEMA = {
    "type": "object",
    "required": ["email", "password"],
    "properties": {
        "email": {
            "type": "string",
            "description": "ID подписки пользователя (user_sub_id)"
        },
        "password": {
            "type": "string",
            "description": "Пароль (user_uuid для trojan, base64 PSK для shadowsocks)"
        }
    },
    "additionalProperties": False
}

XRAY_HY2_SCHEMA = {
    "type": "object",
    "required": ["email", "auth", "level"],
    "properties": {
        "email": {
            "type": "string",
            "description": "ID подписки пользователя (user_sub_id)"
        },
        "auth": {
            "type": "string",
            "description": "Hysteria2 auth (user_uuid)"
        },
        "level": {
            "type": "integer",
            "description": "Уровень пользователя (обычно 0)",
            "minimum": 0
        }
    },
    "additionalProperties": False
}

# ========== SINGBOX ЯДРО ==========

SINGBOX_VLESS_SCHEMA = {
    "type": "object",
    "required": ["uuid", "name"],  # Sing-box использует "uuid" и "name" вместо "id" и "email"
    "properties": {
        "uuid": {
            "type": "string",
            "description": "UUID пользователя (user_uuid)"
        },
        "name": {
            "type": "string",
            "description": "Имя пользователя (user_sub_id)"
        },
        "flow": {
            "type": "string",
            "description": "XTLS flow control (только для Reality, опционально)",
            "enum": ["xtls-rprx-vision", ""]
        }
    },
    "additionalProperties": False
}

SINGBOX_VMESS_SCHEMA = {
    "type": "object",
    "required": ["uuid", "name"],
    "properties": {
        "uuid": {
            "type": "string",
            "description": "UUID пользователя (user_uuid)"
        },
        "name": {
            "type": "string",
            "description": "Имя пользователя (user_sub_id)"
        },
        "alterId": {
            "type": "integer",
            "description": "VMess alterId (обычно 0)",
            "minimum": 0
        }
    },
    "additionalProperties": False
}

SINGBOX_TROJAN_SCHEMA = {
    "type": "object",
    "required": ["name", "password"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Имя пользователя (user_sub_id)"
        },
        "password": {
            "type": "string",
            "description": "Пароль (user_uuid)"
        }
    },
    "additionalProperties": False
}

SINGBOX_SHADOWSOCKS_SCHEMA = {
    "type": "object",
    "required": ["name", "password"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Имя пользователя (user_sub_id)"
        },
        "password": {
            "type": "string",
            "description": "Base64 PSK пользователя"
        }
    },
    "additionalProperties": False
}

SINGBOX_HY2_SCHEMA = {
    "type": "object",
    "required": ["name", "password"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Имя пользователя (user_sub_id)"
        },
        "password": {
            "type": "string",
            "description": "Hysteria2 auth (user_uuid)"
        }
    },
    "additionalProperties": False
}

SINGBOX_WG_SCHEMA = {
    "type": "object",
    "required": ["name", "public_key", "allowed_ips"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Имя peer (обычно user_sub_id)"
        },
        "public_key": {
            "type": "string",
            "description": "WireGuard public key (base64)"
        },
        "preshared_key": {
            "type": "string",
            "description": "WireGuard preshared key (base64, опционально)"
        },
        "allowed_ips": {
            "type": "array",
            "description": "Разрешённые IP адреса для peer (IPv4/32 или IPv6/128)",
            "items": {
                "type": "string",
                # Паттерн поддерживает IPv4/32 и IPv6/128
                "pattern": r"^((\d{1,3}\.){3}\d{1,3}/32|([0-9a-fA-F:]+)/128)$"
            },
            "minItems": 1
        },
        "reserved": {
            "type": "array",
            "description": "WARP reserved bytes (3 байта для обхода ТСПУ блокировок)",
            "items": {
                "type": "integer",
                "minimum": 0,
                "maximum": 255
            },
            "minItems": 3,
            "maxItems": 3
        }
    },
    "additionalProperties": False
}

# ========== МАППИНГ (ЯДРО, ПРОТОКОЛ) → SCHEMA ==========

SCHEMA_MAP = {
    # XRAY ядро
    ('xray', 'vless'): XRAY_VLESS_SCHEMA,
    ('xray', 'vmess'): XRAY_VMESS_SCHEMA,
    ('xray', 'trojan'): XRAY_TROJAN_SHADOWSOCKS_SCHEMA,
    ('xray', 'shadowsocks'): XRAY_TROJAN_SHADOWSOCKS_SCHEMA,  # Объединённая схема!
    ('xray', 'hy2'): XRAY_HY2_SCHEMA,
    
    # SINGBOX ядро
    ('singbox', 'vless'): SINGBOX_VLESS_SCHEMA,
    ('singbox', 'vmess'): SINGBOX_VMESS_SCHEMA,
    ('singbox', 'trojan'): SINGBOX_TROJAN_SCHEMA,
    ('singbox', 'shadowsocks'): SINGBOX_SHADOWSOCKS_SCHEMA,
    ('singbox', 'hy2'): SINGBOX_HY2_SCHEMA,
    ('singbox', 'wg'): SINGBOX_WG_SCHEMA,
    ('singbox', 'awg'): SINGBOX_WG_SCHEMA,  # AmneziaWG использует ту же схему что и WireGuard
}


def get_schema_for_template(template_title: str) -> dict:
    """
    Возвращает JSON Schema на основе ЯДРО-ПРОТОКОЛ маппинга
    
    Формат template_title: ЯДРО-ПРОТОКОЛ-ЗАЩИТА-ПРОЧЕЕ
    Например: xray-vless-reality-tcp → (xray, vless) → XRAY_VLESS_SCHEMA
    
    Это гарантирует что:
    - xray-vless и singbox-vless будут использовать РАЗНЫЕ схемы
    - Нет ложных срабатываний при поиске по подстроке
    
    Args:
        template_title: Название шаблона из proto_templates.title
    
    Returns:
        dict: JSON Schema для валидации extractor output
    
    Raises:
        ValueError: Если формат title неправильный или схема не определена
    
    Example:
        >>> schema = get_schema_for_template('xray-vless-reality-tcp')
        >>> schema == XRAY_VLESS_SCHEMA
        True
        
        >>> schema = get_schema_for_template('xray-trojan-tls-ws')
        >>> schema == XRAY_TROJAN_SHADOWSOCKS_SCHEMA
        True
    """
    parts = template_title.split('-')
    if len(parts) < 2:
        raise ValueError(
            f"Invalid template title format: '{template_title}'. "
            f"Expected format: ЯДРО-ПРОТОКОЛ-ЗАЩИТА-ПРОЧЕЕ"
        )
    
    core_name = parts[0]
    protocol_name = parts[1]
    
    key = (core_name, protocol_name)
    if key not in SCHEMA_MAP:
        available_keys = sorted(SCHEMA_MAP.keys())
        raise ValueError(
            f"No schema defined for ({core_name}, {protocol_name}). "
            f"Please add it to SCHEMA_MAP in extractor_schemas.py. "
            f"Available schemas: {available_keys}"
        )
    
    return SCHEMA_MAP[key]


def get_expected_type_for_cursor(flatten_array_cursor: str) -> str:
    """
    Определяет ожидаемый тип результата extractor по flatten_array_cursor
    
    Разные cursor'ы ожидают разные типы результатов:
    - 'inbounds___X___clients' → dict (пользователи протокола)
    - 'inbounds___X___users' → dict (пользователи протокола)
    - 'inbounds___X___peers' → dict (WireGuard peers)
    - 'experimental___v2ray_api___stats___users' → string (user_sub_id для метрик)
    
    Args:
        flatten_array_cursor: Путь к массиву в конфиге (например, 'inbounds___0___settings___clients')
    
    Returns:
        'dict' | 'string': Ожидаемый тип элемента массива
    
    Example:
        >>> get_expected_type_for_cursor('inbounds___0___settings___clients')
        'dict'
        
        >>> get_expected_type_for_cursor('experimental___v2ray_api___stats___users')
        'string'
    """
    # Специальный случай: v2ray_api статистика ожидает список строк (user_sub_id)
    if 'stats___users' in flatten_array_cursor:
        return 'string'
    
    # Все остальные случаи: dict объекты пользователей
    # (clients, users, peers, и т.д.)
    return 'dict'
