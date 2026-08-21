"""
Интеграционные тесты для prepare_sub скриптов

Проверяет что все скрипты prepare_sub из proto_templates:
- Компилируются без ошибок
- Выполняются без exceptions
- Заменяют все плейсхолдеры (нет фигурных скобок в результате)
- Возвращают валидную строку

Использует реальные скрипты из БД, mock конфиги, и настоящую generate_link_from_json.

Запуск:
    pytest web/sub/tests/integration/test_sub_prepare_scripts.py -v
    pytest web/sub/tests/integration/test_sub_prepare_scripts.py::test_sub_prepare_script_execution -v
"""
import re
import pytest
import uuid as uuid_lib

from web.sub.api.handlers.prepare_func import create_vpn_like_user
from web.sub.sandbox.script_executor import ScriptExecutor
from web.sub.tests.utils.prepare_sub_helpers import (
    extract_jinja_placeholders,
    generate_mock_node_config,
    render_config_link_for_test
)


@pytest.mark.asyncio
@pytest.mark.db
async def test_sub_prepare_script_execution(sub_prepare_infrastructure):
    """
    Тестирует выполнение всех prepare_sub скриптов из БД
    
    Для каждого шаблона с sub_prepare_script:
    1. Загружает данные из фикстуры (template, constant_node_data_obj)
    2. Генерирует mock node_config через helper
    3. Рендерит config_link через render_config_link_for_test (использует generate_link_from_json)
    4. Создаёт user_super_obj через create_vpn_like_user
    5. Вызывает ScriptExecutor.executing_link_processing
    6. Проверяет:
       - ✅ success=True (скрипт выполнился без ошибок)
       - ✅ Нет одиночных фигурных скобок {} в результате (все плейсхолдеры заменены)
       - ⚠️  Схема протокола присутствует (warning если отсутствует, не ронает тест)
    
    ВАЖНО: Фикстура sub_prepare_infrastructure уже создала:
    - constant_node_data_obj для каждого шаблона (на основе скрипта)
    - nodes_protocols записи с заполненными данными
    """
    errors = []
    warnings = []
    success_count = 0
    
    for template_id, data in sub_prepare_infrastructure.items():
        template = data['template']
        constant_node_data_obj = data['constant_node_data_obj']
        node_address = data['node_address']
        node_title = data['node_title']
        
        try:
            # 1. Извлекаем Jinja2 плейсхолдеры из url_tmp
            placeholders = extract_jinja_placeholders(template['url_tmp'])
            
            # 2. Генерируем mock node config
            mock_config = generate_mock_node_config(placeholders)
            
            # 3. Рендерим config_link через generate_link_from_json (БЕЗ punycode!)
            try:
                config_link = render_config_link_for_test(
                    url_tmp=template['url_tmp'],
                    node_config_json=mock_config,
                    node_address=node_address,
                    node_title=node_title
                )
            except Exception as e:
                errors.append({
                    'template': template['title'],
                    'step': 'render_config_link',
                    'error': f"{type(e).__name__}: {str(e)}"
                })
                continue
            
            # 4. Создаём user_super_obj
            user_uuid = str(uuid_lib.uuid4())
            user_sub_id = f"test_sub_{template_id}"
            
            ok, user_super_obj = create_vpn_like_user(
                user_uuid=user_uuid,
                user_sub_id=user_sub_id,
                required_user_data_obj=template['required_user_data_obj'],
                constant_user_data_obj=template['constant_user_data_obj'],
                constant_node_data_obj=constant_node_data_obj,
            )
            
            if not ok:
                errors.append({
                    'template': template['title'],
                    'step': 'create_user_super_obj',
                    'error': user_super_obj
                })
                continue

            # 5. Вызываем prepare_sub через ScriptExecutor
            success, output = await ScriptExecutor.executing_link_processing(
                sub_prepare_script=template['sub_prepare_script'],
                required_libs=template['sub_required_libs'],
                user_obj=user_super_obj,
                config_link=config_link
            )

            # 6. Проверки результата
            if not success:
                errors.append({
                    'template': template['title'],
                    'step': 'execute_prepare_sub',
                    'error': output,
                    'config_link': config_link[:200]  # Первые 200 символов для дебага
                })
                continue
            
            # Теперь output это результат выполнения скрипта (str)

            # 6.1. Проверка что result - строка
            if not isinstance(output, str):
                errors.append({
                    'template': template['title'],
                    'step': 'validate_result_type',
                    'error': f"Expected str, got {type(output).__name__}",
                    'result': str(output)[:200]
                })
                continue
            
            # 6.2. Проверка что нет одиночных фигурных скобок (все плейсхолдеры заменены)
            # ВАЖНО: двойные {{ }} в Jinja2 это нормально, проверяем только одиночные { }
            single_brace_pattern = r'(?<!\{)\{(?!\{)[^}]*\}(?!\})'
            unresolved = re.findall(single_brace_pattern, output)
            
            if unresolved:
                errors.append({
                    'template': template['title'],
                    'step': 'check_placeholders_resolved',
                    'error': f"Unresolved placeholders found: {unresolved[:5]}",  # Первые 5 для дебага
                    'result': output[:300]
                })
                continue
            
            # 6.3. Warning: проверка наличия схемы протокола (не критично)
            # Типичные схемы: vless://, vmess://, ss://, trojan://, hysteria2://, и т.д.
            if '://' not in output:
                warnings.append({
                    'template': template['title'],
                    'warning': 'No protocol scheme (scheme://) found in result',
                    'result': output[:200]
                })
            
            success_count += 1
            
        except Exception as e:
            # Неожиданная ошибка вне try-catch блоков
            errors.append({
                'template': template['title'],
                'step': 'unexpected_error',
                'error': f"{type(e).__name__}: {str(e)}",
                'traceback': str(e)
            })
    
    # Формируем отчёт
    total_templates = len(sub_prepare_infrastructure)
    
    print(f"\n{'='*80}")
    print(f"Sub Prepare Scripts Test Report")
    print(f"{'='*80}")
    print(f"Total templates: {total_templates}")
    print(f"Success: {success_count}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    print(f"{'='*80}\n")
    
    # Выводим warnings (не ронают тест)
    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"\n  Template: {w['template']}")
            print(f"  Warning: {w['warning']}")
            print(f"  Result preview: {w['result']}")
    
    # Выводим errors (ронают тест)
    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for err in errors:
            print(f"\n  Template: {err['template']}")
            print(f"  Step: {err['step']}")
            print(f"  Error: {err['error']}")
            if 'config_link' in err:
                print(f"  Config link: {err['config_link']}")
            if 'result' in err:
                print(f"  Result: {err['result']}")
        
        # Провалить тест с подробным отчётом
        pytest.fail(
            f"\n\n{len(errors)}/{total_templates} prepare_sub scripts failed!\n"
            f"See detailed error report above."
        )
    
    # Если все прошли - выводим успех
    print(f"\n✅ All {success_count}/{total_templates} prepare_sub scripts executed successfully!\n")


