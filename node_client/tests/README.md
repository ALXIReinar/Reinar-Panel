# Node Client Tests

## Фикстуры для работы с шаблонами

### `protocol_templates` — список всех шаблонов

Возвращает **список всех** шаблонов найденных по фильтру `--protocol`.

**Использование:**
```python
async def test_all_templates_have_scripts(protocol_templates):
    """Тест запускается ОДИН раз, но проверяет ВСЕ шаблоны"""
    for template in protocol_templates:
        assert template['api_bulk_add_user_script'], f"{template['title']} missing script"
        assert template['api_bulk_delete_user_script'], f"{template['title']} missing script"
```

**Важно:** Тест **упадёт при первой ошибке** (fail fast). Это корректное поведение — если хоть один шаблон неправильный, тест должен упасть.

## CLI аргументы

### `--protocol`

Фильтр для загрузки шаблонов из БД. Использует `LIKE '%filter%'` запрос.

**Примеры:**

```bash
# ВСЕ шаблоны (24 шаблона: xray + sing-box)
pytest --protocol='*'

# Все xray шаблоны (20 шаблонов)
pytest --protocol=xray

# Все vless шаблоны на любом ядре (5 шаблонов)
pytest --protocol=vless

# Только xray-vless шаблоны (5 шаблонов)
pytest --protocol=xray-vless

# Конкретный шаблон (1 шаблон)
pytest --protocol=xray-vless-reality-tcp

# Несколько фильтров через запятую (OR условие)
pytest --protocol=shadowsocks,trojan
```

### `--mode`

Режим запуска VPN-ядра:
- `mock` (по умолчанию) — моки библиотек, без реальных ядер
- `real` — реальные Docker контейнеры с VPN-ядрами

```bash
# Тесты с моками (быстрые)
pytest --mode=mock

# Тесты с реальными ядрами в Docker (медленные)
pytest --mode=real
```

## Примеры запуска

```bash
# Все интеграционные тесты с xray шаблонами
python -m pytest node_client/tests/integrate/ --protocol=xray -v

# Тесты для ВСЕХ шаблонов (включая sing-box)
python -m pytest node_client/tests/integrate/ --protocol='*' -v

# Конкретный тест для всех vless шаблонов
python -m pytest node_client/tests/test_infrastructure.py --protocol=vless -v -s

# Тест с реальным xray ядром в Docker
python -m pytest node_client/tests/ --protocol=xray-vless-reality-tcp --mode=real -v

# Только unit тесты (не требуют БД и шаблонов)
python -m pytest node_client/tests/unit/ -v
```

## Структура шаблонов

Каждый шаблон (dict) содержит:

```python
{
    'id': int,
    'title': str,  # Формат: CORE-PROTOCOL-TRANSPORT (e.g., xray-vless-reality-tcp)
    'proto_python_lib': str,  # Библиотеки через запятую (e.g., 'xtlsapi,uuid')
    'api_bulk_add_user_script': str,  # Python скрипт для добавления пользователей
    'api_bulk_delete_user_script': str,  # Python скрипт для удаления пользователей
    'reload_core_command': str,
    'metrics_command': str,
    'api_metrics_script': str,
    'metrics_parser_code': str,
    'bulk_add_script_custom_params': dict,
    'bulk_delete_script_custom_params': dict,
    'is_accepted': bool,
    'status': str
}
```

## Fail Fast Behavior

Тесты которые проверяют несколько шаблонов в цикле **упадут при первой ошибке**:

```python
async def test_all_templates(protocol_templates):
    for template in protocol_templates:
        assert template['api_bulk_add_user_script']  # Упадёт на первом шаблоне без скрипта
```

Это правильное поведение — если хоть один шаблон неправильный, разработчик должен это исправить немедленно.

## Инициализация seed_data

Перед запуском тестов убедитесь что тестовая БД инициализирована:

```bash
# Загрузить шаблоны в тестовую БД
python -m web.db.seed_data
```

Seed data автоматически загружает:
- 24 шаблона протоколов (xray-*, sing-box-*)
- Статусы (templates_statuses, pay_statuses, online_statuses)
- Протоколы (protocols)
- Extractors (templates_users_extractors)
- Spec params (template_spec_params)
