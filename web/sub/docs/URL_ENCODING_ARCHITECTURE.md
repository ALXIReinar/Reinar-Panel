# URL Encoding Architecture для VPN ссылок

## Обзор

Архитектура URL encoding для VPN ссылок (vless://, vmess://, trojan://, wireguard://, и т.д.) в ReinarPanel.

### Проблема

VPN ссылки могут содержать:
- **Кириллические домены** в query параметрах (`?sni=пример.рф`)
- **Base64 ключи** с спецсимволами (`+`, `/`, `=`)
- **Эмодзи и non-ASCII символы** в node_title
- **Пробелы и спецсимволы**

Без корректного кодирования VPN клиенты не смогут распарсить ссылку.

### Решение

URL encoding применяется **в 3 этапа** на разных уровнях:

## 1. `generate_link_from_json()` - Генерация базовой ссылки

**Файл**: `web/api/protocols/proto_links_templates/handlers.py`

**Ответственность**:
- ✅ **Punycode для hostname** - конвертирует IDN домены
- ✅ **Quote для fragment** - кодирует `node_title`
- ❌ **НЕ трогает query параметры** - они подставляются "as is"

**Пример**:
```python
generate_link_from_json(
    tmp_link="vless://{user_uuid}@{{node___address}}:{{port}}#{{node___title}}",
    node_config_json={"port": 443},
    node_ip_or_domain="пример.рф",  # ← Кириллица
    node_title="My Node 🚀"  # ← Пробелы и эмодзи
)
# → "vless://{user_uuid}@xn--e1afmkfd.xn--p1ai:443#My%20Node%20%F0%9F%9A%80"
```

**Что обрабатывается**:
1. **Hostname** - проверяет через `IPvAnyAddress()`, если не IP → Punycode через `.encode('idna')`
2. **Fragment** - кодирует через `quote(node_title)`

**Что НЕ обрабатывается**:
- Query параметры (обрабатываются позже в `normalize_url()`)

---

## 2. `prepare_sub()` скрипты - Подстановка пользовательских данных

**Файлы**: Хранятся в БД (`proto_templates.sub_prepare_script`)

**Ответственность**:
- ✅ **Кодируют userinfo часть** (между `://` и `@`)
- ✅ **Подставляют значения** через `.format()`
- ❌ **НЕ кодируют query параметры** - это делается в `normalize_url()`

### Пример для WireGuard:

```python
def prepare_sub(user_obj: dict, config_link: str) -> str:
    # 1. Генерируем приватный ключ (raw base64)
    raw_b64_key = base64.b64encode(priv_key.private_bytes(...)).decode("utf-8")
    # Пример: "ABC+DEF/GHI=" (содержит +, /, =)
    
    # 2. КРИТИЧНО: кодируем для userinfo части
    user_private_key = urllib.parse.quote(raw_b64_key, safe="")
    # Результат: "ABC%2BDEF%2FGHI%3D"
    
    # 3. Публичный ключ сервера (тоже base64)
    server_public_key = urllib.parse.quote(user_obj["node_public_key"], safe="")
    
    # 4. Подставляем в ссылку
    final_link = config_link.format(
        user_private_key=user_private_key,  # ← В userinfo части
        server_public_key=server_public_key,  # ← В query части (закодирован)
        user_ip=user_ip,
        reserved_bytes=reserved_str,
    )
    
    return final_link
```

**Результат**:
```
wireguard://ABC%2BDEF%2FGHI%3D@example.com:51820?public_key=XYZ%2B123&local_address=10.0.0.2/32#node
          └─────────────────┘                     └──────────┘
          userinfo (закодировано)                 query (закодировано)
```

### Пример для VLESS/Trojan (без userinfo):

```python
def prepare_sub(user_obj: dict, config_link: str):
    # Просто подставляем значения
    return config_link.format(
        user_uuid=user_obj['user_uuid'],
        fp=user_obj['sub_link_fp'],
        public_key=user_obj['node_public_key']  # ← НЕ кодируем здесь!
    )
```

**Результат**:
```
vless://{user_uuid}@example.com:443?fp=chrome&pbk=ABC+DEF/GHI=#node
                                                └──────────────┘
                                                НЕ закодировано (будет закодировано в normalize_url)
```

---

## 3. `normalize_url()` - Финальное кодирование query параметров

**Файл**: `web/sub/api/handlers/prepare_func.py`

**Вызывается**: В `sub_api.py` после выполнения `prepare_sub` скрипта

**Ответственность**:
- ✅ **Кодирует query параметры** через `urlencode(params, quote_via=quote)`
- ✅ **Защита от двойного кодирования** - `parse_qsl()` декодирует, `urlencode()` кодирует заново корректно
- ✅ **Работает с любыми символами** - кириллица, base64, эмодзи, пробелы
- ❌ **НЕ трогает scheme, userinfo, hostname, port, fragment**

**Реализация**:
```python
def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_query = urlencode(query_params, quote_via=quote)
    return urlunparse(parsed._replace(query=normalized_query))
```

**Пример**:
```python
# Вход: prepare_sub вернул ссылку с незакодированной кириллицей
url = "vless://uuid@example.com?sni=пример.рф&fp=chrome#node"

# Выход: query параметры закодированы
normalize_url(url)
# → "vless://uuid@example.com?sni=%D0%BF%D1%80%D0%B8%D0%BC%D0%B5%D1%80.%D1%80%D1%84&fp=chrome#node"
```

**Защита от двойного кодирования**:
```python
# prepare_sub вернул УЖЕ закодированный query параметр
url = "vless://uuid@example.com?pbk=ABC%2BDEF%2FGHI%3D#node"

# parse_qsl() декодирует → [('pbk', 'ABC+DEF/GHI=')]
# urlencode() кодирует заново → "pbk=ABC%2BDEF%2FGHI%3D"
normalize_url(url)
# → "vless://uuid@example.com?pbk=ABC%2BDEF%2FGHI%3D#node"
# ✅ НЕТ двойного кодирования (%252B)
```

---

## Полный E2E Flow

### Пример для VLESS Reality:

```
1. generate_link_from_json()
   Вход: tmp_link="vless://{user_uuid}@{{node___address}}:{{port}}?sni={{sni}}&pbk={{public_key}}#{{node___title}}"
         node_ip_or_domain="пример.рф"
         node_title="My Node 🚀"
         config_json={"port": 443, "sni": "тест.com", "public_key": "ABC+DEF/"}
   
   Выход: "vless://{user_uuid}@xn--e1afmkfd.xn--p1ai:443?sni=тест.com&pbk=ABC+DEF/#My%20Node%20%F0%9F%9A%80"
          └─────────────────────────────────────┘                         └────────────────────────┘
          Hostname в Punycode                                             Fragment закодирован

2. prepare_sub()
   Вход: config_link (из шага 1)
         user_obj={'user_uuid': '550e8400-...', 'sub_link_fp': 'chrome'}
   
   Выход: "vless://550e8400-...@xn--e1afmkfd.xn--p1ai:443?sni=тест.com&pbk=ABC+DEF/&fp=chrome#My%20Node%20%F0%9F%9A%80"
          └──────────────┘                                                                        
          user_uuid подставлен

3. normalize_url()
   Вход: результат из шага 2
   
   Выход: "vless://550e8400-...@xn--e1afmkfd.xn--p1ai:443?sni=%D1%82%D0%B5%D1%81%D1%82.com&pbk=ABC%2BDEF%2F&fp=chrome#My%20Node%20%F0%9F%9A%80"
                                                         └────────────────────────┘   └──────────────┘
                                                         Кириллица закодирована       Base64 закодирован

4. Клиент получает финальную ссылку:
   - Hostname в Punycode ✅
   - Query параметры закодированы ✅
   - Fragment закодирован ✅
   - Нет двойного кодирования ✅
```

---

## Правила для prepare_sub скриптов

### ✅ ЧТО нужно кодировать:

1. **Userinfo часть** (между `://` и `@`):
   ```python
   # Для WireGuard, AmneziaWG
   user_private_key = urllib.parse.quote(raw_b64_key, safe="")
   final_link = config_link.format(user_private_key=user_private_key)
   # → wireguard://ABC%2BDEF%2FGHI%3D@...
   ```

2. **Reserved bytes** (для WireGuard WARP):
   ```python
   reserved_str = urllib.parse.quote(f"{b0},{b1},{b2}")
   # → "10%2C20%2C30"
   ```

### ❌ ЧТО НЕ нужно кодировать:

1. **Query параметры** - кодируются автоматически в `normalize_url()`:
   ```python
   # ❌ НЕПРАВИЛЬНО:
   fp = urllib.parse.quote(user_obj['sub_link_fp'])
   
   # ✅ ПРАВИЛЬНО:
   fp = user_obj['sub_link_fp']  # normalize_url() закодирует если нужно
   ```

2. **Hostname** - уже закодирован в `generate_link_from_json()`:
   ```python
   # ❌ НЕПРАВИЛЬНО:
   address = urllib.parse.quote(user_obj['node_address'])
   
   # ✅ ПРАВИЛЬНО:
   address = user_obj['node_address']  # Уже в Punycode
   ```

---

## Тестирование

### Integration тесты:
- **Файл**: `web/sub/tests/integration/test_sub_prepare_scripts.py`
- **Покрытие**: Все 55 шаблонов из БД
- **Проверки**:
  - ✅ Скрипт выполняется без ошибок
  - ✅ Все плейсхолдеры заменены
  - ✅ Нет двойного кодирования (`%252B`, `%252F`, `%253D`)

### Unit тесты:
- **Файл**: `web/sub/tests/unit/test_normalize_url.py`
- **Покрытие**: 23 теста для различных edge cases
- **Проверки**:
  - ✅ Кириллица в query
  - ✅ Base64 ключи
  - ✅ Эмодзи
  - ✅ Пробелы
  - ✅ Защита от двойного кодирования
  - ✅ Сохранение scheme, userinfo, hostname, port, fragment

---

## FAQ

### Q: Почему не кодировать query параметры в prepare_sub скриптах?

**A**: Централизация логики. Если каждый скрипт будет кодировать сам, то:
- Появятся ошибки (кто-то забудет закодировать)
- Возможно двойное кодирование (скрипт закодировал → normalize_url закодировала ещё раз)
- Дублирование кода (в 55 скриптах)

### Q: Что если админ сохранит кириллический домен в `constant_node_data_obj`?

**A**: Два варианта:
1. **Punycode** (рекомендуется) - админ сохраняет `xn--e1afmkfd.xn--p1ai` вместо `пример.рф`
2. **URL encoding** (автоматически) - `normalize_url()` закодирует кириллицу в query

### Q: Почему `+` превращается в `%20` в тесте?

**A**: `parse_qsl()` декодирует `+` в пробел (это стандарт `application/x-www-form-urlencoded`). 
Затем `urlencode()` кодирует пробел в `%20`. 

Это **НЕ проблема**, потому что:
- prepare_sub скрипты УЖЕ кодируют base64 через `quote(key, safe="")` → `+` превращается в `%2B`
- `normalize_url()` получает УЖЕ закодированный `%2B` и оставляет его без изменений

### Q: Нужно ли кодировать Punycode домены?

**A**: Нет. Punycode это валидный ASCII (`xn--e1afmkfd.xn--p1ai`), его не нужно кодировать.

---

## Итоговая архитектура

```
┌──────────────────────────────────────────────────────────────────────┐
│  generate_link_from_json()                                           │
│  ✅ Punycode для hostname                                            │
│  ✅ Quote для fragment                                                │
│  ❌ НЕ трогает query параметры                                       │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  prepare_sub() скрипт                                                │
│  ✅ Кодирует userinfo часть (WireGuard private key)                  │
│  ✅ Подставляет user_uuid, user_sub_id, и т.д.                       │
│  ❌ НЕ кодирует query параметры                                      │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  normalize_url() в sub_api.py                                        │
│  ✅ Кодирует query параметры                                         │
│  ✅ Защита от двойного кодирования                                   │
│  ❌ НЕ трогает scheme, userinfo, hostname, port, fragment            │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   VPN клиент           │
                    │   ✅ Корректная ссылка │
                    └────────────────────────┘
```

---

**Дата**: 2026-08-25  
**Версия**: 1.0  
**Автор**: ReinarPanel Team
