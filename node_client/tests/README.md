# 🧪 Тестирование Node Client

## Структура тестов

```
tests/
├── unit/                          # Unit-тесты (изолированные компоненты)
│   ├── test_write_buffer_utils.py
│   ├── test_write_buffer_registration.py
│   ├── test_write_buffer_crud.py
│   └── test_write_buffer_workers.py
│
├── integrate/                     # Integration-тесты (API endpoints)
│   ├── test_node_config_api.py
│   ├── test_proto_core_users_api.py
│   └── test_execute_api.py
│
├── e2e/                           # E2E тесты (шаблоны + ядра)
│   └── (будет создано)
│
└── utils/                         # Утилиты и хелперы
    ├── db_helpers.py
    ├── fake_core.py
    └── test_data_factory.py
```

---

## 🚀 Быстрый старт

### Запуск всех тестов (mock режим):
```bash
python -m pytest node_client/tests/ -v
```

### Запуск конкретной группы:
```bash
# Unit тесты
python -m pytest node_client/tests/unit/ -v

# Integration тесты
python -m pytest node_client/tests/integrate/ -v

# E2E тесты
python -m pytest node_client/tests/e2e/ -v
```

---

## ⚙️ CLI аргументы

### `--mode` - Режим тестирования

**Mock режим** (по умолчанию):
```bash
python -m pytest node_client/tests/ --mode=mock
```
- ✅ Быстрый запуск
- ✅ Без Docker
- ✅ Моки библиотек (xtlsapi, grpcio, requests)
- ✅ Подходит для CI/CD
- ⚠️ Пропускает тесты с маркером `@pytest.mark.real_core`

**Real режим**:
```bash
python -m pytest node_client/tests/ --mode=real
```
- ✅ Полное E2E тестирование
- ✅ Реальные VPN ядра в Docker
- ⚠️ Требует Docker и настроенные контейнеры
- ⚠️ Медленнее mock режима

---

### `--vpn-core` - Выбор VPN ядер

Указывает для каких ядер запускать E2E тесты (через запятую):

**Одно ядро:**
```bash
python -m pytest node_client/tests/e2e/ --vpn-core=xray
```

**Несколько ядер:**
```bash
python -m pytest node_client/tests/e2e/ --vpn-core=xray,hysteria2,shadowsocks
```

**Все доступные ядра** (если не указано, используется `--protocol`):
```bash
python -m pytest node_client/tests/e2e/  # по умолчанию xray
```

---

### `--protocol` - Старый формат (deprecated)

⚠️ **Устарел, используйте `--vpn-core`**

```bash
python -m pytest node_client/tests/ --protocol=xray
```

---

## 📊 Маркеры тестов

Pytest маркеры используются для фильтрации и категоризации тестов:

### `@pytest.mark.real_core`
Тесты требующие реальное VPN ядро в Docker

```python
@pytest.mark.real_core
async def test_xray_add_user_real():
    """Этот тест запустится только в --mode=real"""
    ...
```

**Поведение:**
- `--mode=mock` → пропускаются
- `--mode=real` → выполняются

---

### `@pytest.mark.vpn_core`
Тесты параметризованные по VPN ядрам

```python
@pytest.mark.vpn_core
@pytest.mark.parametrize("template", templates, ids=lambda t: t['title'])
async def test_template_script(template):
    """Этот тест запустится для каждого ядра из --vpn-core"""
    ...
```

**Поведение:**
- Фильтруются по `--vpn-core=xray,hysteria2`
- Только указанные ядра тестируются

---

### `@pytest.mark.db`
Тесты требующие доступ к БД

```python
@pytest.mark.db
async def test_load_template_from_db(db_pool):
    ...
```

**Запустить только DB тесты:**
```bash
python -m pytest node_client/tests/ -m db
```

---

### `@pytest.mark.slow`
Медленные тесты (батчинг, таймауты, асинхронность)

```python
@pytest.mark.slow
async def test_batching_timeout():
    """Тест с await asyncio.sleep(10)"""
    ...
```

**Пропустить slow тесты:**
```bash
python -m pytest node_client/tests/ -m "not slow"
```

---

### `@pytest.mark.security`
Тесты проверяющие sandbox безопасности HotReloadExecutor

```python
@pytest.mark.security
async def test_sandbox_blocks_open():
    """Проверка что sandbox блокирует опасные операции"""
    ...
```

**Использование:**
- Проверяют что `exec()` sandbox блокирует `open()`, `eval()`, `__import__()`
- Проверяют разрешённые builtins (`int`, `str`, `len`, etc.)

**Запустить только security тесты:**
```bash
python -m pytest node_client/tests/ -m security
```

---

### `@pytest.mark.error_handling`
Тесты проверяющие обработку ошибок в HotReloadExecutor

```python
@pytest.mark.error_handling
async def test_script_syntax_error():
    """Проверка детальных сообщений об ошибках"""
    ...
```

