"""Отладочный скрипт для проверки prepare_sub"""
import asyncio
import os
os.environ['ENV_LOCAL_TEST_FILE'] = 'web/sub/.env.sub.test'

async def main():
    # Тестируем генерацию config_link
    from web.sub.tests.utils.prepare_sub_helpers import (
        extract_jinja_placeholders,
        generate_mock_node_config,
        render_config_link_for_test
    )
    
    url_tmp = 'vless://{user_uuid}@{{node___address}}:{{inbounds___0___port}}?encryption=none&flow={flow}&security={{inbounds___0___streamSettings___security}}&sni={{inbounds___0___streamSettings___realitySettings___serverNames___0}}&fp={fp}&pbk={public_key}&sid={{inbounds___0___streamSettings___realitySettings___shortIds___0}}&type={{inbounds___0___streamSettings___network}}#{{node___title}}'
    
    print("=== url_tmp ===")
    print(url_tmp)
    
    placeholders = extract_jinja_placeholders(url_tmp)
    print(f"\n=== Jinja2 плейсхолдеры ({{{{}}}}): {len(placeholders)} ===")
    print(placeholders)
    
    mock_config = generate_mock_node_config(placeholders)
    print(f"\n=== Mock config ===")
    import json
    print(json.dumps(mock_config, indent=2))
    
    config_link = render_config_link_for_test(
        url_tmp=url_tmp,
        node_config_json=mock_config,
        node_address="192.168.1.100",
        node_title="VNode 10 Active"
    )
    
    print(f"\n=== config_link (после рендеринга Jinja2) ===")
    print(config_link)
    
    # Проверяем что остались одинарные плейсхолдеры
    import re
    single_braces = re.findall(r'\{([^}]+)\}', config_link)
    print(f"\n=== Одинарные плейсхолдеры ({{}}): {len(single_braces)} ===")
    print(single_braces)

if __name__ == '__main__':
    asyncio.run(main())