@pytest.mark.asyncio
@pytest.mark.db
async def test_sub_prepare_infrastructure_fixture(sub_prepare_infrastructure):
    """
    Проверяет что фикстура sub_prepare_infrastructure корректно создана
    
    Это вспомогательный тест для валидации самой фикстуры.
    """
    assert len(sub_prepare_infrastructure) > 0, "No templates with sub_prepare_script found!"
    
    for template_id, data in sub_prepare_infrastructure.items():
        # Проверяем структуру данных
        assert 'template' in data
        assert 'node_proto_id' in data
        assert 'constant_node_data_obj' in data
        assert 'node_address' in data
        assert 'node_title' in data
        
        template = data['template']
        
        # Проверяем что шаблон имеет обязательные поля
        assert template['id'] == template_id
        assert template['sub_prepare_script'] is not None
        assert template['url_tmp'] is not None
        assert template['required_user_data_obj'] is not None
        
        # Проверяем что constant_node_data_obj это dict
        assert isinstance(data['constant_node_data_obj'], dict)
        
        print(f"✓ Template {template['title']} (id={template_id}): "
              f"constant_node_data_obj has {len(data['constant_node_data_obj'])} keys")
    
    print(f"\n✅ Fixture validated: {len(sub_prepare_infrastructure)} templates loaded")


