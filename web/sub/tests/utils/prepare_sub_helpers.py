"""
Helper функции для тестирования prepare_sub скриптов

Основные задачи:
1. Извлечение используемых ключей из prepare_sub скриптов (для constant_node_data_obj)
2. Генерация mock constant_node_data_obj
3. Рендеринг config_link через локальную копию generate_link_from_json
"""
import re
from urllib.parse import quote
from jinja2 import Template
from flatten_json import flatten
from pydantic import IPvAnyAddress
import orjson


def extract_user_obj_keys(script_code: str) -> list[str]:
    """
    Парсит prepare_sub скрипт и извлекает используемые ключи из constant_node_data_obj
    
    Ищет паттерны:
    - user_obj['key']
    - user_obj["key"]
    - user_obj.get('key')
    - user_obj.get("key")
    
    Возвращает ТОЛЬКО ключи с префиксами:
    - 'sub_link_*' → параметры для подписки (fp, grpc_mode, и т.д.)
    - 'node_*' → параметры ноды (public_key, и т.д.)
    
    НЕ включает:
    - 'user_uuid', 'user_sub_id' → идут из required_user_data_obj
    - 'node_address', 'node_title' → подставляются через generate_link_from_json
    
    Args:
        script_code: Код prepare_sub функции
    
    Returns:
        Список уникальных ключей для constant_node_data_obj
    
    Example:
        >>> script = "return config_link.format(user_uuid=user_obj['user_uuid'], fp=user_obj['sub_link_fp'])"
        >>> extract_user_obj_keys(script)
        ['sub_link_fp']
    """
    # Регулярка для поиска user_obj['key'] или user_obj.get('key')
    pattern = r"user_obj(?:\['([^']+)'\]|\[\"([^\"]+)\"\]|\.get\('([^']+)'\)|\.get\(\"([^\"]+)\"\))"
    
    matches = re.findall(pattern, script_code)
    
    # Flatten список кортежей (из-за групп в regex)
    keys = [match for group in matches for match in group if match]
    
    # Убираем дубликаты
    keys = list(set(keys))
    
    # Фильтруем ТОЛЬКО ключи из constant_node_data_obj (с префиксами)
    constant_keys = [
        key for key in keys 
        if key.startswith('sub_link_') or key.startswith('node_')
    ]
    
    return constant_keys


def generate_constant_node_data_obj(script_code: str) -> dict:
    """
    Генерирует mock constant_node_data_obj на основе ключей из prepare_sub скрипта
    
    Извлекает только ключи с префиксами 'sub_link_' и 'node_'.
    Для каждого ключа подставляет типовое mock значение.
    
    НЕ включает 'node_address' и 'node_title' - они подставляются через generate_link_from_json.
    
    Args:
        script_code: Код prepare_sub функции
    
    Returns:
        dict для constant_node_data_obj
    
    Example:
        >>> script = "return config_link.format(fp=user_obj['sub_link_fp'], public_key=user_obj['node_public_key'])"
        >>> generate_constant_node_data_obj(script)
        {'sub_link_fp': 'chrome', 'node_public_key': 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop'}
    """
    keys = extract_user_obj_keys(script_code)
    
    result = {}
    
    # Mock значения для типовых ключей
    mock_values = {
        'sub_link_fp': 'chrome',
        'sub_link_grpc_mode': 'multi',
        'node_public_key': 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop',  # 44 символа base64 (reality, trojan)
        'node_ipv6_subnet': 'fd00::/64',  # Валидная локальная IPv6 подсеть (для WireGuard/AmneziaWG)
        'node_ipv4_subnet': '10.0.0.0/24',  # Валидная приватная IPv4 подсеть
        'node_hop_start': 10000,  # Начальный порт для port hopping (WireGuard/AmneziaWG)
        'node_hop_end': 20000,  # Конечный порт для port hopping
        'node_hash_salt': 'test_salt_for_wg_keys',  # Salt для генерации WireGuard ключей
    }
    
    # Добавляем все ключи из constant_node_data_obj
    for key in keys:
        result[key] = mock_values.get(key, f'mock_{key}')
    
    return result


