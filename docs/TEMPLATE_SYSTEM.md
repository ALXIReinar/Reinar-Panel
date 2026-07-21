# 📋 Система шаблонов ReinarPanel

Документация по всем шаблонизированным компонентам системы.

---

## 🎯 1. Шаблоны конфиг-ссылок (Config Link Templates)

**Таблица:** `proto_templates`

**Назначение:** Генерация клиентских конфиг-ссылок (vless://, vmess://, ss://)

### Правила шаблонизации:

1. **Jinja2 синтаксис** для значений из конфига: `{{key}}`
2. **Flatten-json ключи** с разделителем `___` (тройное подчёркивание)
3. **Плейсхолдер для UUID**: `{user_uuid}` (без двойных фигурных скобок!)

### Примеры:

```
vless://{user_uuid}@{{node_ip}}:{{inbounds___1___port}}?encryption=none&flow={{inbounds___1___settings___clients___0___flow}}&security={{inbounds___1___streamSettings___security}}&sni={{inbounds___1___streamSettings___realitySettings___serverNames___0}}&fp={{inbounds___1___streamSettings___realitySettings___fingerprint}}&pbk={{pbk}}&sid={{inbounds___1___streamSettings___realitySettings___shortIds___1}}&type={{inbounds___1___streamSettings___network}}#{{node_title}}
```

**Разделитель:** `___` (тройное подчёркивание)
- Защита от конфликтов с ключами, содержащими одинарное `_`
- Пример: `inbounds.1.port` → `inbounds___1___port`

**Spec params** (специальные параметры):
- Значения, которых нет в конфиг-файле
- Пример: `pbk` (public key для Reality)
- Хранятся в таблице `template_spec_params`

**Workflow:**
1. Шаблон рендерится при записи конфига на ноду
2. `{user_uuid}` подставляется при выдаче подписки пользователю

---

## 👤 2. Шаблоны пользовательских объектов (User Object Templates)

**Таблица:** `proto_templates`

**Назначение:** Генерация объектов пользователей для конфигов протоколов

### Поля шаблона:

#### `required_user_data_obj` (JSONB)
Обязательные данные пользователя с маркерами подстановки.

**Поддерживаемые маркеры:**

| Маркер | Описание | Обязательность |
|--------|----------|----------------|
| `{USER_UUID}` | UUID пользователя | Всегда доступен |
| `{USER_TG_USERNAME}` | Telegram username | Опционально |
| `{USER_CUSTOM:field_name}` | Кастомное поле из `additional_fields` | Опционально |

**Примеры для разных протоколов:**

```json
// Xray VLESS (с email)
{
  "id": "{USER_UUID}",
  "email": "{USER_TG_USERNAME}"
}

// Shadowsocks (только UUID)
{
  "password": "{USER_UUID}"
}

// WireGuard (кастомные поля)
{
  "PublicKey": "{USER_CUSTOM:public_key}",
  "AllowedIPs": "{USER_UUID}"
}

// Trojan (с SNI)
{
  "password": "{USER_UUID}",
  "sni": "{USER_CUSTOM:domain}"
}
```

#### `constant_user_data_obj` (JSONB)
Константные данные, одинаковые для всех пользователей.

**Пример:**
```json
{
  "flow": "xtls-rprx-vision",
  "level": 0
}
```

#### `clients_path` (VARCHAR)
Путь до массива клиентов в конфиге (flatten-json формат с `___`).

**Пример:**
```
inbounds___1___settings___clients
```

### Workflow добавления пользователя:

```python
# 1. Шаблон из БД
template = {
  "id": "{USER_UUID}",
  "email": "{USER_TG_USERNAME}"
}

# 2. Данные из запроса
uuid = "abc-123-def"
tg_username = "john_doe"

# 3. Резолвинг через resolve_user_template()
resolved = {
  "id": "abc-123-def",
  "email": "john_doe"
}

# 4. Добавление константных данных
final = {
  "id": "abc-123-def",
  "email": "john_doe",
  "flow": "xtls-rprx-vision",
  "level": 0
}

# 5. Запись в конфиг-файл ноды
```

### Валидация:

- Если маркер `{USER_TG_USERNAME}` используется, но `tg_username` не передан → **ValueError**
- Если маркер `{USER_CUSTOM:field}` используется, но `field` отсутствует в `additional_fields` → **ValueError**
- Ошибки валидации логируются и возвращаются в `trouble_nodes`


---




## ⚠️ Важные нюансы

1. **Тройное подчёркивание `___`** - защита от конфликтов ключей
2. **`{user_uuid}` vs `{{user_uuid}}`** - первое для финальной подстановки, второе для Jinja2
3. **Маркеры регистрозависимы** - `{USER_UUID}` ≠ `{user_uuid}`
4. **Валидация шаблонов** - ошибки ловятся до отправки на ноду
5. **Hot-reload + файл** - двухэтапная запись для мгновенного доступа и персистентности