@pytest.mark.asyncio
@pytest.mark.db
async def test_sub_prepare_no_double_encoding(sub_prepare_infrastructure):
    """
    Проверка: prepare_sub не делает двойное URL кодирование
    
    Проверяем что спецсимволы закодированы ОДИН раз:
    - "+" → "%2B" (не "%252B")
    - "/" → "%2F" (не "%252F")
    - "=" → "%3D" (не "%253D")
    
    Двойное кодирование происходит когда:
    1. prepare_sub делает quote() для своих значений
    2. Потом где-то ещё применяется quote() повторно
    
    Результат двойного кодирования: "%2B" превращается в "%252B"
    (процент закодирован в %25)
    
    ВАЖНО: Этот тест НЕ проверяет корректность самих значений,
    только отсутствие двойного кодирования.
    """
    errors = []
    success_count = 0
    
    for template_id, data in sub_prepare_infrastructure.items():
        template = data['template']
        constant_node_data_obj = data['constant_node_data_obj']
        node_address = data['node_address']
        node_title = data['node_title']
        
        try:
            # 1. Генерируем config_link (как в основном тесте)
            placeholders = extract_jinja_placeholders(template['url_tmp'])
            mock_config = generate_mock_node_config(placeholders)
            
            config_link = render_config_link_for_test(
                url_tmp=template['url_tmp'],
                node_config_json=mock_config,
                node_address=node_address,
                node_title=node_title
            )
            
            # 2. Создаём user_super_obj
            user_uuid = str(uuid_lib.uuid4())
            user_sub_id = f"test_sub_{template_id}"
            
            ok, user_super_obj = create_vpn_like_user(
                user_uuid=user_uuid,
                user_sub_id=user_sub_id,
                required_user_data_obj=template['required_user_data_obj'],
                constant_user_data_obj=template['constant_user_data_obj'],
                constant_node_data_obj=constant_node_data_obj,
            )
            
            if not ok:
                # Пропускаем если не смогли создать user_obj
                continue
            
            # 3. Выполняем prepare_sub
            success, final_link = await ScriptExecutor.executing_link_processing(
                sub_prepare_script=template['sub_prepare_script'],
                required_libs=template['sub_required_libs'],
                user_obj=user_super_obj,
                config_link=config_link
            )
            
            if not success:
                # Пропускаем если prepare_sub провалился
                # (это проверяется в основном тесте)
                continue
            
            # 4. ПРОВЕРКА: нет двойного кодирования
            # Паттерны двойного кодирования:
            # %2X → %252X (например, %2B → %252B)
            # %3X → %253X (например, %3D → %253D)
            double_encoded_patterns = [
                '%252',  # %2X закодирован дважды
                '%253',  # %3X закодирован дважды
            ]
            
            found_double_encoding = []
            for pattern in double_encoded_patterns:
                if pattern in final_link:
                    # Ищем контекст вокруг паттерна
                    idx = final_link.find(pattern)
                    context = final_link[max(0, idx-20):idx+30]
                    found_double_encoding.append(f"{pattern} in context: ...{context}...")
            
            if found_double_encoding:
                errors.append({
                    'template': template['title'],
                    'error_type': 'Double URL Encoding Detected',
                    'details': found_double_encoding,
                    'explanation': (
                        'URL encoding was applied twice. '
                        'For example: "+" → "%2B" → "%252B" '
                        '(the percent sign itself got encoded as %25)'
                    ),
                    'link_preview': final_link[:300]
                })
            else:
                success_count += 1
                
        except Exception as e:
            # Неожиданная ошибка - записываем но не ронаем тест
            # (основные ошибки проверяются в test_sub_prepare_script_execution)
            pass
    
    # Формируем отчёт
    total_tested = len(sub_prepare_infrastructure)
    
    print(f"\n{'='*80}")
    print(f"Double Encoding Check Report")
    print(f"{'='*80}")
    print(f"Total templates tested: {total_tested}")
    print(f"No double encoding: {success_count}")
    print(f"Double encoding detected: {len(errors)}")
    print(f"{'='*80}\n")
    
    # Выводим errors если есть
    if errors:
        print(f"\n❌ DOUBLE ENCODING DETECTED ({len(errors)} templates):")
        for err in errors:
            print(f"\n  Template: {err['template']}")
            print(f"  Error: {err['error_type']}")
            print(f"  Details:")
            for detail in err['details']:
                print(f"    - {detail}")
            print(f"  Explanation: {err['explanation']}")
            print(f"  Link preview: {err['link_preview']}")
        
        # Провалить тест
        pytest.fail(
            f"\n\n{len(errors)}/{total_tested} templates have DOUBLE URL ENCODING!\n"
            f"This means URL encoding was applied more than once.\n"
            f"See detailed report above."
        )
    
    print(f"\n✅ All {success_count}/{total_tested} templates: NO double encoding detected!\n")