def extract_jinja_placeholders(url_tmp: str) -> list[str]:
    """
    Парсит url_tmp и извлекает все Jinja2 плейсхолдеры
    
    Ищет паттерны: {{placeholder}}
    
    Args:
        url_tmp: Шаблон config_link из proto_templates.url_tmp
    
    Returns:
        Список уникальных плейсхолдеров (без {{}} скобок)
    
    Example:
        >>> url_tmp = "vless://{user_uuid}@{{node___address}}:{{inbounds___0___port}}#{{node___title}}"
        >>> extract_jinja_placeholders(url_tmp)
        ['node___address', 'inbounds___0___port', 'node___title']
    """
    pattern = r'\{\{([^}]+)\}\}'
    matches = re.findall(pattern, url_tmp)
    return list(set(matches))


def generate_mock_value(key: str) -> str | int | bool:
    """
    Генерирует mock значение для плейсхолдера на основе его имени
    
    Типовые паттерны:
    - *___port → int (443, 8443, и т.д.)
    - *___address → str (IP адрес)
    - *___title → str (название)
    - *___security → str ('tls', 'reality', 'none')
    - *___network → str ('tcp', 'ws', 'grpc', и т.д.)
    - *___path → str ('/api', '/ws', и т.д.)
    - *___ipv6_subnet → str ('fd00::/64')
    - *___ipv4_subnet → str ('10.0.0.0/24')
    - *___public_key / *___pbk → str (base64, 44 символа)
    - *___hop_start / *___hop_end → int (диапазон портов для hopping)
    - *___hash_salt → str (salt для WireGuard)
    - остальное → str ('mock_value')
    
    Args:
        key: Название плейсхолдера (например, 'inbounds___0___port')
    
    Returns:
        Mock значение подходящего типа
    """
    key_lower = key.lower()
    
    # Паттерны для определения типа
    if 'hop_start' in key_lower:
        return 10000  # Начальный порт для hopping
    elif 'hop_end' in key_lower:
        return 20000  # Конечный порт для hopping
    elif 'hash_salt' in key_lower or 'salt' in key_lower:
        return 'test_salt_for_wg_keys'
    elif 'port' in key_lower:
        return 443
    elif 'address' in key_lower:
        return '192.168.1.100'
    elif 'title' in key_lower:
        return 'Test Node Title'
    elif 'security' in key_lower:
        return 'tls'
    elif 'network' in key_lower:
        return 'tcp'
    elif 'path' in key_lower:
        return '/api'
    elif 'host' in key_lower or 'sni' in key_lower or 'servername' in key_lower:
        return 'example.com'
    elif 'mode' in key_lower:
        return 'multi'
    elif 'fp' in key_lower or 'fingerprint' in key_lower:
        return 'chrome'
    elif 'public' in key_lower or 'pbk' in key_lower:
        return 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop'
    elif 'ipv6_subnet' in key_lower or 'ipv6subnet' in key_lower:
        return 'fd00::/64'  # Валидная локальная IPv6 подсеть (для WireGuard/AmneziaWG)
    elif 'ipv4_subnet' in key_lower or 'ipv4subnet' in key_lower:
        return '10.0.0.0/24'  # Валидная приватная IPv4 подсеть
    elif 'sid' in key_lower or 'shortid' in key_lower:
        return '709c400f8da05efa'
    elif 'method' in key_lower:
        return '2022-blake3-aes-256-gcm'
    elif 'psk' in key_lower or 'password' in key_lower:
        return 'test_password_base64_encoded_string'
    else:
        return 'mock_value'


