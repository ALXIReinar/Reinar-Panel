"""
Хелперы для генерации тестовых данных в нод-клиенте

Переиспользует логику из web/sub для эвристического определения
полей constant_node_data_obj на основе анализа кода скриптов.
"""
import re


def extract_node_fields_from_script(script_code: str) -> list[str]:
    """
    Парсит API скрипт и извлекает используемые node_* ключи
    
    Ищет паттерны:
    - u['node_key'] или u["node_key"]
    - u.get('node_key') или u.get("node_key")
    - user_obj['node_key'] и т.д.
    
    Возвращает ТОЛЬКО ключи с префиксом 'node_*'
    
    Args:
        script_code: Код API скрипта (bulk_add, bulk_delete, и т.д.)
    
    Returns:
        Список уникальных node_* ключей
    
    Example:
        >>> script = "password = u['node_method'] if u.get('node_method') else 'default'"
        >>> extract_node_fields_from_script(script)
        ['node_method']
    """
    # Регулярка для user_obj['key'], u['key'], u.get('key') и т.д.
    patterns = [
        r"(?:user_obj|u)(?:\['([^']+)'\]|\[\"([^\"]+)\"\]|\.get\('([^']+)'\)|\.get\(\"([^\"]+)\"\))"
    ]
    
    all_keys = []
    for pattern in patterns:
        matches = re.findall(pattern, script_code)
        # Flatten список кортежей (из-за групп в regex)
        keys = [match for group in matches for match in group if match]
        all_keys.extend(keys)
    
    # Убираем дубликаты и фильтруем только node_* ключи
    node_keys = list(set([key for key in all_keys if key.startswith('node_')]))
    
    return node_keys


def generate_mock_node_data(script_code: str) -> dict:
    """
    Генерирует mock constant_node_data_obj на основе ключей из API скрипта
    
    Извлекает node_* ключи и подставляет типовые mock значения.
    
    Args:
        script_code: Код API скрипта
    
    Returns:
        dict для constant_node_data_obj
    
    Example:
        >>> script = "password = hashlib.sha256(u['node_method'].encode()).digest()"
        >>> generate_mock_node_data(script)
        {'node_method': 'aes-256-gcm'}
    """
    keys = extract_node_fields_from_script(script_code)
    
    # Mock значения для типовых node_* ключей
    mock_values = {
        'node_method': 'aes-256-gcm',  # Shadowsocks encryption method
        'node_public_key': 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop',  # 44 символа base64
        'node_short_id': '0123456789abcdef',  # Reality short ID
        'node_server_name': 'example.com',  # SNI для TLS
        'node_ipv6_subnet': 'fd00::/64',  # IPv6 подсеть
        'node_ipv4_subnet': '10.0.0.0/24',  # IPv4 подсеть
        'node_port': 443,  # Порт сервера
        'node_hop_start': 10000,  # Port hopping start
        'node_hop_end': 20000,  # Port hopping end
        'node_hash_salt': 'test_salt',  # Salt для ключей
    }
    
    result = {}
    for key in keys:
        result[key] = mock_values.get(key, f'mock_{key}')
    
    return result
