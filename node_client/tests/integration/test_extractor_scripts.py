"""
Интеграционные тесты для валидации extractor скриптов

Проверяет что все extractors из таблицы templates_users_extractors:
- Выполняются без ошибок
- Возвращают корректный тип данных (dict или string)
- Соответствуют JSON Schema для своего протокола

Extractor = функция трансформации суперобъекта пользователя в формат конфига ядра.

Примеры:
- xray-vless: {'user_uuid': '...', 'flow': '...'} → {'id': '...', 'email': '...', 'flow': '...', 'level': 0}
- singbox-wg: {'user_uuid': '...', 'node_hash_salt': '...'} → {'name': '...', 'public_key': '...', 'allowed_ips': [...]}

Запуск:
    pytest node_client/tests/integration/test_extractor_scripts.py --protocol=* -v
    pytest node_client/tests/integration/test_extractor_scripts.py --protocol=xray -v
    pytest node_client/tests/integration/test_extractor_scripts.py --protocol=singbox -v
"""
import uuid as uuid_lib

import jsonschema
import pytest

from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.tests.schemas.extractor_schemas import (
    get_schema_for_template,
    get_expected_type_for_cursor
)
from node_client.tests.utils.extractor_helpers import (
    generate_constant_node_data_obj_for_extractor
)
from node_client.tests.utils.user_helpers import create_vpn_like_user


@pytest.mark.asyncio
@pytest.mark.db
async def test_extractor_scripts_execution(protocol_templates_with_extractors):
    """
    Проверка: extractor скрипты корректно трансформируют user_obj
    
    Для каждого шаблона с extractors:
    1. Генерирует mock constant_node_data_obj на основе ключей в extractor_script
    2. Создаёт user_super_obj через create_vpn_like_user()
    3. Компилирует extractor через HotReloadExecutor.get_compiled_func()
    4. Вызывает transform(user_obj)
    5. Валидирует результат:
       - Если cursor содержит 'stats___users' → проверяет что result это string
       - Иначе → валидирует через JSON Schema
    
    Формат отчёта (как в sub тестах):
    ✅ xray-vless-reality-tcp: OK
    ✅ xray-vmess-tls-ws: OK
    ❌ xray-trojan-tls-tcp: FAILED - 'password' is a required property
    
    Итого: 18/20 extractors passed
    
    ВАЖНО: Проверяются только шаблоны с is_accepted = true + singbox-wg (id=83)
    """
    results = []
    errors = []
    
    for template in protocol_templates_with_extractors:
        extractors = template.get('extractors') or []
        
        # Пропускаем шаблоны без extractors
        if not extractors:
            continue
        
        for extractor in extractors:
            extractor_id = extractor.get('id', 'unknown')
            cursor = extractor['flatten_array_cursor']
            
            try:
                # 1. Генерируем constant_node_data_obj на основе ключей в extractor_script
                constant_node_data_obj = generate_constant_node_data_obj_for_extractor(
                    extractor['extractor_script']
                )
                
                # 2. Создаём user_super_obj
                ok, user_obj = create_vpn_like_user(
                    user_uuid=str(uuid_lib.uuid4()),
                    user_sub_id=42,
                    required_user_data_obj=template['required_user_data_obj'],
                    constant_user_data_obj=template['constant_user_data_obj'],
                    constant_node_data_obj=constant_node_data_obj
                )
                
                if not ok:
                    raise ValueError(f"Failed to create user_obj: {user_obj}")
                
                # 3. Компилируем extractor через HotReloadExecutor
                transform_func = HotReloadExecutor.get_compiled_func(
                    func_script=extractor['extractor_script'],
                    func_name='transform',
                    libs=extractor.get('libs')
                )
                
                # 4. Вызываем transform
                result = transform_func(user_obj)
                
                # 5. Валидация по типу
                expected_type = get_expected_type_for_cursor(cursor)
                
                if expected_type == 'string':
                    # Проверяем что вернулась строка (для v2ray_api stats)
                    if not isinstance(result, (str, int)):
                        raise TypeError(
                            f"Expected str or int for cursor '{cursor}', got {type(result).__name__}"
                        )
                    
                    results.append({
                        'template': template['title'],
                        'extractor_id': extractor_id,
                        'cursor': cursor,
                        'status': 'OK',
                        'result_type': type(result).__name__
                    })
                    
                elif expected_type == 'dict':
                    # Валидация через JSON Schema
                    if not isinstance(result, dict):
                        raise TypeError(
                            f"Expected dict for cursor '{cursor}', got {type(result).__name__}"
                        )
                    
                    # Пытаемся получить схему. Если её нет - пропускаем валидацию
                    try:
                        schema = get_schema_for_template(template['title'])
                        jsonschema.validate(result, schema)
                    except ValueError as schema_error:
                        # Схема не определена для этого шаблона - пропускаем
                        results.append({
                            'template': template['title'],
                            'extractor_id': extractor_id,
                            'cursor': cursor,
                            'status': 'SKIPPED (no schema)',
                            'result_type': 'dict'
                        })
                        continue
                    
                    results.append({
                        'template': template['title'],
                        'extractor_id': extractor_id,
                        'cursor': cursor,
                        'status': 'OK',
                        'result_type': 'dict'
                    })
                else:
                    raise ValueError(f"Unknown expected_type: {expected_type}")
                
            except jsonschema.ValidationError as e:
                # JSON Schema валидация провалилась
                errors.append({
                    'template': template['title'],
                    'extractor_id': extractor_id,
                    'cursor': cursor,
                    'error_type': 'Schema Validation',
                    'error': e.message,
                    'path': ' -> '.join(str(p) for p in e.path) if e.path else 'root'
                })
                
            except Exception as e:
                # Любая другая ошибка (компиляция, выполнение, и т.д.)
                errors.append({
                    'template': template['title'],
                    'extractor_id': extractor_id,
                    'cursor': cursor,
                    'error_type': type(e).__name__,
                    'error': str(e),
                    'path': 'N/A'
                })
    
    # ========== ОТЧЁТ (как в sub тестах) ==========
    
    print("\n" + "="*80)
    print("EXTRACTOR SCRIPTS VALIDATION REPORT")
    print("="*80)
    print()
    
    # Успешные результаты
    if results:
        print("✅ PASSED EXTRACTORS:")
        for r in results:
            print(f"   ✅ {r['template']}")
            print(f"      Cursor: {r['cursor']}")
            print(f"      Result type: {r['result_type']}")
        print()
    
    # Ошибки
    if errors:
        print("❌ FAILED EXTRACTORS:")
        for e in errors:
            print(f"   ❌ {e['template']}")
            print(f"      Cursor: {e['cursor']}")
            print(f"      Error type: {e['error_type']}")
            print(f"      Error: {e['error']}")
            if e['path'] != 'N/A':
                print(f"      Path: {e['path']}")
        print()
    
    # Итоговая статистика
    total = len(results) + len(errors)
    passed = len(results)
    failed = len(errors)
    
    print("="*80)
    print(f"ИТОГО: {passed}/{total} extractors passed")
    
    if failed > 0:
        print(f"       {failed} extractors FAILED")
    
    print("="*80)
    print()
    
    # Assert только в конце (чтобы увидеть ВСЕ ошибки, а не только первую)
    assert len(errors) == 0, (
        f"\n{len(errors)} extractors failed validation. "
        f"See detailed report above."
    )