**Использование:**
- SyntaxError с указанием строки и позиции
- Runtime ошибки с полным traceback
- ImportError для несуществующих библиотек
- Отсутствие требуемой функции в скрипте

**Запустить только error_handling тесты:**
```bash
python -m pytest node_client/tests/ -m error_handling
```

---

## 🎯 Примеры использования

### CI/CD (GitHub Actions, GitLab CI):
```bash
# Быстрый прогон всех тестов без Docker
python -m pytest node_client/tests/ --mode=mock -v --tb=short
```

### Локальная разработка - тестирование Xray:
```bash
# Mock режим (без Docker)
python -m pytest node_client/tests/e2e/ --vpn-core=xray --mode=mock

# Real режим (с Docker)
python -m pytest node_client/tests/e2e/ --vpn-core=xray --mode=real
```

### Тестирование всех ядер перед релизом:
```bash
python -m pytest node_client/tests/e2e/ --vpn-core=xray,hysteria2,shadowsocks --mode=real -v
```

### Быстрая проверка после изменений:
```bash
# Только быстрые тесты
python -m pytest node_client/tests/ -m "not slow" --mode=mock
```

### Отладка конкретного теста:
```bash
python -m pytest node_client/tests/integrate/test_node_config_api.py::test_read_config_success -v -s
```

---

## 📈 Статистика покрытия

**Текущее покрытие: 147 тестов**

- ✅ 28 unit-тестов HotReloadExecutor (11 с реальными скриптами из БД, 17 infrastructure)
- ✅ 56 unit-тестов ConfigWriteBuffer
- ✅ 51 integration-тестов (API endpoints)
- ✅ 12 infrastructure тестов

**HotReloadExecutor тесты:**
- 5 unified тестов (mock + real режимы): add_user, delete_user, bulk_add, bulk_delete, get_metrics
- 5 тестов импорта библиотек (используют БД скрипты)
- 4 security тестов (sandbox)
- 4 error_handling тестов
- 5 async/sync тестов (используют БД скрипты)
- 2 теста типов user_obj (используют БД скрипты)

### Запуск с coverage:
```bash
python -m pytest node_client/tests/ --cov=node_client --cov-report=html
```

---

## 🛠️ Фикстуры

### Database фикстуры:
- `db_pool` - пул соединений с тестовой БД
- `protocol_template` - загружает шаблон протокола
- `all_templates` - все активные шаблоны

### Config фикстуры:
- `base_config_path` - путь к vless-tcp-server-metrics.json
- `working_config_path` - рабочая копия конфига
- `temp_config_path` - изолированный конфиг для теста

### Buffer фикстуры:
- `fast_buffer` - ConfigWriteBuffer с timeout=1s
- `mock_core_buffer` - ConfigWriteBuffer с timeout=0.5s

### Mode фикстуры:
- `test_mode` - "mock" или "real"
- `enabled_vpn_cores` - список ядер из `--vpn-core`
- `is_real_mode` - bool для проверки режима
- `is_mock_mode` - bool для проверки режима

---

## 🐛 Troubleshooting

### Проблема: "ValueError: Шаблон для протокола 'xray' не найден в БД"
**Решение:** В тестовой БД нет этого шаблона. Используйте доступный:
```bash
python -m pytest --vpn-core=hysteria2
```

### Проблема: Тесты пропускаются в real режиме
**Причина:** Docker контейнеры не запущены

**Решение:**
```bash
# Проверьте Docker
docker ps

# Запустите контейнеры
docker-compose up -d
```

### Проблема: Медленные тесты
**Решение:** Пропустите slow тесты:
```bash
python -m pytest -m "not slow"
```

---

## 📝 Добавление новых тестов

### Unit тест:
```python
# node_client/tests/unit/test_new_feature.py
import pytest

async def test_new_feature():
    assert True
```

### E2E тест с параметризацией:
```python
# node_client/tests/e2e/test_new_protocol.py
import pytest

@pytest.mark.vpn_core
@pytest.mark.parametrize("template", all_templates, ids=lambda t: t['title'])
async def test_protocol_feature(template):
    # Этот тест запустится для каждого ядра из --vpn-core
    assert True
```

### Real core тест:
```python
@pytest.mark.real_core
async def test_with_docker():
    # Запустится только с --mode=real
    assert True
```

---

## 🚦 Best Practices

1. **Mock по умолчанию** - используйте `--mode=mock` для быстрой итерации
2. **Real перед коммитом** - запускайте `--mode=real` перед пушем в репозиторий
3. **Изолируйте тесты** - используйте `tmp_path` для файловых операций
4. **Параметризуйте** - один тест для всех протоколов через `@pytest.mark.parametrize`
5. **Маркируйте правильно** - добавляйте `@pytest.mark.slow` для долгих тестов

---

## 📚 Дополнительные ресурсы

- [Pytest документация](https://docs.pytest.org/)
- [Pytest маркеры](https://docs.pytest.org/en/stable/how-to/mark.html)
- [Pytest parametrize](https://docs.pytest.org/en/stable/how-to/parametrize.html)