def generate_mock_node_config(placeholders: list[str]) -> dict:
    """
    Генерирует минимальный mock JSON конфиг на основе плейсхолдеров
    
    Использует flatten() обратную логику:
    - 'inbounds___0___port' → {'inbounds': [{'port': 443}]}
    - 'node___address' → {'node': {'address': '192.168.1.100'}}
    - 'shortIds___0' → {'shortIds': ['value']}
    - 'serverNames___0' → {'serverNames': ['value']}
    
    Args:
        placeholders: Список плейсхолдеров из extract_jinja_placeholders()
    
    Returns:
        Nested dict структура для Jinja2 рендеринга
    
    Example:
        >>> placeholders = ['node___address', 'inbounds___0___port']
        >>> generate_mock_node_config(placeholders)
        {'node': {'address': '192.168.1.100'}, 'inbounds': [{'port': 443}]}
        
        >>> placeholders = ['shortIds___0']
        >>> generate_mock_node_config(placeholders)
        {'shortIds': ['709c400f8da05efa']}
    """
    nested_config = {}
    
    for placeholder in placeholders:
        # Пропускаем системные плейсхолдеры (обрабатываются отдельно)
        if placeholder in ('node___address', 'node___title'):
            continue
        
        parts = placeholder.split('___')
        value = generate_mock_value(placeholder)
        
        # Специальный случай: если последняя часть - индекс (например, shortIds___0)
        # Это означает что предпоследний ключ должен быть массивом
        if len(parts) >= 2 and parts[-1].isdigit():
            # Навигация до предпоследнего ключа
            current = nested_config
            for i in range(len(parts) - 2):  # до предпоследнего
                part = parts[i]
                next_part = parts[i + 1]
                
                if part.isdigit():
                    # Индекс - пропускаем (обработан ранее)
                    continue
                
                if next_part.isdigit():
                    # Следующий элемент - индекс массива
                    if part not in current:
                        current[part] = []
                    
                    index = int(next_part)
                    while len(current[part]) <= index:
                        current[part].append({})
                    
                    current = current[part][index]
                else:
                    # Обычный вложенный ключ
                    if part not in current:
                        current[part] = {}
                    current = current[part]
            
            # Теперь устанавливаем предпоследний ключ как массив
            array_key = parts[-2]
            array_index = int(parts[-1])
            
            if array_key not in current:
                current[array_key] = []
            
            # Расширяем массив если нужно
            while len(current[array_key]) <= array_index:
                current[array_key].append(None)
            
            current[array_key][array_index] = value
            
        else:
            # Обычный случай: последняя часть - обычный ключ
            current = nested_config
            
            for i in range(len(parts)):
                part = parts[i]
                is_last = (i == len(parts) - 1)
                
                if part.isdigit():
                    # Индекс - пропускаем (обработано ранее)
                    continue
                
                if is_last:
                    # Последняя часть - устанавливаем значение
                    current[part] = value
                else:
                    # Проверяем следующую часть
                    next_part = parts[i + 1]
                    
                    if next_part.isdigit():
                        # Следующая часть - индекс массива
                        if part not in current:
                            current[part] = []
                        
                        index = int(next_part)
                        while len(current[part]) <= index:
                            current[part].append({})
                        
                        current = current[part][index]
                    else:
                        # Обычный вложенный ключ
                        if part not in current:
                            current[part] = {}
                        current = current[part]
    
    return nested_config


def render_config_link_for_test(
    url_tmp: str,
    node_config_json: dict,
    node_address: str = '192.168.1.100',
    node_title: str = 'Sub Prepare Test Node'
) -> str:
    """
    Рендерит config_link (локальная копия generate_link_from_json для безопасности)
    
    Это копия функции из web.api.protocols.proto_links_templates.handlers,
    но БЕЗ punycode обработки (она перенесена в sub_api.py).
    
    Args:
        url_tmp: Шаблон из proto_templates.url_tmp
        node_config_json: Mock конфиг ноды (dict структура)
        node_address: IP/домен ноды для подстановки
        node_title: Название ноды для подстановки
    
    Returns:
        Отрендеренная config_link строка (сырая, БЕЗ URL encoding и БЕЗ punycode!)
    
    Example:
        >>> url_tmp = "vless://{user_uuid}@{{node___address}}:{{inbounds___0___port}}#{{node___title}}"
        >>> mock_config = {'inbounds': [{'port': 443}]}
        >>> render_config_link_for_test(url_tmp, mock_config)
        'vless://{user_uuid}@192.168.1.100:443#Sub Prepare Test Node'
    """
    if not url_tmp:
        raise ValueError('url_tmp не может быть пустым')
    
    if isinstance(node_config_json, str):
        node_config_json = orjson.loads(node_config_json)
    
    flat_config = flatten(node_config_json, separator='___')
    
    # Собираем контекст для Jinja2 (БЕЗ punycode - это делается в sub_api.py)
    context = {
        **flat_config,
        'node___address': node_address,
        'node___title': node_title,
    }
    
    # Рендерим через Jinja2
    template = Template(url_tmp)
    config_url = template.render(context)
    
    return config_url
