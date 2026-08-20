"""
Helper функции для тестирования extractor скриптов

Основные задачи:
1. Извлечение используемых ключей из extractor скриптов (для constant_node_data_obj)
2. Генерация mock constant_node_data_obj на основе найденных ключей
"""
import re


def extract_node_keys_from_extractor(extractor_script: str) -> list[str]:
    """
    Парсит extractor скрипт и извлекает используемые ключи из constant_node_data_obj
    
    Ищет паттерны:
    - user_obj['key']
    - user_obj["key"]
    - user_obj.get('key')
    - user_obj.get("key")
    
    Возвращает ТОЛЬКО ключи с префиксом 'node_*':
    - 'node_hash_salt' → соль для генерации ключей
    - 'node_ipv4_subnet' → подсеть для WireGuard
    - 'node_public_key' → публичный ключ ноды
    
    НЕ включает:
    - 'user_uuid', 'user_sub_id' → идут из required_user_data_obj
    - Любые другие ключи без префикса 'node_'
    
    Args:
        extractor_script: Код transform функции
    
    Returns:
        Список уникальных ключей для constant_node_data_obj
    
    Example:
        >>> script = '''
        ... def transform(user_obj: dict) -> dict:
        ...     salt = user_obj.get("node_hash_salt", "")
        ...     subnet = user_obj["node_ipv4_subnet"]
        ...     user_id = user_obj["user_sub_id"]  # НЕ node_ ключ
        ...     return {...}
        ... '''
        >>> extract_node_keys_from_extractor(script)
        ['node_hash_salt', 'node_ipv4_subnet']
    """
    # Регулярка для поиска user_obj['key'] или user_obj.get('key')
    pattern = r"user_obj(?:\['([^']+)'\]|\[\"([^\"]+)\"\]|\.get\('([^']+)'\)|\.get\(\"([^\"]+)\"\))"
    
    matches = re.findall(pattern, extractor_script)
    
    # Flatten список кортежей (из-за групп в regex)
    keys = [match for group in matches for match in group if match]
    
    # Убираем дубликаты
    keys = list(set(keys))
    
    # Фильтруем ТОЛЬКО ключи из constant_node_data_obj (с префиксом 'node_')
    node_keys = [key for key in keys if key.startswith('node_')]
    
    return node_keys


def generate_mock_value_for_node_key(key: str) -> str | int | bool:
    """
    Генерирует mock значение для node_ ключа на основе его имени
    
    Типовые паттерны:
    - node_hash_salt → str (соль для генерации ключей)
    - node_ipv4_subnet → str (CIDR подсеть для WireGuard)
    - node_public_key → str (base64 ключ)
    - node_*_port → int (порт)
    - остальное → str ('mock_<key>')
    
    Args:
        key: Название ключа (например, 'node_hash_salt')
    
    Returns:
        Mock значение подходящего типа
    
    Example:
        >>> generate_mock_value_for_node_key('node_hash_salt')
        'test_salt_12345'
        
        >>> generate_mock_value_for_node_key('node_ipv4_subnet')
        '172.16.0.0/16'
    """
    key_lower = key.lower()
    
    # Специфичные паттерны для node_ ключей
    if 'hash_salt' in key_lower or 'salt' in key_lower:
        return 'test_salt_12345'
    elif 'ipv4_subnet' in key_lower or 'subnet' in key_lower:
        return '172.16.0.0/16'
    elif 'ipv6_subnet' in key_lower:
        return 'fd00::/64'
    elif 'public_key' in key_lower or 'pubkey' in key_lower:
        return 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop'  # 44 символа base64
    elif 'private_key' in key_lower or 'privkey' in key_lower:
        return 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN=='  # 44 символа base64
    elif 'port' in key_lower:
        return 443
    elif 'address' in key_lower or 'ip' in key_lower:
        return '192.168.1.100'
    else:
        # Дефолтное значение для неизвестных ключей
        return f'mock_{key}'


def generate_constant_node_data_obj_for_extractor(extractor_script: str) -> dict:
    """
    Генерирует mock constant_node_data_obj на основе ключей из extractor скрипта
    
    Извлекает только ключи с префиксом 'node_'.
    Для каждого ключа подставляет типовое mock значение.
    
    Args:
        extractor_script: Код transform функции
    
    Returns:
        dict для constant_node_data_obj (может быть пустым {})
    
    Example:
        >>> script = '''
        ... def transform(user_obj: dict) -> dict:
        ...     salt = user_obj.get("node_hash_salt", "")
        ...     subnet = user_obj["node_ipv4_subnet"]
        ...     return {...}
        ... '''
        >>> generate_constant_node_data_obj_for_extractor(script)
        {'node_hash_salt': 'test_salt_12345', 'node_ipv4_subnet': '172.16.0.0/16'}
    """
    node_keys = extract_node_keys_from_extractor(extractor_script)
    
    result = {}
    for key in node_keys:
        result[key] = generate_mock_value_for_node_key(key)
    
    return result
